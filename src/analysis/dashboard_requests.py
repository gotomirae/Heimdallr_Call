# PRD Ref: §7 · §9.1 — 대시보드 클릭형 LLM 분석 큐
"""대시보드에서 접수한 단건 분석을 비용 가드 뒤에서 처리한다.

Vercel 요청 안에서 30~60초짜리 모델 호출을 실행하지 않는다. API는 큐에만 쓰고,
이 worker가 pending/deferred 요청을 순서대로 claim한다. 일·월 사용량이 소진되면
deferred로 남겨 다음 예약 실행이 자동으로 이어받는다.
"""

from __future__ import annotations

import argparse
import re
import time
from copy import copy
from datetime import datetime, timezone

from src.analysis.analyze import AnalysisError, BudgetExceeded, analyze, save, validate_payload
from src.analysis.run import build_input
from src.config.constants import DASHBOARD_ON_DEMAND_EXCERPT_MAX_CHARS
from src.db.supabase_client import get_client
from src.utils.console import enable_utf8_stdout
from src.utils.cost_guard import check_budget


def inaccessible_search_domain(error: Exception) -> bool:
    """Anthropic가 검색 허용 도메인을 거부한 호출인지 Provider SDK 타입 없이 판정한다.

    ADR 9에 따라 SDK 예외를 분석 도메인 계약으로 끌어올리지 않는다. 이 400은 모델
    생성 전 도구 설정 검증에서 난 것이므로 같은 Provider를 웹검색 없이 한 번 실행한다.
    """
    message = str(error).lower()
    return "domains are not accessible to our user agent" in message


def input_too_large(error: Exception) -> bool:
    """무료 사전 계측에서 입력 토큰 상한을 넘긴 경우만 식별한다."""
    message = str(error)
    return isinstance(error, AnalysisError) and "입력 " in message and "토큰이 상한" in message


def output_truncated(error: Exception) -> bool:
    """비용이 발생했지만 출력 상한에서 잘린 웹검색 응답인지 식별한다."""
    message = str(error)
    return isinstance(error, AnalysisError) and "max_tokens(" in message and "걸려 잘렸다" in message


def recoverable_failed_error(message: str | None) -> bool:
    """코드 보강 뒤 딱 한 번만 자동 재개할 과거 실패."""
    text = message or ""
    if "자동복구 실패" in text:
        return False
    return (
        "domains are not accessible to our user agent" in text
        or "max_tokens(" in text
        or "유료 응답 구조 검증 실패" in text
    )


def provider_usage_resume_at(message: str | None) -> datetime | None:
    """Provider 400이 밝힌 재개 시각. 로컬 비용 실링과 별개이므로 추측하지 않는다."""
    match = re.search(
        r"regain access on (\d{4}-\d{2}-\d{2}) at (\d{2}:\d{2}) UTC",
        message or "",
        re.I,
    )
    if not match:
        return None
    return datetime.fromisoformat(f"{match.group(1)}T{match.group(2)}:00+00:00")


def deferred_ready(row: dict, *, now: datetime | None = None) -> bool:
    resume_at = provider_usage_resume_at(row.get("error"))
    return resume_at is None or resume_at <= (now or datetime.now(timezone.utc))


def strict_repair(data, label: str):
    """compact strict 계약을 한 번만 실행하고 재실패를 영구 재시도와 구분한다."""
    compact = copy(data)
    compact.excerpt = (getattr(data, "excerpt", "") or "")[:DASHBOARD_ON_DEMAND_EXCERPT_MAX_CHARS]
    try:
        return analyze(compact, env="prod", web_search=False)
    except Exception as exc:
        raise AnalysisError(f"{label}: 자동복구 실패 — {exc}") from exc


def pending_rows(limit: int) -> list[dict]:
    db = get_client()
    result = (
        db.table("dashboard_analysis_requests")
        .select("id,request_key,code,fiscal_year,fiscal_quarter,status,requested_at,error")
        .in_("status", ["pending", "deferred"])
        .order("requested_at")
        .limit(max(100, limit * 10))
        .execute()
    )
    rows = [row for row in (result.data or []) if deferred_ready(row)][:limit]
    if len(rows) >= limit:
        return rows
    # 2026-09-24 이전 검색 허용 도메인 설정 실패는 모델 생성 전 400이었다. 코드가
    # 웹검색 없는 strict 계약으로 복구할 수 있게 된 뒤에도 failed에 영구 고정되므로 재개한다.
    failed = (
        db.table("dashboard_analysis_requests")
        .select("id,request_key,code,fiscal_year,fiscal_quarter,status,requested_at,error")
        .eq("status", "failed")
        .order("requested_at")
        .limit(100)
        .execute()
    )
    recoverable = [row for row in (failed.data or []) if recoverable_failed_error(row.get("error"))]
    return [*rows, *recoverable[:limit - len(rows)]]


def claim(row: dict) -> bool:
    db = get_client()
    result = (
        db.table("dashboard_analysis_requests")
        .update({"status": "working", "claimed_at": datetime.now(timezone.utc).isoformat(), "error": None})
        .eq("id", row["id"])
        .in_("status", ["pending", "deferred", "failed"])
        .execute()
    )
    return bool(result.data)


def set_status(row_id: int, status: str, *, error: str | None = None) -> None:
    payload: dict[str, object] = {"status": status, "error": error}
    if status == "completed":
        payload["completed_at"] = datetime.now(timezone.utc).isoformat()
    get_client().table("dashboard_analysis_requests").update(payload).eq("id", row_id).execute()


def run(limit: int, max_seconds: float) -> int:
    started = time.monotonic()
    done = failed = deferred = 0
    for row in pending_rows(limit):
        if time.monotonic() - started >= max_seconds:
            break
        budget = check_budget()
        if not budget.allowed:
            # 한도가 회복되면 같은 deferred 행을 다음 실행이 다시 집는다.
            set_status(row["id"], "deferred", error=str(budget.reason))
            deferred += 1
            break
        if not claim(row):
            continue
        label = f"{row['code']} {row['fiscal_year']}.{row['fiscal_quarter']}Q"
        try:
            data = build_input(
                row["code"], year=row["fiscal_year"], quarter=row["fiscal_quarter"],
                allow_fetch=True,
            )
            data.analysis_stage = "dashboard_on_demand"
            try:
                result = analyze(data, env="prod", web_search=True)
            except Exception as exc:
                if inaccessible_search_domain(exc):
                    print(f"⚠ {label} · 검색 허용 도메인 거부 — 같은 Provider로 공개 원문 검색 없이 재시도")
                    result = strict_repair(data, label)
                elif output_truncated(exc):
                    print(f"⚠ {label} · 웹검색 출력 상한 도달 — compact strict 계약으로 1회 자동 복구")
                    result = strict_repair(data, label)
                elif input_too_large(exc):
                    print(
                        f"⚠ {label} · 검색 도구 포함 입력 상한 초과 — 구조화 재무는 유지하고 "
                        f"공시 발췌를 {DASHBOARD_ON_DEMAND_EXCERPT_MAX_CHARS}자로 줄여 웹검색을 먼저 재시도"
                    )
                    compact = copy(data)
                    compact.excerpt = (data.excerpt or "")[:DASHBOARD_ON_DEMAND_EXCERPT_MAX_CHARS]
                    try:
                        result = analyze(compact, env="prod", web_search=True)
                    except Exception as compact_search_exc:
                        if not input_too_large(compact_search_exc):
                            raise
                        print(
                            f"⚠ {label} · 압축 후에도 검색 계약이 입력 상한 초과 — "
                            "검색 전용 선택 필드를 뺀 strict 계약으로 재시도"
                        )
                        result = strict_repair(data, label)
                else:
                    raise
            problems = validate_payload(result.payload)
            if problems:
                # 웹검색은 forced strict tool과 함께 쓸 수 없어 드물게 일부 필드만 온다(T96).
                # 유료 응답을 화면에 숨긴 채 끝내지 않고, 검색을 끈 compact strict 계약으로
                # 딱 한 번 복구한다. 두 호출 모두 비용 장부에는 이미 기록된다.
                print(
                    f"⚠ {label} · 웹검색 결과 구조 오류 — strict 계약으로 1회 자동 복구: "
                    f"{'; '.join(problems[:4])}"
                )
                result = strict_repair(data, label)
                problems = validate_payload(result.payload)
                if problems:
                    raise AnalysisError(
                        f"{label}: strict 복구 결과도 검증 실패 — {'; '.join(problems[:8])}"
                    )
            save(result)
            set_status(row["id"], "completed")
            done += 1
            print(f"✓ {label} · 대시보드 요청 분석 완료 · ${result.cost_usd:.4f}")
        except BudgetExceeded as exc:
            set_status(row["id"], "deferred", error=str(exc))
            deferred += 1
            print(f"⏳ {label} · 사용량 갱신 대기")
            break
        except AnalysisError as exc:
            resume_at = provider_usage_resume_at(str(exc))
            if resume_at is not None:
                set_status(row["id"], "deferred", error=str(exc)[:500])
                deferred += 1
                print(f"⏳ {label} · Provider 사용량 한도 — {resume_at.isoformat()} 이후 자동 재개")
                break
            set_status(row["id"], "failed", error=str(exc)[:500])
            failed += 1
            print(f"✗ {label} · {exc}")
        except Exception as exc:
            resume_at = provider_usage_resume_at(str(exc))
            if resume_at is not None:
                set_status(row["id"], "deferred", error=str(exc)[:500])
                deferred += 1
                print(f"⏳ {label} · Provider 사용량 한도 — {resume_at.isoformat()} 이후 자동 재개")
                break
            set_status(row["id"], "failed", error=f"{type(exc).__name__}: {exc}"[:500])
            failed += 1
            print(f"✗ {label} · {type(exc).__name__}: {exc}")
    print(f"대시보드 LLM 요청: 완료 {done} · 실패 {failed} · 사용량 대기 {deferred}")
    return 1 if failed else 0


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="대시보드 클릭형 LLM 분석 큐")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--max-seconds", type=float, default=240)
    args = parser.parse_args()
    return run(args.limit, args.max_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
