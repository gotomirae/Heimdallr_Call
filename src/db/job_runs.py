# PRD Ref: §10 · traps.md T23, T217, T229
"""배치 실행 완료 표식 — pg_cron 정시 실행과 GitHub 예비 schedule이 같은 날 둘 다 돌 때 뒤의 것을 끝낸다.

    python -m src.db.job_runs gate --job universe_daily --timeout-minutes 90 --gate-output "$GITHUB_OUTPUT"
    python -m src.db.job_runs done --job universe_daily

★ 게이트는 두 가지를 본다.
  ① 오늘(KST) 이미 완료됐는가 → skip
  ② 지금 시작하면 **장 시작(09:00 KST) 전에 끝날 수 있는가** → 못 끝나면 skip(평일만)
     `price_run`은 시작 시각의 러너 날짜(UTC)로 라벨을 고정한다. 06:00 시작 실행이 09:00을 넘기면
     장중가가 **어제 날짜의 종가**로 저장되고, 09:00 이후 시작하면 오늘 날짜의 종가가 된다(T217).
     에러 없이 다음 정상 실행이 덮을 때까지 그대로 읽힌다. 16:00 KST 이후는 확정 종가라 안전하다.
★ 판정 실패(표 없음·DB 장애)는 skip=false(= 그냥 돈다) — 표식은 비용 절감이지 정합성 방어선이 아니다.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.config.constants import KOREA_MARKET_COMPLETED_HOUR_KST, KOREA_MARKET_OPEN_HOUR_KST
from src.utils.console import enable_utf8_stdout

KST = ZoneInfo("Asia/Seoul")
TABLE = "job_runs"


def run_day(now: datetime) -> date:
    return now.astimezone(KST).date()


def unsafe_start(now: datetime, timeout_minutes: int) -> bool:
    """평일에 지금 시작하면 잡 제한시간 안에 장중(09:00~16:00 KST)에 걸릴 수 있는가.

    손계산(timeout 90분): 06:00 → 안전(07:30 종료) · 07:30 → 안전(09:00 정각 종료)
    · 07:31 → 위험 · 12:00 → 위험 · 15:59 → 위험 · 16:00 → 안전 · 토요일 10:00 → 안전
    """
    kst = now.astimezone(KST)
    if kst.weekday() >= 5:
        return False
    day = kst.replace(hour=0, minute=0, second=0, microsecond=0)
    opens = day + timedelta(hours=KOREA_MARKET_OPEN_HOUR_KST)
    completes = day + timedelta(hours=KOREA_MARKET_COMPLETED_HOUR_KST)
    return kst + timedelta(minutes=timeout_minutes) > opens and kst < completes


def gate_decision(complete: bool, now: datetime, timeout_minutes: int) -> tuple[bool, str]:
    if complete:
        return True, "오늘 이미 완료"
    if unsafe_start(now, timeout_minutes):
        return True, f"지금 시작하면 {timeout_minutes}분 안에 장중에 걸린다 — 16:00 KST 이후 재시도에 맡긴다"
    return False, "실행"


def is_complete(job: str, day: date) -> bool:
    from src.db.supabase_client import get_client

    rows = (
        get_client().table(TABLE).select("status")
        .eq("job", job).eq("run_day", day.isoformat()).limit(1).execute().data
        or []
    )
    return bool(rows) and rows[0].get("status") == "complete"


def mark_complete(job: str, day: date, detail: dict | None = None) -> None:
    from src.db.supabase_client import get_client

    get_client().table(TABLE).upsert(
        {
            "job": job, "run_day": day.isoformat(), "status": "complete",
            "finished_at": datetime.now(timezone.utc).isoformat(), "detail": detail or {},
        },
        on_conflict="job,run_day",
    ).execute()


def gate(job: str, timeout_minutes: int, output: str | None) -> int:
    now = datetime.now(KST)
    day = run_day(now)
    try:
        complete = is_complete(job, day)
    except Exception as exc:
        print(f"⚠ {TABLE} 조회 실패({type(exc).__name__}) — 완료 여부 모름으로 진행")
        complete = False
    skip, reason = gate_decision(complete, now, timeout_minutes)
    print(f"{job} · run_day {day} · {now:%H:%M} KST · {reason} → skip={str(skip).lower()}")
    if output:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write(f"skip={str(skip).lower()}\n")
    return 0


def done(job: str, detail: dict | None = None) -> int:
    day = run_day(datetime.now(KST))
    try:
        mark_complete(job, day, detail)
    except Exception as exc:
        # 표식 실패가 잡을 실패로 만들면 안 된다 — 본 작업은 끝났다. 다음 예비 실행이 한 번 더 돌 뿐이다.
        print(f"⚠ {TABLE} 완료 표식 실패({type(exc).__name__}) — docs/migrations/cron_universe_daily.sql 적용 확인")
        return 0
    print(f"✓ {job} · run_day {day} 완료 표식")
    return 0


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="배치 실행 완료 표식(게이트)")
    parser.add_argument("action", choices=["gate", "done"])
    parser.add_argument("--job", required=True)
    parser.add_argument("--timeout-minutes", type=int, default=0, help="잡 제한시간 — 장중 겹침 판정")
    parser.add_argument("--gate-output", help="게이트 결과를 덧붙일 파일($GITHUB_OUTPUT)")
    parser.add_argument("--run-id", help="표식에 남길 GitHub run id")
    args = parser.parse_args()
    if args.action == "gate":
        return gate(args.job, args.timeout_minutes, args.gate_output)
    return done(args.job, {"run_id": args.run_id} if args.run_id else None)


if __name__ == "__main__":
    raise SystemExit(main())
