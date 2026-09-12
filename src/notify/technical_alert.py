# PRD Ref: §8.6, §10 — 장 마감 후 기술적 매수 관찰 자동 알림
"""성장 지속 기업의 MACD 상향 접근을 네이버 일봉으로 판정해 텔레그램에 알린다.

    python -m src.notify.technical_alert          # 읽기 전용 dry-run
    python -m src.notify.technical_alert --send   # 실제 발송 + 중복 기록

선별에는 LLM을 쓰지 않는다(ADR 3). 같은 종목·평가 분기에는 한 번만 발송한다.
"""

from __future__ import annotations

import argparse
import collections
import time
from dataclasses import asdict
from datetime import date, timedelta

from src.collectors.quarter_prices import fetch_daily_closes_naver
from src.config.constants import (
    DASHBOARD_URL_DEFAULT,
    TECHNICAL_ALERT_DAILY_MAX,
)
from src.db.supabase_client import select_all
from src.notify.links import naver_stock_url
from src.notify.telegram import TelegramClient, already_sent, send_once
from src.notify.templates import technical_setup_message
from src.screener.score import active_score
from src.screener.technical_setup import (
    CompanyGrowth,
    SectorGrowth,
    company_growth_streak,
    sector_growth_continuity,
    technical_setup,
)
from src.universe.sector_map import UNKNOWN_SECTOR, classify_sector
from src.utils.console import enable_utf8_stdout
from src.utils.env import optional_env

KIND_TECHNICAL = "technical_setup"
SCREEN_COLUMNS = (
    "code,fiscal_year,fiscal_quarter,gate_passed,grade,score_flash,score_final"
)


def _qi(year: int, quarter: int) -> int:
    return year * 4 + quarter - 1


def _latest_screens(rows: list[dict]) -> list[dict]:
    latest: dict[str, dict] = {}
    for row in rows:
        if row.get("fiscal_year") is None or row.get("fiscal_quarter") is None:
            continue
        previous = latest.get(str(row.get("code") or ""))
        if previous is None or _qi(int(row["fiscal_year"]), int(row["fiscal_quarter"])) > _qi(
            int(previous["fiscal_year"]), int(previous["fiscal_quarter"])
        ):
            latest[str(row["code"])] = row
    return list(latest.values())


def _fundamental_series(rows: list[dict]) -> dict[str, dict[int, dict]]:
    out: dict[str, dict[int, dict]] = collections.defaultdict(dict)
    for row in rows:
        if row.get("fiscal_year") is None or row.get("fiscal_quarter") is None:
            continue
        out[str(row["code"])][_qi(int(row["fiscal_year"]), int(row["fiscal_quarter"]))] = row
    return out


def growth_candidates(
    screens: list[dict], universe_rows: list[dict], fundamental_rows: list[dict]
) -> list[dict]:
    """외부 호출 전에 산업·기업 성장 지속 조건으로 일봉 조회 대상을 줄인다."""
    universe = {str(row["code"]): row for row in universe_rows}
    series = _fundamental_series(fundamental_rows)
    sectors: dict[str, list[dict[int, dict]]] = collections.defaultdict(list)
    sector_of: dict[str, str] = {}
    for code, row in universe.items():
        if row.get("is_excluded") is True:
            continue
        sector = classify_sector(row.get("name"), row.get("industry"), row.get("products"))
        sector_of[code] = sector
        if sector != UNKNOWN_SECTOR and code in series:
            sectors[sector].append(series[code])

    sector_cache: dict[tuple[str, int], SectorGrowth | None] = {}
    candidates: list[dict] = []
    for screen in _latest_screens(screens):
        code = str(screen.get("code") or "")
        if screen.get("gate_passed") is not True or code not in universe or code not in series:
            continue
        index = _qi(int(screen["fiscal_year"]), int(screen["fiscal_quarter"]))
        company = company_growth_streak(series[code], index)
        sector = sector_of.get(code, UNKNOWN_SECTOR)
        cache_key = (sector, index)
        if cache_key not in sector_cache:
            sector_cache[cache_key] = sector_growth_continuity(
                sectors.get(sector, []), index
            ) if sector != UNKNOWN_SECTOR else None
        sector_growth = sector_cache[cache_key]
        if company is None or sector_growth is None:
            continue
        candidates.append({
            **screen,
            "name": universe[code].get("name") or code,
            "sector": sector,
            "company_growth": company,
            "sector_growth": sector_growth,
        })
    candidates.sort(key=lambda row: (-(active_score(row) or 0), row["code"]))
    return candidates


def _growth_dict(value: CompanyGrowth | SectorGrowth) -> dict:
    return asdict(value)


def unsent_matches(matches: list[dict], limit: int) -> tuple[list[dict], int]:
    """이미 보낸 상위 종목이 일일 상한을 차지하지 않게 먼저 걷어낸다."""
    out: list[dict] = []
    duplicates = 0
    for row in matches:
        if already_sent(
            row["code"], int(row["fiscal_year"]), int(row["fiscal_quarter"]),
            KIND_TECHNICAL,
        ):
            duplicates += 1
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out, duplicates


def _daily_limit(requested: int) -> int:
    """수동 실행에서도 사용자 지정 일일 상한을 넘기지 않는다."""
    return min(max(requested, 0), TECHNICAL_ALERT_DAILY_MAX)


def run(*, send: bool, limit: int) -> int:
    limit = _daily_limit(limit)
    screens = select_all("screen_results", SCREEN_COLUMNS)
    universe = select_all(
        "krx_universe", "code,name,industry,products,is_excluded"
    )
    fundamentals = select_all(
        "quarterly_fundamentals",
        "code,fiscal_year,fiscal_quarter,revenue,op,revenue_yoy,op_yoy",
    )
    candidates = growth_candidates(screens, universe, fundamentals)
    today = date.today()
    begin, end = f"{today.year - 1}{today:%m%d}", f"{today:%Y%m%d}"
    print(f"펀더멘털 후보 {len(candidates)}종목 · 네이버 일봉 {begin}~{end}")

    matches: list[dict] = []
    fetched = failed = 0
    for candidate in candidates:
        try:
            closes = fetch_daily_closes_naver(candidate["code"], begin, end)
            fetched += bool(closes)
            setup = technical_setup(closes)
        except Exception as exc:
            failed += 1
            print(f"  ⚠ {candidate['name']}({candidate['code']}): {type(exc).__name__}")
            continue
        finally:
            time.sleep(0.12)
        if setup is not None and setup.qualifies:
            matches.append({**candidate, "technical": setup})

    matches.sort(key=lambda row: (
        abs(row["technical"].histogram_pct),
        -(active_score(row) or 0),
        row["code"],
    ))
    print(f"일봉 성공 {fetched}/{len(candidates)} · 기술 신호 {len(matches)} · 실패 {failed}")

    base_url = optional_env("DASHBOARD_BASE_URL", DASHBOARD_URL_DEFAULT).rstrip("/")
    send_rows, duplicates = (
        unsent_matches(matches, limit) if send else (matches[:limit], 0)
    )
    client = TelegramClient() if send else None
    sent = 0
    for row in send_rows:
        setup = row["technical"]
        context = {
            "code": row["code"], "name": row["name"], "sector": row["sector"],
            "grade": row.get("grade") or "—",
            "company_growth": _growth_dict(row["company_growth"]),
            "sector_growth": _growth_dict(row["sector_growth"]),
            "technical": asdict(setup),
            "url": f"{base_url}/stock/{row['code']}",
            "naver_url": naver_stock_url(row["code"], mobile=True),
        }
        text = technical_setup_message(context)
        print(f"\n{'[발송 후보]' if not send else '[발송]'} {row['name']}({row['code']})")
        print(text)
        if client is not None:
            sent += send_once(
                client,
                code=row["code"],
                fiscal_year=int(row["fiscal_year"]),
                fiscal_quarter=int(row["fiscal_quarter"]),
                kind=KIND_TECHNICAL,
                text=text,
                payload={
                    "as_of": setup.as_of,
                    "grade": row.get("grade"),
                    "sector": row["sector"],
                    "technical": asdict(setup),
                },
            )
    if not send:
        print("\n(--send 미지정 — 발송·DB 쓰기 0건)")
    else:
        print(f"\n기술 신호 발송 {sent}/{len(send_rows)}건 · 분기 중복 {duplicates}건")
    return 0


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="성장 지속 + MACD 상향 접근 알림")
    parser.add_argument("--send", action="store_true", help="실제 텔레그램 발송")
    parser.add_argument("--limit", type=int, default=TECHNICAL_ALERT_DAILY_MAX)
    args = parser.parse_args()
    return run(send=args.send, limit=args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
