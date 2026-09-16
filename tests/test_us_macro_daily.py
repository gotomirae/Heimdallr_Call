# PRD Ref: §9, §10 — 미국 전일 장마감·공식 매크로 스냅샷
from __future__ import annotations

from datetime import datetime, timezone

from src.collectors.us_macro_daily import build_context, parse_fed_rss, parse_fed_statement, parse_yahoo_chart


def test_premarket_vix_cannot_mix_with_previous_completed_us_session():
    payload = {"chart": {"result": [{
        "timestamp": [1789416000, 1789502400, 1789588800],
        "indicators": {"quote": [{"close": [100, 98, 95]}]},
    }]}}
    now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)  # 뉴욕 08:00, 장 시작 전
    result = parse_yahoo_chart(payload, now=now)
    assert result["date"] == "2026-09-15"
    assert result["changePct"] == -2.0


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
