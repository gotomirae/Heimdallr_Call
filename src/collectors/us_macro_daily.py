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
SYMBOLS = {"sp500": "%5EGSPC", "nasdaq": "%5EIXIC", "dow": "%5EDJI", "semiconductor": "%5ESOX", "vix": "%5EVIX"}
FEAR_GREED_URL = "https://fearandgreedgraph.com/api/fear-greed"
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
    history = [{"date": measured_day, "value": round(value, 2)} for measured_day, value in measured[-60:]]
    return {"date": day, "close": round(close, 2), "changePct": round((close / previous - 1) * 100, 2), "history": history}


def parse_fear_greed(payload: dict) -> dict:
    """공개 JSON의 날짜·값 배열을 맞춰 최근 60개 고유 관측치만 보존한다."""
    dates = payload.get("dates") or []
    values = payload.get("values") or []
    if not isinstance(dates, list) or not isinstance(values, list) or len(dates) != len(values):
        raise ValueError("Fear & Greed 날짜·값 배열 불일치")
    measured: dict[str, float] = {}
    for day, value in zip(dates, values):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if isinstance(day, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) and 0 <= numeric <= 100:
            measured[day] = numeric
    history = [{"date": day, "value": round(value, 1)} for day, value in sorted(measured.items())[-60:]]
    if not history:
        raise ValueError("Fear & Greed 유효 관측치 없음")
    latest = history[-1]
    value = latest["value"]
    label = "극도의 공포" if value < 25 else "공포" if value < 45 else "중립" if value <= 55 else "탐욕" if value <= 75 else "극도의 탐욕"
    return {"date": latest["date"], "value": value, "label": label, "history": history,
            "sourceUrl": "https://fearandgreedgraph.com/", "sourceLabel": "CNN Fear & Greed 재배포 데이터"}


MACRO_EVENTS = (
    {"date": "2026-09-30", "event": "미국 2분기 GDP 3차 추정·8월 PCE", "source": "BEA", "url": "https://www.bea.gov/news/schedule", "watch": "성장률 수정폭과 근원 PCE", "response": "물가가 예상보다 높으면 장기금리 민감 성장주의 추격을 줄이고, 둔화가 확인되면 실적 가속·낮은 PRI 종목을 분할 확인한다."},
    {"date": "2026-10-02", "event": "미국 9월 고용", "source": "BLS", "url": "https://www.bls.gov/schedule/2026/", "watch": "신규고용·실업률·임금", "response": "강한 고용과 임금 재가속이 겹치면 금리 상승 위험을 우선하고, 완만한 둔화면 경기침체 신호와 구분한다."},
    {"date": "2026-10-14", "event": "미국 9월 CPI", "source": "BLS", "url": "https://www.bls.gov/schedule/2026/", "watch": "근원 CPI 월간 속도", "response": "발표 전 포지션을 키우지 않고, 예상 상회 시 고PER 비중을 점검하며 예상 하회 시 이익 전망이 유지되는 성장주부터 본다."},
    {"date": "2026-10-28", "event": "FOMC 금리 결정·기자회견", "source": "Federal Reserve", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "watch": "정책금리·성명 문구·파월 기자회견", "response": "첫 가격 반응보다 금리 경로와 이익 전망 변화를 확인하고, 방향이 엇갈리면 현금 비중과 분할 접근을 유지한다."},
    {"date": "2026-10-29", "event": "미국 3분기 GDP 속보·9월 PCE", "source": "BEA", "url": "https://www.bea.gov/news/schedule", "watch": "민간 최종수요와 물가", "response": "성장·물가 동반 상향은 금리 부담, 성장 유지·물가 둔화는 실적주 우호 조합으로 구분한다."},
    {"date": "2026-11-06", "event": "미국 10월 고용", "source": "BLS", "url": "https://www.bls.gov/schedule/2026/", "watch": "고용 추세와 이전치 수정", "response": "한 달 숫자보다 3개월 평균과 이전치 수정을 확인한 뒤 경기민감·방어 섹터 우선순위를 조정한다."},
    {"date": "2026-11-10", "event": "미국 10월 CPI", "source": "BLS", "url": "https://www.bls.gov/schedule/2026/", "watch": "서비스·주거비 물가", "response": "서비스 물가가 꺾이지 않으면 밸류 부담을 낮추고, 둔화가 이어지면 F.PER 하락 종목을 우선한다."},
    {"date": "2026-11-25", "event": "미국 3분기 GDP 2차 추정·10월 PCE", "source": "BEA", "url": "https://www.bea.gov/news/schedule", "watch": "GDP 수정·소비·근원 PCE", "response": "소비 둔화와 마진 압박이 겹치는 업종은 피하고, 수요가 유지되는 제품군을 분리해 본다."},
    {"date": "2026-12-04", "event": "미국 11월 고용", "source": "BLS", "url": "https://www.bls.gov/schedule/news_release/empsit.htm", "watch": "연말 고용과 임금", "response": "12월 FOMC 직전 금리 기대가 과도하게 움직일 수 있어 발표 직후 추격보다 확인을 우선한다."},
    {"date": "2026-12-09", "event": "FOMC 금리 결정·경제전망(SEP)", "source": "Federal Reserve", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "watch": "점도표·성장·물가 전망", "response": "점도표 변화가 실제 이익 전망과 일치하는지 확인하고, 멀티플만 오른 종목은 비중을 보수적으로 관리한다."},
    {"date": "2026-12-23", "event": "미국 3분기 GDP 3차 추정·11월 PCE", "source": "BEA", "url": "https://www.bea.gov/news/schedule", "watch": "연말 소비·근원 PCE·GDP 수정폭", "response": "소비와 물가가 함께 강하면 금리 부담을, 물가 둔화와 이익 유지가 겹치면 낮은 PRI 실적주를 분할 확인한다."},
)


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


def build_context(markets: dict[str, dict], fed: dict, checked_at: datetime, fear_greed: dict | None = None) -> dict:
    dates = {row["date"] for row in markets.values()}
    if len(dates) != 1:
        raise ValueError(f"미국 시장 지표 거래일 불일치: {sorted(dates)}")
    market_date = dates.pop()
    if (checked_at.astimezone(NEW_YORK).date() - datetime.fromisoformat(market_date).date()).days > US_MACRO_MAX_STALE_CALENDAR_DAYS:
        raise ValueError(f"미국 시장 종가가 오래됐습니다: {market_date}")
    sp, nasdaq, dow, sox, vix = (
        markets[key] for key in ("sp500", "nasdaq", "dow", "semiconductor", "vix")
    )
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
    start = checked_at.date()
    end = start + timedelta(days=92)
    events = [event for event in MACRO_EVENTS if start <= datetime.fromisoformat(event["date"]).date() <= end]
    return {
        "source": "미국 전 거래일 종가: Yahoo Finance·TradingView · 통화정책: Federal Reserve",
        "checkedAt": checked_at.astimezone(SEOUL).strftime("%Y-%m-%d %H:%M KST"),
        "marketDate": market_date,
        "items": [
            {"title": f"미국 {date_label} 전 거래일 종가 · TradingView", "url": market_url, "publishedAt": market_date},
            {"title": "CBOE VIX · 향후 30일 예상 변동성", "url": "https://www.cboe.com/tradable-products/vix", "publishedAt": market_date},
            *([{"title": "Fear & Greed Index · 시장 심리", "url": fear_greed["sourceUrl"], "publishedAt": fear_greed["date"]}] if fear_greed else []),
            {key: fed[key] for key in ("title", "url", "publishedAt")},
            *[{key: briefing[key] for key in ("title", "url", "publishedAt")} for briefing in briefings],
        ],
        "briefings": briefings,
        "markets": {key: markets[key] for key in ("sp500", "nasdaq", "dow", "semiconductor", "vix") if key in markets},
        "fearGreed": fear_greed,
        "nextEvents": events,
        "flags": {"rates": True, "industry": True, "geopolitics": risk_off},
        "sortMode": mode,
        "preferredSectors": sectors,
        "summary": {
            "current": f"미국 {date_label} 장 마감: S&P 500 {sp['changePct']:+.2f}%, 나스닥 {nasdaq['changePct']:+.2f}%, 다우 {dow['changePct']:+.2f}%, 필라델피아 반도체 {sox['changePct']:+.2f}%, CBOE VIX {vix['close']:.2f}" + (f", Fear & Greed {fear_greed['value']:.1f}({fear_greed['label']})" if fear_greed else "") + f". {regime} 국면으로 해석합니다.",
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
            response = client.get(YAHOO_CHART.format(symbol=symbol), params={"range": "3mo", "interval": "1d"})
            response.raise_for_status()
            markets[key] = parse_yahoo_chart(response.json(), now=now)
        fear_greed = None
        try:
            response = client.get(FEAR_GREED_URL)
            response.raise_for_status()
            fear_greed = parse_fear_greed(response.json())
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            print(f"⚠ Fear & Greed 수집 실패 — 결측으로 표시: {type(exc).__name__}")
        response = client.get(FED_RSS)
        response.raise_for_status()
        fed = parse_fed_rss(response.text)
        try:
            statement = client.get(fed["url"])
            statement.raise_for_status()
            fed.update(parse_fed_statement(statement.text))
        except httpx.HTTPError:
            print("⚠ FOMC 성명 본문 확인 실패 — 금리·물가 수치 표시 생략")
    return build_context(markets, fed, now, fear_greed)


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
