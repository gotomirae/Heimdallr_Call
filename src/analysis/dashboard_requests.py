# PRD Ref: §7 · §9.1 — 대시보드 클릭형 LLM 분석 큐
"""대시보드에서 접수한 단건 분석을 비용 가드 뒤에서 처리한다.

Vercel 요청 안에서 30~60초짜리 모델 호출을 실행하지 않는다. API는 큐에만 쓰고,
이 worker가 pending/deferred 요청을 순서대로 claim한다. 일·월 사용량이 소진되면
deferred로 남겨 다음 예약 실행이 자동으로 이어받는다.
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone

from src.analysis.analyze import AnalysisError, BudgetExceeded, analyze, save
from src.analysis.run import build_input
from src.db.supabase_client import get_client
from src.utils.console import enable_utf8_stdout
from src.utils.cost_guard import check_budget


def pending_rows(limit: int) -> list[dict]:
    db = get_client()
    result = (
        db.table("dashboard_analysis_requests")
        .select("id,request_key,code,fiscal_year,fiscal_quarter,status,requested_at")
        .in_("status", ["pending", "deferred"])
        .order("requested_at")
        .limit(limit)
        .execute()
    )
    return result.data or []


def claim(row: dict) -> bool:
    db = get_client()
    result = (
        db.table("dashboard_analysis_requests")
        .update({"status": "working", "claimed_at": datetime.now(timezone.utc).isoformat(), "error": None})
        .eq("id", row["id"])
        .in_("status", ["pending", "deferred"])
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
            result = analyze(data, env="prod", web_search=True)
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
            set_status(row["id"], "failed", error=str(exc)[:500])
            failed += 1
            print(f"✗ {label} · {exc}")
        except Exception as exc:
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
