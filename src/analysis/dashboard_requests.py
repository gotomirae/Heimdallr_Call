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
from src.analysis.run import build_input, load_narrative_history, load_previous_analysis
from src.config.constants import (
    ANALYSIS_REQUEST_DAILY_LIMIT,
    ANALYSIS_PREVIOUS_MAX_CHARS,
    DASHBOARD_ANALYSIS_INPUT_TOKEN_BUDGET,
    DASHBOARD_ON_DEMAND_EXCERPT_MAX_CHARS,
)
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
        return analyze(compact, env="prod", web_search=False, token_budget=DASHBOARD_ANALYSIS_INPUT_TOKEN_BUDGET)
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
    from src.analysis.pro_worker import run_once
    db = get_client()
    old = db.table("dashboard_analysis_requests").select("*").in_("status", ["pending", "deferred"]).order("requested_at").range(0, limit - 1).execute().data or []
    for row in old:
        db.rpc("pro_enqueue_analysis", {"p_request": {
            "request_key": f"company:{row['code']}:{row['fiscal_year']}:{row['fiscal_quarter']}",
            "kind": "company", "target": row["code"], "fiscal_year": row["fiscal_year"], "fiscal_quarter": row["fiscal_quarter"],
            "historical": False, "force_analysis": False, "daily_limit": ANALYSIS_REQUEST_DAILY_LIMIT,
        }}).execute()
        set_status(row["id"], "completed", error="MIGRATED_TO_PRO_QUEUE")
    result = run_once()
    print(result)
    return 1 if result.get("status") == "failed" else 0


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="대시보드 클릭형 LLM 분석 큐")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--max-seconds", type=float, default=240)
    args = parser.parse_args()
    return run(args.limit, args.max_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
