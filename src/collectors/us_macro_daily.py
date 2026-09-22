# PRD Ref: §9, §10 — 미국 장 마감 후 07:00 KST 매크로 스냅샷
"""대시보드 렌더와 분리된 매크로 수집기. 네트워크 실패 시 이전 스냅샷을 보존한다."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from src.config.constants import (
    US_MACRO_EQUITY_DAILY_DROP_PCT,
    US_MACRO_MARKET_CLOSE_GRACE_MINUTES,
    US_MACRO_MAX_STALE_CALENDAR_DAYS,
    US_MACRO_VIX_RISK_OFF,
)

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "dashboard" / "lib" / "macro-daily.json"
BRIEFINGS = ROOT / "dashboard" / "lib" / "macro-briefings.json"
FED_RSS = "https://www.federalreserve.gov/feeds/press_monetary.xml"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
SYMBOLS = {"sp500": "%5EGSPC", "nasdaq": "%5EIXIC", "semiconductor": "%5ESOX", "vix": "%5EVIX"}
NEW_YORK = ZoneInfo("America/New_York")
SEOUL = ZoneInfo("Asia/Seoul")


def parse_yahoo_chart(payload: dict, *, now: datetime) -> dict:
    """완료된 최근 두 거래일 종가로 전일 수익률을 계산한다."""
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise ValueError("Yahoo chart 결과 없음")
    chart = result[0]
    timestamps = chart.get("timestamp") or []
    quotes = ((chart.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    ny_now = now.astimezone(NEW_YORK)
    completed_through = ny_now.date() if ny_now.time() >= time(16, US_MACRO_MARKET_CLOSE_GRACE_MINUTES) else ny_now.date() - timedelta(days=1)
    measured = [
        (datetime.fromtimestamp(int(timestamp), NEW_YORK).date().isoformat(), float(close))
        for timestamp, close in zip(timestamps, quotes)
        if close is not None and float(close) > 0
        and datetime.fromtimestamp(int(timestamp), NEW_YORK).date() <= completed_through
    ]
    if len(measured) < 2:
        raise ValueError("Yahoo chart 완료 거래일 2일 미만")
    (previous_day, previous), (day, close) = measured[-2:]
    if day == previous_day:
        raise ValueError("Yahoo chart 거래일 중복")
    return {"date": day, "close": round(close, 2), "changePct": round((close / previous - 1) * 100, 2)}


def parse_fed_rss(xml_text: str) -> dict:
    root = ElementTree.fromstring(xml_text)
    fallback: dict | None = None
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        published = (item.findtext("pubDate") or "").strip()
        if title and link.startswith("https://www.federalreserve.gov/"):
            date = parsedate_to_datetime(published).date().isoformat() if published else None
            candidate = {"title": title, "url": link, "publishedAt": date}
            fallback = fallback or candidate
            if "issues FOMC statement" in title:
                return {**candidate, "title": f"미 연준 FOMC 성명 ({date})"}
    if fallback:
        return fallback
    raise ValueError("연준 공식 RSS에서 유효한 항목을 찾지 못했습니다")


def parse_fed_statement(html: str) -> dict:
    """원문에서 확인된 정책금리·결정 방향·물가 평가만 반환한다."""
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    match = re.search(
        r"target range for the federal funds rate (?:at|by .{1,50}? to)\s+([0-9./-]+) to ([0-9./-]+) percent",
        text, re.IGNORECASE,
    )

    def rate(raw: str) -> float:
        if "-" in raw and "/" in raw:
            whole, fraction = raw.split("-", 1)
            numerator, denominator = fraction.split("/", 1)
            return float(whole) + float(numerator) / float(denominator)
        return float(raw)

    result: dict = {}
    if match:
        result["policyRangePct"] = [rate(match.group(1)), rate(match.group(2))]
    if re.search(r"decided to raise the target range", text, re.IGNORECASE):
        result["policyAction"] = "인상"
    elif re.search(r"decided to lower the target range", text, re.IGNORECASE):
        result["policyAction"] = "인하"
    elif re.search(r"decided to maintain the target range", text, re.IGNORECASE):
        result["policyAction"] = "동결"
    result["inflationAboveTarget"] = bool(re.search(
        r"inflation (?:remains|is) elevated",
        text, re.IGNORECASE,
    ))
    if re.search(r"economic activity is expanding at a solid pace", text, re.IGNORECASE):
        result["activity"] = "경제활동이 견조한 속도로 확장"
    return result


def build_context(markets: dict[str, dict], fed: dict, checked_at: datetime) -> dict:
    dates = {row["date"] for row in markets.values()}
    if len(dates) != 1:
        raise ValueError(f"미국 시장 지표 거래일 불일치: {sorted(dates)}")
    market_date = dates.pop()
    if (checked_at.astimezone(NEW_YORK).date() - datetime.fromisoformat(market_date).date()).days > US_MACRO_MAX_STALE_CALENDAR_DAYS:
        raise ValueError(f"미국 시장 종가가 오래됐습니다: {market_date}")
    sp, nasdaq, sox, vix = (markets[key] for key in ("sp500", "nasdaq", "semiconductor", "vix"))
    risk_off = vix["close"] >= US_MACRO_VIX_RISK_OFF or (sp["changePct"] <= US_MACRO_EQUITY_DAILY_DROP_PCT and nasdaq["changePct"] <= US_MACRO_EQUITY_DAILY_DROP_PCT)
    ai_lead = sox["changePct"] > sp["changePct"] and sox["changePct"] > 0 and not risk_off
    if risk_off:
        mode = "quality_price"
        sectors = ["전력인프라", "방산·우주", "조선·해운", "반도체 장비", "반도체 소재", "반도체 부품", "반도체 IDM"]
        regime = "변동성 확대·위험 회피"
    elif ai_lead:
        mode = "earnings_growth"
        sectors = ["반도체 장비", "반도체 소재", "반도체 부품", "반도체 DSP", "반도체 OSAT", "반도체 IDM", "전력인프라", "통신·네트워크", "방산·우주"]
        regime = "미국 반도체 상대강세"
    else:
        mode = "balanced"
        sectors = ["전력인프라", "반도체 장비", "반도체 소재", "반도체 부품", "반도체 IDM", "방산·우주", "조선·해운"]
        regime = "혼조·실적 확인"
    date_label = datetime.fromisoformat(market_date).strftime("%Y-%m-%d")
    policy_range = fed.get("policyRangePct")
    policy_summary = (
        f"연준이 금리를 {fed.get('policyAction', '결정')}해 정책금리 목표범위를 {policy_range[0]:g}~{policy_range[1]:g}%로 설정했습니다."
        if policy_range else "연준 정책금리 범위는 원문 확인 필요"
    )
    inflation_summary = (
        "연준은 물가가 여전히 높다고 평가했습니다."
        if fed.get("inflationAboveTarget") else "연준의 물가 방향은 본문에서 확인되지 않았습니다."
    )
    activity_summary = f"{fed['activity']}한다고 평가했습니다. " if fed.get("activity") else ""
    briefings = json.loads(BRIEFINGS.read_text(encoding="utf-8"))
    market_url = "https://www.tradingview.com/markets/stocks-usa/market-movers-all-stocks/"
    return {
        "source": "미국 전 거래일 종가: Yahoo Finance·TradingView · 통화정책: Federal Reserve",
        "checkedAt": checked_at.astimezone(SEOUL).strftime("%Y-%m-%d %H:%M KST"),
        "marketDate": market_date,
        "items": [
            {"title": f"미국 {date_label} 전 거래일 종가 · TradingView", "url": market_url, "publishedAt": market_date},
            {key: fed[key] for key in ("title", "url", "publishedAt")},
            *[{key: briefing[key] for key in ("title", "url", "publishedAt")} for briefing in briefings],
        ],
        "briefings": briefings,
        "flags": {"rates": True, "industry": True, "geopolitics": risk_off},
        "sortMode": mode,
        "preferredSectors": sectors,
        "summary": {
            "current": f"미국 {date_label} 장 마감: S&P 500 {sp['changePct']:+.2f}%, 나스닥 {nasdaq['changePct']:+.2f}%, 필라델피아 반도체 {sox['changePct']:+.2f}%, VIX {vix['close']:.2f}. {regime} 국면으로 해석합니다.",
            "forward": f"연준 성명({fed['publishedAt']}): {policy_summary} {activity_summary}{inflation_summary} 아래 미국 물가·고용·GDP와 IMF 세계전망은 발표일이 확인된 원문 핵심 수치로 요약했습니다.",
            "recommendedSort": "추천 정렬: " + (
                f"{regime} 적합 섹터 → 초기 흑전·낮은 주가반영도 후보 → 높은 투자 매력도 → 높은 영업이익 YoY → 높은 내년 F.ROE → 낮은 주가반영도 → 등급 → 최신 분기"
                if mode == "earnings_growth" else
                f"{regime} 적합 섹터 → 초기 흑전·낮은 주가반영도 후보 → 높은 투자 매력도 → 낮은 주가반영도 → 낮은 내년 F.PER → 높은 내년 F.ROE → 영업이익 YoY → 등급 → 최신 분기"
                if mode == "quality_price" else
                f"{regime} 적합 섹터 → 초기 흑전·낮은 주가반영도 후보 → 높은 투자 매력도 → 낮은 주가반영도 → 높은 영업이익 YoY → 등급 → 최신 분기"
            ),
        },
    }


def collect(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    headers = {"User-Agent": "Mozilla/5.0 (Heimdallr macro snapshot)"}
    with httpx.Client(timeout=15, follow_redirects=True, headers=headers) as client:
        markets = {}
        for key, symbol in SYMBOLS.items():
            response = client.get(YAHOO_CHART.format(symbol=symbol), params={"range": "5d", "interval": "1d"})
            response.raise_for_status()
            markets[key] = parse_yahoo_chart(response.json(), now=now)
        response = client.get(FED_RSS)
        response.raise_for_status()
        fed = parse_fed_rss(response.text)
        try:
            statement = client.get(fed["url"])
            statement.raise_for_status()
            fed.update(parse_fed_statement(statement.text))
        except httpx.HTTPError:
            print("⚠ FOMC 성명 본문 확인 실패 — 금리·물가 수치 표시 생략")
    return build_context(markets, fed, now)


def should_write_snapshot(previous: dict, context: dict, *, force: bool = False) -> bool:
    """같은 거래일 사전 예열본도 07시 이후 첫 확인 시점에는 다시 기록한다."""
    previous_at = previous.get("checkedAt", "")
    current_at = context["checkedAt"]
    prewarm_needs_seven_oclock = (
        previous_at[:10] == current_at[:10]
        and previous_at[11:16] < "07:00" <= current_at[11:16]
    )
    return bool(
        force or prewarm_needs_seven_oclock
        or (previous_at[:10], previous.get("marketDate"))
        != (current_at[:10], context["marketDate"])
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="미국 장 마감/연준 매크로 스냅샷")
    parser.add_argument("--write", action="store_true", help="검증 성공 시 대시보드 JSON 갱신")
    parser.add_argument("--force", action="store_true", help="같은 날 출처 선택 수정 시 재생성")
    args = parser.parse_args()
    context = collect()
    print(context["checkedAt"], context["marketDate"], context["sortMode"])
    print(context["summary"]["current"])
    if args.write:
        previous = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
        if should_write_snapshot(previous, context, force=args.force):
            OUTPUT.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"갱신: {OUTPUT}")
        else:
            print("같은 KST 날짜·거래일 스냅샷 유지")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
