# PRD Ref: §9.1 — 운영 대시보드의 잔여 계약
"""DB에 이미 있는 종목 상세 지표가 화면 배선에서 다시 빠지지 않게 한다."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUERIES = (ROOT / "dashboard/lib/queries.ts").read_text(encoding="utf-8")
TYPES = (ROOT / "dashboard/lib/types.ts").read_text(encoding="utf-8")
STOCK = (ROOT / "dashboard/app/stock/[code]/page.tsx").read_text(encoding="utf-8")
HOME = (ROOT / "dashboard/app/page.tsx").read_text(encoding="utf-8")
DISCOVERY = (ROOT / "dashboard/components/DiscoveryTable.tsx").read_text(encoding="utf-8")
COST_ROUTE = (ROOT / "dashboard/app/api/cost/route.ts").read_text(encoding="utf-8")
QUARTER_CHART = (ROOT / "dashboard/components/QuarterlyChart.tsx").read_text(encoding="utf-8")
WEEKLY_CHART = (ROOT / "dashboard/components/WeeklyPriceChart.tsx").read_text(encoding="utf-8")


def test_query_contract_includes_existing_prd_columns():
    for column in (
        "score_final",
        "score_delta",
        "pctile_in_quarter",
        "ret_3m",
        "ret_6m",
        "ret_12m",
        "rel_ret_6m",
        "rel_ret_12m",
    ):
        assert f'"{column}"' in QUERIES
        assert column in TYPES


def test_stock_detail_renders_prd_evidence_without_inventing_values():
    for label in (
        "분기 내 백분위",
        "FCF",
        "과거 9분기 평균 PER 대비",
        "참고 PEG",
        "섹터 비교",
        "종목별 결과 추적",
        "네이버 증권 기업실적분석",
        "주간 종가",
    ):
        assert label in STOCK

    assert 'title="공시 발췌"' not in STOCK


def test_watchlist_replaces_duplicate_all_stocks_route():
    route = ROOT / "dashboard/app/watchlist/page.tsx"
    assert route.exists()
    source = route.read_text(encoding="utf-8")
    assert "watchlistOnly" in source
    assert not (ROOT / "dashboard/app/screener/page.tsx").exists()
    assert "localStorage" in DISCOVERY
    assert "^[0-9A-Z]{6}$" in DISCOVERY, "T6 영숫자 종목코드도 관심 종목에 남아야 한다"


def test_cost_history_pages_and_exposes_forecast_basis():
    assert ".range(" in COST_ROUTE
    assert "months:" in COST_ROUTE
    assert "nextMonthForecastUsd" in COST_ROUTE
    assert "forecastBasis" in COST_ROUTE


def test_sector_comparison_reads_the_exact_evaluated_quarter_with_paging():
    assert "getScreensForQuarter" in QUERIES
    assert "selectAll<ScreenRow>" in QUERIES
    assert "trailing4qPer" in STOCK


def test_quarter_chart_uses_opm_and_weekly_price_matches_its_period():
    for label in ("매출", "매출 YoY", "영업이익", "영업이익 YoY", "OPM", "수주잔고", "신규수주"):
        assert label in QUARTER_CHART
    assert 'dataKey="close"' not in QUARTER_CHART
    assert "fromDate={weeklyFromDate}" in STOCK
    assert "MACD (12·26·9)" in WEEKLY_CHART and "RSI (14)" in WEEKLY_CHART


def test_growth_dashboard_title_and_quarter_chart_display_contract():
    assert "성장 가속 종목" in HOME
    assert "실적 가속 종목" not in HOME
    assert "매출 YoY · 영업이익 YoY" in QUARTER_CHART
    assert "수주잔고 · 신규수주" in QUARTER_CHART
    assert QUARTER_CHART.count("<LabelList") == 7
    assert "영업이익 · OPM" in QUARTER_CHART
    assert QUARTER_CHART.index("<RevenuePanel") < QUARTER_CHART.index("<EarningsPanel") < QUARTER_CHART.index("<GrowthPanel")
    assert 'dataKey="revenueYoy"' in QUARTER_CHART
    assert 'dataKey="opYoy"' in QUARTER_CHART
    assert 'dataKey="orderBacklog"' in QUARTER_CHART
    assert 'dataKey="newOrders"' in QUARTER_CHART
    assert "분기별 값 라벨 · 영업이익과 OPM, 성장률과 수주 항목은 한눈에 비교" in STOCK
    assert "각 항목은 독립 축" not in STOCK


def test_pri_five_inputs_and_requested_history_are_visible():
    for field in (
        "high_52w_drawdown_pct", "announcement_return_pct", "per_vs_9q_avg_pct",
        "foreign_net_ratio_5d", "rsi_14",
    ):
        assert field in QUERIES and field in TYPES
    for label in ("매출 YoY", "매출 QoQ", "영업이익 YoY", "영업이익 QoQ", "OPM", "FCF", "구분"):
        assert label in STOCK
    for removed in ("매출총이익", "지배순익", "TTM 영업익", "매출채권", "주식수"):
        assert removed not in STOCK


def test_discovery_table_has_chained_sorting_and_grouped_headers():
    filters = (ROOT / "dashboard/lib/discoveryFilters.ts").read_text(encoding="utf-8")
    page = (ROOT / "dashboard/app/page.tsx").read_text(encoding="utf-8")

    assert 'marketCap: "시총"' in DISCOVERY
    assert 'label="주가 반영도"' in DISCOVERY
    assert "분기실적 발표" in DISCOVERY
    assert "종목 정보" in DISCOVERY and "실적 · 가격" in DISCOVERY
    assert "sorts: SortRule[]" in filters
    assert "sorts.map" in DISCOVERY
    assert "priority: index + 1" in DISCOVERY
    assert "원본" in DISCOVERY and "내림" in DISCOVERY and "오름" in DISCOVERY
    for category in ("성장 가속", "매출 YoY 둔화 + 영익 YoY 가속", "턴어라운드", "기타", "전 종목"):
        assert category in DISCOVERY
    assert 'gate: "growth"' in filters
    assert 'r.category !== gate' in DISCOVERY
    assert "turnaround: s.turnaround" in page
    assert "r.turnaround &&" not in DISCOVERY, "등급 칸에는 턴어라운드 문구를 중복 표시하지 않는다"


def test_only_growth_acceleration_renders_llm_and_links_are_exact():
    assert 'isGrowthAcceleration ? <Card' in STOCK
    assert "(1단계) 잠정실적 발표 초기 분석" in STOCK
    assert "(2단계) 분기/반기/사업보고서 공시 후 최종 분석" in STOCK
    assert "stockeasyStockUrl(code)" in STOCK
    assert "naverDisclosureUrl" not in STOCK
