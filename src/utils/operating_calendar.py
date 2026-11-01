# PRD Ref: §10 · ADR50
"""한국 휴일/시각 판정. 16시 실행과 공시 시즌 판정은 서로 독립적이다."""
from __future__ import annotations

import argparse
from datetime import date, datetime
from zoneinfo import ZoneInfo

import holidays

from src.config.constants import EARNINGS_SEASON_WINDOWS, INDICATORS_HOUR_KST, KOREA_EXTRA_HOLIDAYS

KST = ZoneInfo("Asia/Seoul")


def indicator_day(day: date) -> bool:
    # SC: 대체/임시 공휴일도 제외. 추가 지정일은 ISO 날짜로만 입력한다.
    extra = {date.fromisoformat(value.strip()) for value in KOREA_EXTRA_HOLIDAYS}
    return day.weekday() < 5 and day not in holidays.KR(years=day.year, observed=True) and day not in extra


def indicators_due(now: datetime) -> bool:
    local = now.astimezone(KST)
    return indicator_day(local.date()) and local.hour >= INDICATORS_HOUR_KST


def earnings_season(day: date) -> bool:
    return any((m1, d1) <= (day.month, day.day) <= (m2, d2)
               for m1, d1, m2, d2 in EARNINGS_SEASON_WINDOWS)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("indicators", "disclosure"))
    parser.add_argument("--output")
    parser.add_argument("--complete", action="store_true")
    args = parser.parse_args()
    now = datetime.now(KST)
    allowed = indicators_due(now) if args.kind == "indicators" else (
        earnings_season(now.date()) or indicators_due(now) and now.hour == INDICATORS_HOUR_KST)
    if args.kind == "disclosure":
        from src.db.job_runs import is_complete, mark_complete
        slot = f"disclosure-{now.hour // 2}"
        if args.complete:
            mark_complete(slot, now.date())
            return 0
        if allowed:
            allowed = not is_complete(slot, now.date())
    if args.output:
        with open(args.output, "a", encoding="utf-8") as stream:
            stream.write(f"run={str(allowed).lower()}\n")
    print(f"{args.kind}: {now.isoformat()} run={allowed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
