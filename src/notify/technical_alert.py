# PRD Ref: §8.6, §10 — 장 마감 후 기술적 매수 관찰 자동 알림
"""펀더멘털 후보의 5·20일선/MACD 상향 교차 접근을 일봉으로 판정한다.

    python -m src.notify.technical_alert          # 읽기 전용 dry-run
    python -m src.notify.technical_alert --send   # 실제 발송 + 중복 기록

선별에는 LLM을 쓰지 않는다(ADR 3). 같은 종목·평가 분기에는 한 번만 발송한다.
"""

from __future__ import annotations

import argparse
import collections
import json
import time
from dataclasses import asdict
from datetime import datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.collectors.kis_prices import fetch_recent_investor_streak
from src.collectors.quarter_prices import fetch_daily_closes_naver
from src.config.constants import (
    DASHBOARD_URL_DEFAULT,
    PRI_LOW,
    TECHNICAL_ALERT_DAILY_MAX,
    TECHNICAL_INVESTOR_BUY_STREAK_DAYS,
    TECHNICAL_MIN_DAILY_FETCH_RATE,
    TECHNICAL_PRICE_MAX_AGE_CALENDAR_DAYS,
)
from src.db.supabase_client import get_client, select_all
from src.notify.links import naver_stock_url
from src.notify.telegram import TelegramClient, already_sent, send_once
from src.notify.templates import technical_setup_message
from src.screener.score import active_score
from src.screener.sector_growth import sector_growth_profile
from src.screener.technical_setup import (
    CompanyGrowth,
    SectorGrowth,
    company_growth_streak,
    company_initial_inflection,
    sector_growth_continuity,
    technical_setup,
)
from src.universe.sector_map import UNKNOWN_SECTOR, classify_sector
from src.utils.console import enable_utf8_stdout
from src.utils.env import optional_env

KIND_TECHNICAL = "technical_setup"
KST = ZoneInfo("Asia/Seoul")
SCREEN_COLUMNS = (
    "code,fiscal_year,fiscal_quarter,gate_passed,turnaround,grade,pri,score_flash,score_final"
)
CONSENSUS_COLUMNS = (
    "code,fiscal_year,fiscal_quarter,revenue_est,op_est,fwd_per,roe_next_est,roe_next_year,source,snapshot_at"
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
    screens: list[dict], universe_rows: list[dict], fundamental_rows: list[dict],
    stats: collections.Counter | None = None,
) -> list[dict]:
    """외부 호출 전에 초기 흑전·지속 가속 후보로 일봉 조회 대상을 줄인다."""
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
    stats = stats if stats is not None else collections.Counter()
    latest_screens = _latest_screens(screens)
    stats["latest"] = len(latest_screens)
    for screen in latest_screens:
        code = str(screen.get("code") or "")
        if screen.get("gate_passed") is not True or code not in universe or code not in series:
            continue
        stats["gate"] += 1
        index = _qi(int(screen["fiscal_year"]), int(screen["fiscal_quarter"]))
        # 최신 사용자 기준은 영업이익 YoY가 측정되는 2개 분기 가속을 필수로 한다.
        # 흑전 첫 분기는 성장률을 만들 수 없으므로 별도 후보로 우회시키지 않는다.
        company = company_growth_streak(series[code], index)
        if company is None:
            continue
        stats["company"] += 1
        sector = sector_of.get(code, UNKNOWN_SECTOR)
        cache_key = (sector, index)
        if cache_key not in sector_cache:
            sector_cache[cache_key] = sector_growth_continuity(
                sectors.get(sector, []), index
            ) if sector != UNKNOWN_SECTOR else None
        sector_growth = sector_cache[cache_key]
        growth_profile = sector_growth_profile(
            sector, universe[code].get("products"), universe[code].get("industry")
        )
        if sector_growth is None:
            continue
        stats["sector_quarterly"] += 1
        if growth_profile is None:
            stats[f"cagr_missing:{sector}"] += 1
            continue
        stats["sector_cagr"] += 1
        candidates.append({
            **screen,
            "name": universe[code].get("name") or code,
            "industry": universe[code].get("industry"),
            "products": universe[code].get("products"),
            "sector": sector,
            "company_growth": company,
            "sector_growth": sector_growth,
            "sector_growth_profile": growth_profile,
            "current_fundamental": series[code][index],
            "early_priority": bool(
                screen.get("pri") is not None
                and float(screen["pri"]) < PRI_LOW
                and screen.get("grade") in {"★", "○"}
            ),
        })
    candidates.sort(key=lambda row: (
        not row["early_priority"], -(active_score(row) or 0), row["code"],
    ))
    return candidates


def latest_annual_consensus(rows: list[dict]) -> dict[str, dict]:
    """종목별 최신 네이버 연간 전망 1행.

    분기 컨센서스와 연간 F.PER/ROE를 섞으면 기준 기간이 달라진다. 연간 행만
    고르고, 같은 종목에서는 추정연도와 스냅샷 시각이 가장 최신인 행을 쓴다.
    """
    latest: dict[str, dict] = {}
    for row in rows:
        quarter = row.get("fiscal_quarter")
        if quarter is None or int(quarter) != 0 or row.get("source") != "naver":
            continue
        code = str(row.get("code") or "")
        key = (int(row.get("fiscal_year") or 0), str(row.get("snapshot_at") or ""))
        previous = latest.get(code)
        previous_key = (
            int(previous.get("fiscal_year") or 0), str(previous.get("snapshot_at") or "")
        ) if previous else (-1, "")
        if key > previous_key:
            latest[code] = row
    return latest


def latest_next_quarter_consensus(rows: list[dict], candidates: list[dict]) -> dict[str, dict]:
    """후보 평가분기의 바로 다음 분기 네이버 컨센서스 최신 행."""
    target = {}
    for row in candidates:
        year, quarter = int(row["fiscal_year"]), int(row["fiscal_quarter"])
        target[row["code"]] = (year + (quarter == 4), 1 if quarter == 4 else quarter + 1)
    latest: dict[str, dict] = {}
    for row in rows:
        code = str(row.get("code") or "")
        if row.get("source") != "naver" or target.get(code) != (
            int(row.get("fiscal_year") or 0), int(row.get("fiscal_quarter") or 0)
        ):
            continue
        if code not in latest or str(row.get("snapshot_at") or "") > str(latest[code].get("snapshot_at") or ""):
            latest[code] = row
    return latest


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


def first_announcement_dates(rows: list[dict]) -> dict[tuple[str, int, int], str]:
    """회계분기별 첫 실적 공시일만 앵커로 쓴다. 날짜가 없으면 추측하지 않는다."""
    out: dict[tuple[str, int, int], str] = {}
    for row in rows:
        if row.get("fiscal_year") is None or row.get("fiscal_quarter") is None:
            continue
        day = str(row.get("disclosed_at") or "")[:10]
        if len(day) != 10:
            continue
        key = (str(row["code"]), int(row["fiscal_year"]), int(row["fiscal_quarter"]))
        if key not in out or day < out[key]:
            out[key] = day
    return out


def sent_count_today(now: datetime) -> int:
    """재실행·수동 실행을 합쳐 KST 하루 최대 2건을 강제한다."""
    start = datetime.combine(now.astimezone(KST).date(), clock_time(), KST)
    end = start + timedelta(days=1)
    response = (
        get_client().table("notifications").select("id", count="exact")
        .eq("kind", KIND_TECHNICAL)
        .gte("sent_at", start.astimezone(timezone.utc).isoformat())
        .lt("sent_at", end.astimezone(timezone.utc).isoformat())
        .limit(1).execute()
    )
    if response.count is None:
        raise RuntimeError("일일 텔레그램 발송 건수를 확인하지 못했습니다")
    return int(response.count)


def _write_summary(path: str | None, summary: dict) -> None:
    if path:
        Path(path).write_text(json.dumps(summary, ensure_ascii=False) + "\n", encoding="utf-8")


def run(*, send: bool, limit: int, summary_path: str | None = None) -> int:
    limit = _daily_limit(limit)
    screens = select_all("screen_results", SCREEN_COLUMNS)
    universe = select_all(
        "krx_universe", "code,name,industry,products,is_excluded"
    )
    fundamentals = select_all(
        "quarterly_fundamentals",
        "code,fiscal_year,fiscal_quarter,revenue,op,revenue_yoy,op_yoy,op_status_label,"
        "opm,opm_yoy_delta,ttm_opm_delta,fcf,cfo",
    )
    consensus_rows = select_all("consensus_snapshots", CONSENSUS_COLUMNS)
    announcements = first_announcement_dates(select_all(
        "earnings_disclosures", "code,fiscal_year,fiscal_quarter,disclosed_at",
    ))
    funnel: collections.Counter = collections.Counter()
    candidates = growth_candidates(screens, universe, fundamentals, funnel)
    print("추천 펀더멘털 퍼널 · " + " → ".join(
        f"{label} {funnel[key]}" for key, label in (
            ("latest", "최신평가"), ("gate", "게이트"), ("company", "2Q 가속+OPM"),
            ("sector_quarterly", "동종산업 가속"), ("sector_cagr", "3Y CAGR≥15%"),
        )
    ))
    missing_profiles = sorted(
        ((key.split(":", 1)[1], value) for key, value in funnel.items() if key.startswith("cagr_missing:")),
        key=lambda item: (-item[1], item[0]),
    )
    if missing_profiles:
        print("CAGR 미측정 상위 · " + " · ".join(f"{sector} {count}" for sector, count in missing_profiles[:8]))
    if not candidates:
        print("조건 충족 후보 0건 — 엄격한 AND 게이트의 정상 결과 · 발송 0건")
        _write_summary(summary_path, {
            "date": datetime.now(KST).date().isoformat(), "status": "complete",
            "funnel": dict(funnel), "matches": 0, "sent": 0,
        })
        return 0
    consensus_by_code = latest_annual_consensus(consensus_rows)
    next_consensus_by_code = latest_next_quarter_consensus(consensus_rows, candidates)
    now = datetime.now(KST)
    today = now.date()
    begin, end = f"{today.year - 1}{today:%m%d}", f"{today:%Y%m%d}"
    print(f"펀더멘털 후보 {len(candidates)}종목 · 네이버 일봉 {begin}~{end}")

    matches: list[dict] = []
    fetched = failed = empty = missing_anchor = stale = price_pass = sma_pass = macd_pass = rsi_pass = flow_pass = 0
    for candidate in candidates:
        key = (candidate["code"], int(candidate["fiscal_year"]), int(candidate["fiscal_quarter"]))
        announcement_date = announcements.get(key)
        if announcement_date is None:
            missing_anchor += 1
            continue
        try:
            closes = fetch_daily_closes_naver(candidate["code"], begin, end)
            fetched += bool(closes)
            empty += not bool(closes)
            setup = technical_setup(closes, announcement_date=announcement_date)
        except Exception as exc:
            failed += 1
            print(f"  ⚠ {candidate['name']}({candidate['code']}): {type(exc).__name__}")
            continue
        finally:
            time.sleep(0.12)
        if setup is None:
            continue
        as_of = datetime.strptime(setup.as_of, "%Y%m%d").date()
        if (today - as_of).days > TECHNICAL_PRICE_MAX_AGE_CALENDAR_DAYS:
            stale += 1
            continue
        price_pass += bool(setup.price_regime)
        sma_pass += bool(setup.price_regime and setup.sma_approaching)
        macd_pass += bool(setup.price_regime and setup.sma_approaching and setup.macd_approaching)
        rsi_pass += bool(setup.strong_recommendation)
        if setup.qualifies:
            try:
                investor_flow = fetch_recent_investor_streak(
                    candidate["code"], sessions=TECHNICAL_INVESTOR_BUY_STREAK_DAYS
                )
            except Exception as exc:
                failed += 1
                print(f"  ⚠ {candidate['name']}({candidate['code']}) 수급: {type(exc).__name__}")
                continue
            if investor_flow is None:
                continue
            flow_pass += 1
            matches.append({**candidate, "technical": setup, "investor_flow": investor_flow})

    matches.sort(key=lambda row: (
        not row["early_priority"],
        not row["technical"].strong_recommendation,
        abs(row["technical"].histogram_pct),
        abs(row["technical"].sma_gap_pct),
        -(active_score(row) or 0),
        row["code"],
    ))
    attempted = len(candidates) - missing_anchor
    print(f"일봉 성공 {fetched}/{attempted} · 빈 일봉 {empty} · 기술 신호 {len(matches)} · 실패 {failed}")
    print(f"발표일 누락 {missing_anchor} · 일봉 지연 {stale} · 가격 {price_pass} · 가격+5/20일선 {sma_pass} · 가격+5/20일선+MACD {macd_pass} · 3일 연속 수급 {flow_pass} · RSI 보강 {rsi_pass}")
    summary = {
        "date": today.isoformat(), "status": "complete", "candidates": len(candidates),
        "evaluated": fetched, "price": price_pass, "sma": sma_pass, "macd": macd_pass,
        "flow": flow_pass, "rsi": rsi_pass, "matches": len(matches), "sent": 0,
    }
    if attempted and fetched / attempted < TECHNICAL_MIN_DAILY_FETCH_RATE:
        print(f"⚠ 일봉 조회 성공률 {fetched / attempted:.1%} — 발송 중단")
        _write_summary(summary_path, {**summary, "status": "scan_failed"})
        return 1

    base_url = optional_env("DASHBOARD_BASE_URL", DASHBOARD_URL_DEFAULT).rstrip("/")
    already_today = sent_count_today(now) if send else 0
    remaining = min(limit, max(0, TECHNICAL_ALERT_DAILY_MAX - already_today))
    send_rows, duplicates = (
        unsent_matches(matches, remaining) if send and remaining else (matches[:remaining], 0) if not send else ([], 0)
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
            "sector_growth_profile": asdict(row["sector_growth_profile"]),
            "products": row.get("products"),
            "industry": row.get("industry"),
            "fundamental": row.get("current_fundamental") or {},
            "investment_score": active_score(row),
            "pri": row.get("pri"),
            "consensus": consensus_by_code.get(row["code"]) or {},
            "next_consensus": next_consensus_by_code.get(row["code"]) or {},
            "early_priority": row["early_priority"],
            "technical": asdict(setup),
            "investor_flow": asdict(row["investor_flow"]),
            "url": f"{base_url}/?gate=all",
            "heimdallr_url": f"{base_url}/stock/{row['code']}",
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
                    "early_priority": row["early_priority"],
                    "technical": asdict(setup),
                },
            )
    if not send:
        print("\n(--send 미지정 — 발송·DB 쓰기 0건)")
    else:
        print(f"\n기술 신호 발송 {sent}/{len(send_rows)}건 · 오늘 기존 {already_today}건 · 분기 중복 {duplicates}건")
    summary["sent"] = sent
    if send and (sent != len(send_rows) or failed):
        summary["status"] = "delivery_failed"
    _write_summary(summary_path, summary)
    return 1 if summary["status"] != "complete" else 0


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="초기 전환 우선 + 5·20일선/MACD 상향 접근 알림")
    parser.add_argument("--send", action="store_true", help="실제 텔레그램 발송")
    parser.add_argument("--limit", type=int, default=TECHNICAL_ALERT_DAILY_MAX)
    parser.add_argument("--summary-path", help="일일 요약에 붙일 기술 신호 점검 결과 JSON")
    args = parser.parse_args()
    return run(send=args.send, limit=args.limit, summary_path=args.summary_path)


if __name__ == "__main__":
    raise SystemExit(main())
