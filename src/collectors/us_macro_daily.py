# PRD Ref: §9, §10 — 미국 07:00·한국 16:00 완료 거래일 매크로 스냅샷
"""대시보드 렌더와 분리된 매크로 수집기. 네트워크 실패 시 이전 스냅샷을 보존한다."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from src.config.constants import (
    KOREA_MARKET_COMPLETED_HOUR_KST,
    US_MACRO_EQUITY_DAILY_DROP_PCT,
    US_MACRO_MARKET_CLOSE_GRACE_MINUTES,
    US_MACRO_MAX_STALE_CALENDAR_DAYS,
    US_MACRO_VIX_RISK_OFF,
    US_MACRO_ISSUE_LOOKBACK_DAYS,
    US_MACRO_RECENT_ISSUE_LIMIT,
)
from src.utils.console import enable_utf8_stdout

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "dashboard" / "lib" / "macro-daily.json"
BRIEFINGS = ROOT / "dashboard" / "lib" / "macro-briefings.json"
FED_RSS = "https://www.federalreserve.gov/feeds/press_monetary.xml"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
SYMBOLS = {
    "sp500": "%5EGSPC", "nasdaq": "%5EIXIC", "dow": "%5EDJI",
    "semiconductor": "%5ESOX", "vix": "%5EVIX", "nasdaq100": "%5ENDX",
    "kospi": "%5EKS11", "kosdaq": "%5EKQ11",
}
FEAR_GREED_URL = "https://fearandgreedgraph.com/api/fear-greed"
NEW_YORK = ZoneInfo("America/New_York")
SEOUL = ZoneInfo("Asia/Seoul")
RECENT_ISSUE_FEEDS = (
    ("BLS", "https://www.bls.gov/feed/empsit.rss"),
    ("BLS", "https://www.bls.gov/feed/jolts.rss"),
    ("BLS", "https://www.bls.gov/feed/cpi.rss"),
    ("Federal Reserve", FED_RSS),
)
BEA_RELEASES = "https://www.bea.gov/news/current-releases"


def recent_issue(item: dict, now: datetime) -> dict | None:
    """최근 7일 공식 발표만 사용. 실제 발표 사실과 조건부 영향 해석을 분리한다."""
    try:
        published = datetime.fromisoformat(item["publishedAt"]).date()
    except (ValueError, TypeError, KeyError):
        return None
    today = now.astimezone(SEOUL).date()
    if not today - timedelta(days=US_MACRO_ISSUE_LOOKBACK_DAYS - 1) <= published <= today:
        return None
    parsed_url = urlparse(item.get("url", ""))
    if parsed_url.scheme != "https" or parsed_url.hostname not in {"www.bls.gov", "www.bea.gov", "www.federalreserve.gov"}:
        return None
    title = item.get("title", "")
    topic = title + " " + item.get("url", "")
    if re.search(r"Employment Situation|Job Openings|payroll|empsit_|jolts_", topic, re.I):
        label = "미국 구인·이직(JOLTS) 발표" if re.search(r"Job Openings|jolts_", topic, re.I) else "미국 고용·실업률 발표"
        emoji = "👷"
        impact = "고용·임금이 강하면 금리 인하 기대 약화와 성장주 밸류 부담으로 이어질 수 있습니다. 완만한 둔화는 금리 부담 완화, 급격한 둔화는 소비·기업 이익 위험으로 구분해 봅니다."
    elif re.search(r"GDP|Gross Domestic|Corporate Profits", title, re.I):
        label, emoji = "미국 성장·기업 이익 발표", "🏭"
        impact = "민간 최종수요·기업 이익 개선이 확인되면 수출·경기민감 업종의 실적 지속성을 점검합니다. 성장 둔화와 물가 상승이 겹치면 마진 및 밸류 부담이 커질 수 있습니다."
    elif re.search(r"Personal Income|Consumer Price|Inflation|cpi_", topic, re.I):
        label, emoji = "미국 소비·물가 발표", "🛒"
        impact = "근원 물가가 재가속하면 장기금리와 고PER 주식 부담을 확인합니다. 물가 둔화와 소비 유지가 함께 나타나면 실적이 뒷받침되는 성장주에 우호적일 수 있습니다."
    elif re.search(r"FOMC|monetary|discount|interest rate", title, re.I):
        label, emoji = "연준 정책 관련 발표", "🏦"
        impact = "새 정책 결정인지 과거 회의 기록인지 원문을 구분합니다. 긴축적인 금리 경로는 기술주 밸류와 원화에 부담, 완화적인 경로는 부담 완화 요인이지만 경기 악화 여부를 함께 확인해야 합니다."
    else:
        return None
    return {**item, "label": label, "emoji": emoji, "marketImpact": impact,
            "fact": item.get("fact") or "공식 발표 확인 · 세부 결과는 원문에서 확인하세요."}


def parse_recent_issue_rss(xml_text: str, source: str, now: datetime) -> list[dict]:
    items = []
    root = ElementTree.fromstring(xml_text)
    atom = "{http://www.w3.org/2005/Atom}"
    if root.tag not in {"rss", f"{atom}feed"}:
        raise ValueError("공식 발표 피드의 RSS/Atom 구조를 확인하지 못했습니다")
    entries = root.findall("./channel/item") + root.findall(f"{atom}entry")
    for node in entries:
        try:
            raw = node.findtext("pubDate")
            timestamp = (parsedate_to_datetime(raw) if raw else
                         datetime.fromisoformat((node.findtext(f"{atom}published") or "").replace("Z", "+00:00")))
            if timestamp > now:
                continue
            published = timestamp.astimezone(SEOUL).date().isoformat()
        except (ValueError, TypeError, AttributeError):
            continue
        link = node.find(f"{atom}link")
        title = (node.findtext("title") or node.findtext(f"{atom}title") or "").strip()
        body = node.findtext("description") or node.findtext(f"{atom}content") or title
        url = (node.findtext("link") or (link.get("href") if link is not None else "") or "").strip()
        item = recent_issue({"title": title, "url": url, "publishedAt": published, "source": source,
                             "fact": parse_issue_fact(body)}, now)
        if item:
            items.append(item)
    return items


def parse_issue_fact(body: str) -> str | None:
    """출처가 직접 명시한 수치만 짧은 한국어로 변환한다. 미파싱은 추측하지 않는다."""
    text = BeautifulSoup(body, "html.parser").get_text(" ", strip=True)
    facts = []
    payroll = re.search(r"(?:nonfarm )?payroll employment\s*\(([+-]?[\d,]+)\)", text, re.I)
    unemployment = re.search(r"unemployment rate\s*\(([\d.]+)\s*(?:percent|%)\)", text, re.I)
    if payroll:
        facts.append(f"비농업 고용 변화 {payroll[1]}명")
    if unemployment:
        facts.append(f"실업률 {unemployment[1]}%")
    openings = re.search(r"(?:number of )?job openings\b[^.]{0,100}?at ([\d.]+) million", text, re.I)
    if openings:
        facts.append(f"구인 건수 {float(openings[1]) * 100:g}만 건")
    gdp = re.search(r"Real gross domestic product.*?\b(increased|decreased)\b.*?annual rate of ([\d.]+) percent", text, re.I)
    if gdp:
        facts.append(f"실질 GDP 전분기 대비 연율 {'+' if gdp[1].lower() == 'increased' else '-'}{gdp[2]}%")
    monthly = re.search(r"From the preceding month, the PCE price index[^.]{0,80}?\b(increased|decreased) ([\d.]+) percent", text, re.I)
    core = re.search(r"Excluding food and energy, the PCE price index\s+(increased|decreased) ([\d.]+) percent\s*\.", text, re.I)
    if monthly:
        facts.append(f"PCE 물가 전월 대비 {'+' if monthly[1].lower() == 'increased' else '-'}{monthly[2]}%")
    if core and monthly:
        facts.append(f"근원 PCE 전월 대비 {'+' if core[1].lower() == 'increased' else '-'}{core[2]}%")
    return " · ".join(facts) or None


def parse_recent_bea_releases(html: str, now: datetime) -> list[dict]:
    items = []
    for row in BeautifulSoup(html, "html.parser").select("tr"):
        link = row.find("a", href=True)
        match = re.search(r"\b([A-Z][a-z]+ \d{1,2}, \d{4})\b", row.get_text(" ", strip=True))
        if not link or not match:
            continue
        try:
            published = datetime.strptime(match[1], "%B %d, %Y").date().isoformat()
        except ValueError:
            continue
        item = recent_issue({"title": link.get_text(" ", strip=True), "url": urljoin(BEA_RELEASES, link["href"]),
                             "publishedAt": published, "source": "BEA"}, now)
        if item:
            items.append(item)
    return items


def parse_yahoo_chart(payload: dict, *, now: datetime, market_tz: ZoneInfo = NEW_YORK) -> dict:
    """완료된 최근 두 거래일 종가로 전일 수익률을 계산한다."""
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise ValueError("Yahoo chart 결과 없음")
    chart = result[0]
    timestamps = chart.get("timestamp") or []
    quotes = ((chart.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    local_now = now.astimezone(market_tz)
    close_time = (
        time(KOREA_MARKET_COMPLETED_HOUR_KST, 0) if market_tz.key == SEOUL.key
        else time(16, US_MACRO_MARKET_CLOSE_GRACE_MINUTES)
    )
    completed_through = local_now.date() if local_now.time() >= close_time else local_now.date() - timedelta(days=1)
    measured = [
        (datetime.fromtimestamp(int(timestamp), market_tz).date().isoformat(), float(close))
        for timestamp, close in zip(timestamps, quotes)
        if close is not None and float(close) > 0
        and datetime.fromtimestamp(int(timestamp), market_tz).date() <= completed_through
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
    {"date": "2026-09-30", "event": "미국 2분기 GDP 3차 추정·8월 PCE", "source": "BEA", "url": "https://www.bea.gov/news/schedule/full", "watch": "성장률 수정폭과 근원 PCE", "response": "물가가 예상보다 높으면 장기금리 민감 성장주의 추격을 줄이고, 둔화가 확인되면 실적 가속·낮은 PRI 종목을 분할 확인한다."},
    {"date": "2026-10-02", "event": "미국 9월 고용", "source": "BLS", "url": "https://www.bls.gov/schedule/news_release/empsit.htm", "watch": "신규고용·실업률·임금", "response": "강한 고용과 임금 재가속이 겹치면 금리 상승 위험을 우선하고, 완만한 둔화면 경기침체 신호와 구분한다."},
    {"date": "2026-10-14", "event": "미국 9월 CPI", "source": "BLS", "url": "https://www.bls.gov/schedule/news_release/cpi.htm", "watch": "근원 CPI 월간 속도", "response": "발표 전 포지션을 키우지 않고, 예상 상회 시 고PER 비중을 점검하며 예상 하회 시 이익 전망이 유지되는 성장주부터 본다.", "important": True},
    {"date": "2026-10-28", "event": "FOMC 금리 결정·기자회견", "source": "Federal Reserve", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "watch": "정책금리·성명 문구·파월 기자회견", "response": "첫 가격 반응보다 금리 경로와 이익 전망 변화를 확인하고, 방향이 엇갈리면 현금 비중과 분할 접근을 유지한다.", "important": True},
    {"date": "2026-10-29", "event": "미국 3분기 GDP 속보·9월 PCE", "source": "BEA", "url": "https://www.bea.gov/news/schedule/full", "watch": "민간 최종수요와 물가", "response": "성장·물가 동반 상향은 금리 부담, 성장 유지·물가 둔화는 실적주 우호 조합으로 구분한다."},
    {"date": "2026-11-06", "event": "미국 10월 고용", "source": "BLS", "url": "https://www.bls.gov/schedule/news_release/empsit.htm", "watch": "고용 추세와 이전치 수정", "response": "한 달 숫자보다 3개월 평균과 이전치 수정을 확인한 뒤 경기민감·방어 섹터 우선순위를 조정한다."},
    {"date": "2026-11-10", "event": "미국 10월 CPI", "source": "BLS", "url": "https://www.bls.gov/schedule/news_release/cpi.htm", "watch": "서비스·주거비 물가", "response": "서비스 물가가 꺾이지 않으면 밸류 부담을 낮추고, 둔화가 이어지면 F.PER 하락 종목을 우선한다."},
    {"date": "2026-11-25", "event": "미국 3분기 GDP 2차 추정·10월 PCE", "source": "BEA", "url": "https://www.bea.gov/news/schedule/full", "watch": "GDP 수정·소비·근원 PCE", "response": "소비 둔화와 마진 압박이 겹치는 업종은 피하고, 수요가 유지되는 제품군을 분리해 본다."},
    {"date": "2026-12-04", "event": "미국 11월 고용", "source": "BLS", "url": "https://www.bls.gov/schedule/news_release/empsit.htm", "watch": "연말 고용과 임금", "response": "12월 FOMC 직전 금리 기대가 과도하게 움직일 수 있어 발표 직후 추격보다 확인을 우선한다."},
    {"date": "2026-12-09", "event": "FOMC 금리 결정·경제전망(SEP)", "source": "Federal Reserve", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "watch": "점도표·성장·물가 전망", "response": "점도표 변화가 실제 이익 전망과 일치하는지 확인하고, 멀티플만 오른 종목은 비중을 보수적으로 관리한다.", "important": True},
    {"date": "2026-12-23", "event": "미국 3분기 GDP 3차 추정·11월 PCE", "source": "BEA", "url": "https://www.bea.gov/news/schedule/full", "watch": "연말 소비·근원 PCE·GDP 수정폭", "response": "소비와 물가가 함께 강하면 금리 부담을, 물가 둔화와 이익 유지가 겹치면 낮은 PRI 실적주를 분할 확인한다."},
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


def build_context(markets: dict[str, dict], fed: dict, checked_at: datetime, fear_greed: dict | None = None,
                  recent_issues: list[dict] | None = None, issue_failures: list[str] | None = None) -> dict:
    us_keys = ("sp500", "nasdaq", "dow", "semiconductor", "vix")
    dates = {markets[key]["date"] for key in us_keys}
    if len(dates) != 1:
        raise ValueError(f"미국 시장 지표 거래일 불일치: {sorted(dates)}")
    market_date = dates.pop()
    if markets.get("nasdaq100") and markets["nasdaq100"]["date"] != market_date:
        raise ValueError("나스닥100 완료 거래일 불일치")
    if (checked_at.astimezone(NEW_YORK).date() - datetime.fromisoformat(market_date).date()).days > US_MACRO_MAX_STALE_CALENDAR_DAYS:
        raise ValueError(f"미국 시장 종가가 오래됐습니다: {market_date}")
    sp, nasdaq, dow, sox, vix = (
        markets[key] for key in us_keys
    )
    korea = {key: markets[key] for key in ("kospi", "kosdaq") if key in markets}
    korea_dates = {row["date"] for row in korea.values()}
    if len(korea_dates) > 1:
        raise ValueError(f"한국 시장 지표 거래일 불일치: {sorted(korea_dates)}")
    korea_market_date = next(iter(korea_dates), None)
    kospi = korea.get("kospi")
    kosdaq = korea.get("kosdaq")
    risk_off = vix["close"] >= US_MACRO_VIX_RISK_OFF or (sp["changePct"] <= US_MACRO_EQUITY_DAILY_DROP_PCT and nasdaq["changePct"] <= US_MACRO_EQUITY_DAILY_DROP_PCT)
    ai_lead = sox["changePct"] > sp["changePct"] and sox["changePct"] > 0 and not risk_off
    if risk_off:
        mode = "quality_price"
        sectors = ["전력인프라", "우주방산", "조선·해운", "반도체 장비", "반도체 소재", "반도체 부품", "반도체 IDM"]
        regime = "변동성 확대·위험 회피"
    elif ai_lead:
        mode = "earnings_growth"
        sectors = ["반도체 장비", "반도체 소재", "반도체 부품", "반도체 DSP", "반도체 OSAT", "반도체 IDM", "AI", "전력인프라", "통신·네트워크", "우주방산"]
        regime = "미국 반도체 상대강세"
    else:
        mode = "balanced"
        sectors = ["전력인프라", "반도체 장비", "반도체 소재", "반도체 부품", "반도체 IDM", "우주방산", "조선·해운"]
        regime = "혼조·실적 확인"
    korea_mode = "mixed"
    preferred_boards = ["KOSPI", "KOSDAQ"]
    korea_summary = "한국 지수 미수집"
    if kospi and kosdaq:
        korea_summary = f"KOSPI {kospi['changePct']:+.2f}%, KOSDAQ {kosdaq['changePct']:+.2f}%"
        if kospi["changePct"] > 0 and kosdaq["changePct"] > 0:
            korea_mode = "risk_on"
        elif kospi["changePct"] < 0 and kosdaq["changePct"] < 0:
            korea_mode = "risk_off"
        preferred_boards = (
            ["KOSDAQ", "KOSPI"]
            if kosdaq["changePct"] > kospi["changePct"] and not risk_off
            else ["KOSPI", "KOSDAQ"]
        )
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
    global_text = " ".join(
        str(item.get(key) or "")
        for item in briefings
        for key in ("summary", "keyPoint", "marketImpact")
    )
    global_sector_tilts: list[str] = []
    if re.search(r"인공지능|\bAI\b|설비투자", global_text, re.I):
        global_sector_tilts += ["AI", "반도체 장비", "반도체 부품", "전력인프라", "통신·네트워크", "로봇기계"]
    if re.search(r"에너지|공급망|전쟁|분쟁", global_text):
        global_sector_tilts += ["전력인프라", "우주방산", "조선·해운"]
    if re.search(r"민간수요|소비지출", global_text):
        global_sector_tilts += ["자동차", "유통·소비재"]
    global_sector_tilts = list(dict.fromkeys(global_sector_tilts))
    # 미국 장 국면 상위 3개를 유지하면서 IMF·공식 경기지표의 글로벌 기회/위험을
    # 실제 순위 후보에 삽입한다. 화면 설명에만 쓰고 정렬에는 안 쓰는 상태를 막는다.
    sectors = list(dict.fromkeys([*sectors[:3], *global_sector_tilts, *sectors[3:]]))
    market_url = "https://www.tradingview.com/markets/stocks-usa/market-movers-all-stocks/"
    start = checked_at.date()
    end = start + timedelta(days=92)
    events = [event for event in MACRO_EVENTS if start <= datetime.fromisoformat(event["date"]).date() <= end]
    issues = {item["url"]: item for candidate in (recent_issues or [])
              if (item := recent_issue(candidate, checked_at)) is not None}
    issues = sorted(issues.values(), key=lambda item: item["publishedAt"], reverse=True)[:US_MACRO_RECENT_ISSUE_LIMIT]
    current_lines = [
        f"🇺🇸 {date_label} 미국 마감 · S&P 500 {sp['changePct']:+.2f}% / 나스닥 {nasdaq['changePct']:+.2f}% / 반도체 {sox['changePct']:+.2f}%",
        f"🌡️ VIX {vix['close']:.2f}" + (f" · Fear & Greed {fear_greed['value']:.1f} ({fear_greed['label']})" if fear_greed else " · Fear & Greed 미수집"),
        f"🇰🇷 {korea_market_date or '거래일 미확인'} 한국 마감 · {korea_summary}",
        f"🧭 종합 판단 · {regime}. 지수 방향과 실제 기업 이익을 함께 확인합니다.",
    ]
    return {
        "source": "미국·한국 전 거래일 종가: Yahoo Finance·TradingView · 통화정책: Federal Reserve · 글로벌: IMF",
        "checkedAt": checked_at.astimezone(SEOUL).strftime("%Y-%m-%d %H:%M KST"),
        "marketDate": market_date,
        "koreaMarketDate": korea_market_date,
        "items": [
            {"title": f"미국 {date_label} 전 거래일 종가 · TradingView", "url": market_url, "publishedAt": market_date},
            {"title": "CBOE VIX · 향후 30일 예상 변동성", "url": "https://www.cboe.com/tradable-products/vix", "publishedAt": market_date},
            *([{"title": "Fear & Greed Index · 시장 심리", "url": fear_greed["sourceUrl"], "publishedAt": fear_greed["date"]}] if fear_greed else []),
            {key: fed[key] for key in ("title", "url", "publishedAt")},
            *[{key: briefing[key] for key in ("title", "url", "publishedAt")} for briefing in briefings],
        ],
        "briefings": briefings,
        "markets": {key: markets[key] for key in (*us_keys, "nasdaq100", "kospi", "kosdaq") if key in markets},
        "recentIssues": issues,
        "recentIssueFailures": issue_failures or [],
        "recentIssueWindow": {"from": (checked_at.astimezone(SEOUL).date() - timedelta(days=US_MACRO_ISSUE_LOOKBACK_DAYS - 1)).isoformat(),
                              "through": checked_at.astimezone(SEOUL).date().isoformat()},
        "fearGreed": fear_greed,
        "nextEvents": events,
        "flags": {"rates": True, "industry": True, "geopolitics": risk_off},
        "sortMode": mode,
        "preferredSectors": sectors,
        "globalSectorTilts": global_sector_tilts,
        "preferredBoards": preferred_boards,
        "koreaMode": korea_mode,
        "summary": {
            "current": "\n".join(current_lines),
            "forward": "지난밤을 포함한 최근 7일 공식 발표를 확인합니다. 아래 영향 설명은 조건부 해석이며 실제 발표 결과나 확정 전망이 아닙니다.",
            "recommendedSort": "추천 정렬: " + (
                f"미국·글로벌 적합 섹터 → 한국 상대강세 시장({preferred_boards[0]}) → 섹터 5일 흐름 확인 → 초기 흑전·낮은 주가반영도 후보 → 높은 투자 매력도 → 높은 영업이익 YoY → 높은 내년 F.ROE → 낮은 주가반영도 → 등급 → 최신 분기"
                if mode == "earnings_growth" else
                f"미국·글로벌 적합 섹터 → 한국 상대강세 시장({preferred_boards[0]}) → 섹터 5일 흐름 확인 → 초기 흑전·낮은 주가반영도 후보 → 높은 투자 매력도 → 낮은 주가반영도 → 낮은 내년 F.PER → 높은 내년 F.ROE → 영업이익 YoY → 등급 → 최신 분기"
                if mode == "quality_price" else
                f"미국·글로벌 적합 섹터 → 한국 상대강세 시장({preferred_boards[0]}) → 섹터 5일 흐름 확인 → 초기 흑전·낮은 주가반영도 후보 → 높은 투자 매력도 → 낮은 주가반영도 → 높은 영업이익 YoY → 등급 → 최신 분기"
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
            markets[key] = parse_yahoo_chart(
                response.json(), now=now,
                market_tz=SEOUL if key in {"kospi", "kosdaq"} else NEW_YORK,
            )
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
        issues, failures = [], []
        for source, url in RECENT_ISSUE_FEEDS:
            try:
                response = client.get(url)
                response.raise_for_status()
                issues.extend(parse_recent_issue_rss(response.text, source, now))
            except (httpx.HTTPError, ValueError, ElementTree.ParseError):
                failures.append(url)
        try:
            response = client.get(BEA_RELEASES)
            response.raise_for_status()
            issues.extend(parse_recent_bea_releases(response.text, now))
        except (httpx.HTTPError, ValueError):
            failures.append(BEA_RELEASES)
        for item in issues:
            if item["source"] == "BEA":
                try:
                    response = client.get(item["url"])
                    response.raise_for_status()
                    item["fact"] = parse_issue_fact(response.text) or item["fact"]
                except httpx.HTTPError:
                    failures.append(item["url"])
    return build_context(markets, fed, now, fear_greed, issues, failures)


def should_write_snapshot(previous: dict, context: dict, *, force: bool = False) -> bool:
    """미국 07시 확인 또는 한국 16시 확정 거래일이 바뀌면 다시 기록한다."""
    previous_at = previous.get("checkedAt", "")
    current_at = context["checkedAt"]
    prewarm_needs_seven_oclock = (
        previous_at[:10] == current_at[:10]
        and previous_at[11:16] < "07:00" <= current_at[11:16]
    )
    return bool(
        force or prewarm_needs_seven_oclock
        or previous.get("recentIssues") != context.get("recentIssues")
        or previous.get("recentIssueFailures") != context.get("recentIssueFailures")
        or ("nasdaq100" not in previous.get("markets", {}) and "nasdaq100" in context.get("markets", {}))
        or (previous_at[:10], previous.get("marketDate"), previous.get("koreaMarketDate"))
        != (current_at[:10], context["marketDate"], context.get("koreaMarketDate"))
    )


def main() -> int:
    enable_utf8_stdout()
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
