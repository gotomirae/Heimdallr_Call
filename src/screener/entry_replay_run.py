# PRD Ref: §8.8 · JARVIS INTEGRATION_TASKS B-12 — 과거 2시즌 replay
"""M1·M2·M5(M3·M4 제외) 통과 표본 수를 과거 실적 시즌에 재생해 센다(읽기 전용).

    python -m src.screener.entry_replay_run                    # 최근 2시즌
    python -m src.screener.entry_replay_run --write docs/decisions/024-jarvis-entry-checks.md

replay 우선 검증 원칙(CLAUDE.md): 라이브 이벤트를 기다리지 않고 과거 데이터를 재생한다.
같은 판정 함수(`src/screener/entry_checks.py`)를 쓰고 **날짜 d 이전 데이터만** 본다.

한계(결과와 함께 출력한다)
  · PRI는 일별 이력이 없다 — `screen_results.pri`는 그 분기의 **최신 재계산값**이다.
    그래서 PRI 포함·제외 두 가지로 센다.
  · M5는 KIS가 최근 약 30거래일만 주므로 replay는 네이버 투자자별 매매로 판정한다.
  · 연간 컨센서스는 날짜 d 이전 스냅샷만 쓴다(없으면 데이터 없음 = 통과).
"""

from __future__ import annotations

import argparse
import bisect
import collections
import math
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.config.constants import ENTRY_DAILY_LOOKBACK_CALENDAR_DAYS
from src.notify.entry_checks_run import (
    FUNDAMENTAL_COLUMNS,
    SCREEN_COLUMNS,
    first_announcements,
    fundamental_series,
    prior_year_actual,
    to_bars,
)
from src.screener.entry_checks import (
    all_of,
    m1_fundamental,
    m1_price,
    m2_check,
    m5_check,
)
from src.utils.console import enable_utf8_stdout

KST = ZoneInfo("Asia/Seoul")
#: 시즌 하나를 이루는 최소 첫 공시 종목 수. 이보다 적은 분기는 아직 시즌이 아니다.
SEASON_MIN_ANNOUNCEMENTS = 50
#: 시즌 첫 공시일부터 볼 거래일 수(다음 시즌 시작 전까지로 다시 자른다).
SEASON_TRADING_DAYS = 60
NAVER_FLOW_ROWS_PER_PAGE = 20


def _qi(year: int, quarter: int) -> int:
    return year * 4 + quarter - 1


def pick_seasons(announcements: dict[tuple[str, int, int], str], count: int) -> list[tuple[int, int, str]]:
    """첫 공시가 충분히 쌓인 최근 분기 `count`개 → [(연도, 분기, 시즌 시작일)]. 순수."""
    by_quarter: dict[tuple[int, int], list[str]] = collections.defaultdict(list)
    for (_, year, quarter), day in announcements.items():
        if 1 <= quarter <= 4:
            by_quarter[(year, quarter)].append(day)
    seasons = [
        (year, quarter, sorted(days)[len(days) // 20])  # 상위 5% 조기 공시는 시즌 앞당김으로 보지 않는다
        for (year, quarter), days in by_quarter.items()
        if len(days) >= SEASON_MIN_ANNOUNCEMENTS
    ]
    return sorted(seasons, key=lambda item: _qi(item[0], item[1]))[-count:]


def quarter_on(code_quarters: list[tuple[str, int]], day: str) -> int | None:
    """그 날짜까지 첫 공시가 난 가장 최근 분기 인덱스. `code_quarters`=[(공시일, qi)] 정렬."""
    position = bisect.bisect_right(code_quarters, (day, math.inf))
    return code_quarters[position - 1][1] if position else None


def consensus_on(rows: list[dict], day_iso: str) -> dict | None:
    """날짜 d 이전 스냅샷 중 d의 연도 연간 전망 최신 1행."""
    year = int(day_iso[:4])
    eligible = [
        row for row in rows
        if int(row.get("fiscal_year") or 0) == year and str(row.get("snapshot_at") or "")[:10] <= day_iso
    ]
    return max(eligible, key=lambda row: str(row.get("snapshot_at") or ""), default=None)


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="entry_checks 과거 시즌 replay (M1·M2·M5)")
    parser.add_argument("--seasons", type=int, default=2)
    parser.add_argument("--max-codes", type=int, default=0, help="점검용 후보 상한(0=전부)")
    parser.add_argument("--write", help="결과 표를 이 마크다운 파일 끝에 덧붙인다")
    args = parser.parse_args()

    from src.collectors.kis_prices import fetch_index_closes, fetch_investor_daily_naver
    from src.collectors.quarter_prices import fetch_daily_ohlcv_naver
    from src.db.supabase_client import select_all

    now = datetime.now(KST)
    universe = {
        str(row["code"]) for row in select_all("krx_universe", "code,is_excluded")
        if row.get("is_excluded") is not True
    }
    screens = {
        (str(row["code"]), _qi(int(row["fiscal_year"]), int(row["fiscal_quarter"]))): row
        for row in select_all("screen_results", SCREEN_COLUMNS)
        if row.get("fiscal_year") is not None and row.get("fiscal_quarter") is not None
    }
    series = fundamental_series(select_all("quarterly_fundamentals", FUNDAMENTAL_COLUMNS))
    announcements = first_announcements(select_all(
        "earnings_disclosures", "code,fiscal_year,fiscal_quarter,disclosed_at",
    ))
    consensus: dict[str, list[dict]] = collections.defaultdict(list)
    for row in select_all(
        "consensus_snapshots", "code,fiscal_year,fiscal_quarter,revenue_est,op_est,source,snapshot_at",
        filters={"fiscal_quarter": 0},
    ):
        if row.get("source") == "naver":
            consensus[str(row["code"])].append(row)

    seasons = pick_seasons(announcements, args.seasons)
    if not seasons:
        print("시즌을 찾지 못했다 — earnings_disclosures 확인")
        return 1
    begin = (datetime.strptime(seasons[0][2], "%Y-%m-%d") - timedelta(days=ENTRY_DAILY_LOOKBACK_CALENDAR_DAYS)).strftime("%Y%m%d")
    calendar = sorted(fetch_index_closes("KOSPI", begin, now.strftime("%Y%m%d")))
    calendar = [day for day in calendar if day < now.strftime("%Y%m%d")]  # 오늘(미확정)은 빼고 본다

    code_quarters: dict[str, list[tuple[str, int]]] = collections.defaultdict(list)
    for (code, year, quarter), day in announcements.items():
        if code in universe and 1 <= quarter <= 4:
            code_quarters[code].append((day.replace("-", ""), _qi(year, quarter)))
    for rows in code_quarters.values():
        rows.sort()

    windows: list[tuple[str, list[str]]] = []
    for index, (year, quarter, start) in enumerate(seasons):
        start_key = start.replace("-", "")
        stop = seasons[index + 1][2].replace("-", "") if index + 1 < len(seasons) else "99999999"
        days = [day for day in calendar if start_key <= day < stop][:SEASON_TRADING_DAYS]
        windows.append((f"{year}.{quarter}Q", days))
        print(f"시즌 {year}.{quarter}Q · {days[0] if days else '-'}~{days[-1] if days else '-'} · {len(days)}거래일")

    # 1단계 — DB만으로 M1 재무(+PRI)를 날짜별로 판정하고 후보를 모은다.
    fin_cache: dict[tuple[str, int, int], dict] = {}
    stage: dict[tuple[str, str, str], dict] = {}
    candidates: set[str] = set()
    for label, days in windows:
        for day in days:
            day_iso = f"{day[:4]}-{day[4:6]}-{day[6:]}"
            for code, quarters in code_quarters.items():
                index = quarter_on(quarters, day)
                screen = screens.get((code, index)) if index is not None else None
                if screen is None:
                    continue
                annual = consensus_on(consensus.get(code, []), day_iso)
                key = (code, index, int(day[:4]))
                if key not in fin_cache or annual is not None:
                    fin_cache[key] = m1_fundamental(
                        series.get(code, {}), index,
                        base_effect_warning=screen.get("base_effect_warning"),
                        annual_consensus=annual,
                        prior_year_actual=prior_year_actual(series.get(code, {}), int(day[:4]) - 1),
                    )
                fin = fin_cache[key]
                stage[(label, day, code)] = {"fin": fin, "screen": screen, "index": index}
                if fin["pass"] is True:
                    candidates.add(code)
    ordered = sorted(candidates)
    if args.max_codes:
        ordered = ordered[: args.max_codes]
    print(f"M1 재무 통과 종목(시즌 합집합) {len(candidates)} · 일봉·수급 조회 {len(ordered)}")

    bars_by_code: dict[str, list] = {}
    flows_by_code: dict[str, list[tuple[str, int, int]]] = {}
    pages = max(1, math.ceil(sum(1 for day in calendar if day >= windows[0][1][0]) / NAVER_FLOW_ROWS_PER_PAGE) + 1) if windows[0][1] else 1
    for number, code in enumerate(ordered, 1):
        try:
            bars_by_code[code] = to_bars(fetch_daily_ohlcv_naver(code, begin, now.strftime("%Y%m%d")))
            flows_by_code[code] = fetch_investor_daily_naver(code, max_pages=pages)
        except Exception as exc:
            print(f"  ⚠ {code}: {type(exc).__name__}")
        time.sleep(0.12)
        if number % 25 == 0:
            print(f"  … {number}/{len(ordered)}")

    lines = [
        "",
        f"### replay 실측 ({now:%Y-%m-%d %H:%M} KST · `python -m src.screener.entry_replay_run`)",
        "",
        "| 시즌 | 거래일 | 평가 종목·일 | M1 재무 | M1(PRI 포함) | M1(PRI 제외) | M1∧M2 | M1∧M5 | M1∧M2∧M5 | M1∧M2∧M5(PRI 제외) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, days in windows:
        counts: collections.Counter = collections.Counter()
        codes_by: dict[str, set[str]] = collections.defaultdict(set)
        for day in days:
            day_iso = f"{day[:4]}-{day[4:6]}-{day[6:]}"
            for code in universe:
                item = stage.get((label, day, code))
                if item is None:
                    continue
                counts["evaluated"] += 1
                fin = item["fin"]
                if fin["pass"] is not True:
                    continue
                counts["fin"] += 1
                codes_by["fin"].add(code)
                if code not in bars_by_code:
                    continue
                bars = [bar for bar in bars_by_code[code] if bar.date <= day]
                if not bars or bars[-1].date != day:
                    continue
                screen = item["screen"]
                year, quarter = divmod(item["index"], 4)
                announced = announcements.get((code, year, quarter + 1))
                with_pri = m1_price(bars, announcement_date=announced, pri=screen.get("pri"))
                without_pri = m1_price(bars, announcement_date=announced, pri=0.0)
                m2 = m2_check(bars)
                flow_rows = [row for row in flows_by_code.get(code, []) if row[0] <= day]
                m5 = m5_check(flow_rows, source="naver")
                m5_ok = bool(m5 and m5["as_of"] == day and m5["pass"])
                m2_ok = bool(m2 and m2["pass"])
                for suffix, price in (("", with_pri), ("_nopri", without_pri)):
                    if all_of([fin["pass"], price["pass"]]) is not True:
                        continue
                    for name, ok in (
                        (f"m1{suffix}", True), (f"m1m2{suffix}", m2_ok),
                        (f"m1m5{suffix}", m5_ok), (f"m1m2m5{suffix}", m2_ok and m5_ok),
                    ):
                        if ok:
                            counts[name] += 1
                            codes_by[name].add(code)

        def cell(name: str) -> str:
            return f"{counts[name]}일·{len(codes_by[name])}종목"

        lines.append(
            f"| {label} | {len(days)} | {counts['evaluated']} | {cell('fin')} | {cell('m1')} | "
            f"{cell('m1_nopri')} | {cell('m1m2')} | {cell('m1m5')} | {cell('m1m2m5')} | {cell('m1m2m5_nopri')} |"
        )
    lines += [
        "",
        "- 셀 = 통과 **종목·일 수**·**고유 종목 수**. M3·M4는 JARVIS 몫이라 제외했다.",
        "- PRI는 일별 이력이 없어 분기 최신 재계산값이다 → PRI 제외 열을 함께 둔다.",
        "- M5는 replay 한정 네이버 투자자별 매매(운영은 KIS 1차·네이버 폴백).",
    ]
    report = "\n".join(lines)
    print(report)
    if args.write:
        with open(args.write, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(report + "\n")
        print(f"\n✓ {args.write}에 덧붙였다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
