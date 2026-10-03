# PRD Ref: §9, §10 — 미국 전일 장마감·공식 매크로 스냅샷
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.collectors.us_macro_daily import MACRO_EVENTS, build_context, parse_fear_greed, parse_fed_rss, parse_fed_statement, parse_yahoo_chart, should_write_snapshot
from src.collectors.us_macro_daily import SYMBOLS, parse_recent_issue_rss, parse_recent_bea_releases, parse_issue_fact


def test_recent_atom_captures_last_night_and_excludes_stale_future_untrusted():
    now = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    entries = "".join(f'''<entry><title>Employment Situation</title><link href="{url}"/>
        <published>{day}T12:00:00Z</published><content>Both nonfarm payroll employment (+29,000) and the unemployment rate (4.2 percent) changed little.</content></entry>'''
        for day, url in [("2026-10-02", "https://www.bls.gov/news.release/archives/empsit_10022026.htm"),
                         ("2026-09-25", "https://www.bls.gov/old"),
                         ("2026-10-04", "https://www.bls.gov/future"),
                         ("2026-10-01", "https://www.bls.gov.evil.test/fake")])
    results = parse_recent_issue_rss(f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>', "BLS", now)
    assert len(results) == 1
    assert results[0]["publishedAt"] == "2026-10-02"
    assert results[0]["fact"] == "비농업 고용 변화 +29,000명 · 실업률 4.2%"
    assert "금리" in results[0]["marketImpact"]


def test_recent_rss_and_bea_keep_publication_date_not_observation_period():
    now = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
    rss = '<rss><channel><item><title>Federal Reserve interest rate announcement</title><link>https://www.federalreserve.gov/new</link><pubDate>Wed, 30 Sep 2026 18:00:00 GMT</pubDate></item></channel></rss>'
    assert len(parse_recent_issue_rss(rss, "Federal Reserve", now)) == 1
    html = '<table><tr><td><a href="/news/2026/gdp">GDP and State Personal Income, 2nd Quarter 2026</a></td><td>September 30, 2026</td></tr></table>'
    issue = parse_recent_bea_releases(html, now)[0]
    assert issue["label"] == "미국 성장·기업 이익 발표"
    assert issue["publishedAt"] == "2026-09-30"
    assert parse_issue_fact('No verified figure') is None
    assert parse_issue_fact('Real gross domestic product decreased at an annual rate of 0.7 percent') == '실질 GDP 전분기 대비 연율 -0.7%'
    assert parse_issue_fact('From the preceding month, the PCE price index for August increased 0.3 percent. Excluding food and energy, the PCE price index increased 0.2 percent.') == 'PCE 물가 전월 대비 +0.3% · 근원 PCE 전월 대비 +0.2%'
    assert parse_issue_fact('The number of job openings was little changed at 7.1 million in August.') == '구인 건수 710만 건'


def test_nasdaq100_is_separate_source_and_same_day_new_issues_trigger_write():
    assert SYMBOLS["nasdaq100"] == "%5ENDX"
    assert SYMBOLS["nasdaq"] == "%5EIXIC"
    prior = {"checkedAt": "2026-10-03 07:00 KST", "marketDate": "2026-10-02", "recentIssues": []}
    assert should_write_snapshot(prior, {**prior, "recentIssues": [{"url": "https://www.bls.gov/new"}]})


def test_macro_ui_uses_ndx_and_removes_pencil_and_earnings_badge():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    table = (root / 'dashboard/components/DiscoveryTable.tsx').read_text(encoding='utf-8')
    charts = (root / 'dashboard/components/MacroMarketOverview.tsx').read_text(encoding='utf-8')
    assert '✎' not in table
    assert '📊 실적 {dataAsOf' not in table
    assert '＋ 직접 입력…' in table
    assert 'const nasdaq = markets.nasdaq100' in charts
    assert 'Fear & Greed × 나스닥100' in charts


def test_premarket_vix_cannot_mix_with_previous_completed_us_session():
    payload = {"chart": {"result": [{
        "timestamp": [1789416000, 1789502400, 1789588800],
        "indicators": {"quote": [{"close": [100, 98, 95]}]},
    }]}}
    now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)  # 뉴욕 08:00, 장 시작 전
    result = parse_yahoo_chart(payload, now=now)
    assert result["date"] == "2026-09-15"
    assert result["changePct"] == -2.0


def test_korea_market_accepts_today_only_from_1600_kst():
    seoul = ZoneInfo("Asia/Seoul")
    payload = {"chart": {"result": [{
        "timestamp": [
            int(datetime(2026, 9, 25, 9, tzinfo=seoul).timestamp()),
            int(datetime(2026, 9, 28, 9, tzinfo=seoul).timestamp()),
            int(datetime(2026, 9, 29, 9, tzinfo=seoul).timestamp()),
        ],
        "indicators": {"quote": [{"close": [3380, 3400, 3434]}]},
    }]}}
    before = parse_yahoo_chart(
        payload, now=datetime(2026, 9, 29, 15, 59, tzinfo=seoul), market_tz=seoul
    )
    after = parse_yahoo_chart(
        payload, now=datetime(2026, 9, 29, 16, 0, tzinfo=seoul), market_tz=seoul
    )
    assert before["date"] == "2026-09-28"
    assert after["date"] == "2026-09-29"


def test_fed_rss_prefers_latest_fomc_statement_over_discount_minutes():
    rss = """<rss><channel>
      <item><title>Minutes of discount meetings</title><link>https://www.federalreserve.gov/one</link><pubDate>Tue, 25 Aug 2026 18:00:00 GMT</pubDate></item>
      <item><title>Federal Reserve issues FOMC statement</title><link>https://www.federalreserve.gov/two</link><pubDate>Wed, 29 Jul 2026 18:00:00 GMT</pubDate></item>
    </channel></rss>"""
    result = parse_fed_rss(rss)
    assert result["url"].endswith("/two")
    assert result["publishedAt"] == "2026-07-29"


def test_fed_policy_range_handles_mixed_fraction_and_only_verified_inflation():
    result = parse_fed_statement("<p>The Committee decided to maintain the target range for the federal funds rate at 3-1/2 to 3-3/4 percent.</p><p>Inflation remains elevated relative to the Committee's 2 percent goal.</p>")
    assert result["policyRangePct"] == [3.5, 3.75]
    assert result["inflationAboveTarget"] is True
    assert "policyRangePct" not in parse_fed_statement("<p>No policy rate figure.</p>")


def test_market_regime_changes_default_sort_without_mixing_score_and_pri():
    now = datetime(2026, 9, 16, 0, 0, tzinfo=timezone.utc)
    markets = {
        "sp500": {"date": "2026-09-15", "close": 7000, "changePct": -0.3},
        "nasdaq": {"date": "2026-09-15", "close": 22000, "changePct": -0.5},
        "dow": {"date": "2026-09-15", "close": 45000, "changePct": 0.1},
        "semiconductor": {"date": "2026-09-15", "close": 9000, "changePct": 0.4},
        "vix": {"date": "2026-09-15", "close": 17, "changePct": -1},
    }
    fed = {"title": "미 연준 FOMC 성명 (2026-07-29)", "url": "https://www.federalreserve.gov/example", "publishedAt": "2026-07-29"}
    growth = build_context(markets, fed, now)
    assert growth["sortMode"] == "earnings_growth"
    assert growth["preferredSectors"][0] == "반도체 장비"
    markets["vix"]["close"] = 28
    defensive = build_context(markets, fed, now)
    assert defensive["sortMode"] == "quality_price"
    assert defensive["preferredSectors"][0] == "전력인프라"


def test_korea_flow_sets_board_priority_without_forcing_same_market_date():
    now = datetime(2026, 9, 16, 0, 0, tzinfo=timezone.utc)
    markets = {
        "sp500": {"date": "2026-09-15", "close": 7000, "changePct": 0.2},
        "nasdaq": {"date": "2026-09-15", "close": 22000, "changePct": 0.3},
        "dow": {"date": "2026-09-15", "close": 45000, "changePct": 0.1},
        "semiconductor": {"date": "2026-09-15", "close": 9000, "changePct": 0.4},
        "vix": {"date": "2026-09-15", "close": 17, "changePct": -1},
        "kospi": {"date": "2026-09-16", "close": 3600, "changePct": 0.2},
        "kosdaq": {"date": "2026-09-16", "close": 980, "changePct": 1.1},
    }
    fed = {"title": "FOMC", "url": "https://www.federalreserve.gov/example", "publishedAt": "2026-07-29"}
    context = build_context(markets, fed, now)
    assert context["koreaMarketDate"] == "2026-09-16"
    assert context["koreaMode"] == "risk_on"
    assert context["preferredBoards"] == ["KOSDAQ", "KOSPI"]
    assert "미국·글로벌 적합 섹터" in context["summary"]["recommendedSort"]
    assert "AI" in context["globalSectorTilts"]
    assert "로봇기계" in context["globalSectorTilts"]
    assert "로봇기계" in context["preferredSectors"]


def test_fear_greed_deduplicates_latest_day_and_keeps_bounded_history():
    parsed = parse_fear_greed({"dates": ["2026-09-21", "2026-09-22", "2026-09-22"], "values": [28, 34, 35]})
    assert parsed["value"] == 35
    assert parsed["label"] == "공포"
    assert parsed["history"] == [
        {"date": "2026-09-21", "value": 28.0},
        {"date": "2026-09-22", "value": 35.0},
    ]


def test_seven_oclock_snapshot_replaces_early_prewarm_but_not_repeated_run():
    prior = {"checkedAt": "2026-09-18 06:45 KST", "marketDate": "2026-09-17", "koreaMarketDate": "2026-09-17"}
    at_seven = {"checkedAt": "2026-09-18 07:00 KST", "marketDate": "2026-09-17", "koreaMarketDate": "2026-09-17"}
    assert should_write_snapshot(prior, at_seven)
    assert not should_write_snapshot(at_seven, {**at_seven, "checkedAt": "2026-09-18 07:30 KST"})
    assert should_write_snapshot(at_seven, {**at_seven, "marketDate": "2026-09-18"})
    assert should_write_snapshot(at_seven, {
        **at_seven, "checkedAt": "2026-09-18 16:10 KST", "koreaMarketDate": "2026-09-18"
    })


def test_official_events_have_direct_sources_and_at_most_three_gold_stars():
    important = [event for event in MACRO_EVENTS if event.get("important")]
    assert len(important) == 3
    assert all(event["url"].startswith("https://") for event in MACRO_EVENTS)
    assert all("/schedule/news_release/" in event["url"] for event in MACRO_EVENTS if event["source"] == "BLS")
    assert all(event["url"].endswith("/full") for event in MACRO_EVENTS if event["source"] == "BEA")
