# PRD Ref: §9.1 — 운영 대시보드의 잔여 계약
"""DB에 이미 있는 종목 상세 지표가 화면 배선에서 다시 빠지지 않게 한다."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUERIES = (ROOT / "dashboard/lib/queries.ts").read_text(encoding="utf-8")
SUPABASE = (ROOT / "dashboard/lib/supabase.ts").read_text(encoding="utf-8")
TYPES = (ROOT / "dashboard/lib/types.ts").read_text(encoding="utf-8")
STOCK = (ROOT / "dashboard/app/stock/[code]/page.tsx").read_text(encoding="utf-8")
HOME = (ROOT / "dashboard/app/page.tsx").read_text(encoding="utf-8")
DISCOVERY = (ROOT / "dashboard/components/DiscoveryTable.tsx").read_text(encoding="utf-8")
DISCOVERY_ROW = (ROOT / "dashboard/lib/discoveryRow.ts").read_text(encoding="utf-8")
COST_ROUTE = (ROOT / "dashboard/app/api/cost/route.ts").read_text(encoding="utf-8")
QUARTER_CHART = (ROOT / "dashboard/components/QuarterlyChart.tsx").read_text(encoding="utf-8")
DAILY_CHART = (ROOT / "dashboard/components/DailyPriceChart.tsx").read_text(encoding="utf-8")
NAVER = (ROOT / "dashboard/lib/naver.ts").read_text(encoding="utf-8")
MEANING = (ROOT / "dashboard/lib/metricMeaning.ts").read_text(encoding="utf-8")
PRI_BREAKDOWN = (ROOT / "dashboard/components/ScoreBreakdown.tsx").read_text(encoding="utf-8")
OUTCOME = (ROOT / "dashboard/app/outcome/page.tsx").read_text(encoding="utf-8")
SECTOR_EARNINGS = (ROOT / "dashboard/lib/sectorEarnings.ts").read_text(encoding="utf-8")
ANALYSIS_VIEW = (ROOT / "dashboard/lib/analysis.ts").read_text(encoding="utf-8")
ANALYSIS_SECTION = (ROOT / "dashboard/components/AnalysisSection.tsx").read_text(encoding="utf-8")


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
        "과거 3개년 평균 PER 대비",
        "PEG (자체 계산)",
        "섹터 비교",
        "종목별 결과 추적",
        "네이버 증권",
        "일간 종가",
        "올해 → 내년 ROE",
        "최신 분기 매출",
        "F.PER",
    ):
        assert label in STOCK

    assert 'title="공시 발췌"' not in STOCK
    assert "PBR" not in STOCK


def test_watchlist_replaces_duplicate_all_stocks_route():
    route = ROOT / "dashboard/app/watchlist/page.tsx"
    assert route.exists()
    source = route.read_text(encoding="utf-8")
    assert "watchlistOnly" in source
    assert not (ROOT / "dashboard/app/screener/page.tsx").exists()
    assert "localStorage" in DISCOVERY
    assert "^[0-9A-Z]{6}$" in DISCOVERY, "T6 영숫자 종목코드도 관심 종목에 남아야 한다"


def test_dashboard_transient_reads_retry_without_hiding_permanent_errors():
    for code in ("PGRST000", "PGRST001", "PGRST002", "PGRST003", "53300", "57014"):
        assert code in SUPABASE
    assert "readWithTransientRetry" in SUPABASE
    assert "TRANSIENT_HTTP_STATUSES" in SUPABASE
    assert "if (error.code !== UNDEFINED_COLUMN) throw error" in SUPABASE
    assert "withReadFallback" in HOME
    assert "0이 아니라 미수집" in HOME


def test_stock_detail_isolates_optional_reads_and_does_not_refetch_live_peer_data():
    assert "getUniverseForCode(code)" in STOCK
    assert "withDetailFallback" in STOCK
    assert "일부 보조 자료가 잠시 연결되지 않아 결측으로 표시했습니다" in STOCK
    assert "peerAnnual?.per ?? null" in STOCK
    assert "peerAnnual?.per ?? peerPrice?.per_current_ttm" not in STOCK
    assert STOCK.count("getNaverLiveSnapshot(") == 1
    assert "getFundamentals(peerScreen.code)" not in STOCK


def test_discovery_table_renders_rows_progressively_without_dropping_full_data():
    assert "constants.discovery_initial_rows" in DISCOVERY
    assert "constants.discovery_row_step" in DISCOVERY
    assert "filtered.slice(0, visibleLimit)" in DISCOVERY
    assert "setVisibleLimit((current) => current + ROW_STEP)" in DISCOVERY


def test_discovery_rows_use_compact_wire_contract_and_restore_all_outcomes():
    assert "wireRows={rows.map(packDiscoveryRow)}" in HOME
    assert "wireRows.map(unpackDiscoveryRow)" in DISCOVERY
    assert "export type DiscoveryRowWire = [" in DISCOVERY_ROW
    for day in (-5, 0, 5, 20, 40, 60):
        assert f"row.excess[{day}] ?? null" in DISCOVERY_ROW
    for field in ("code", "sectorProcess", "failReasons", "forwardRoe", "ret5d", "excess"):
        assert f"{field}:" in DISCOVERY_ROW


def test_cost_history_pages_and_exposes_forecast_basis():
    assert ".range(" in COST_ROUTE
    assert "months:" in COST_ROUTE
    assert "nextMonthForecastUsd" in COST_ROUTE
    assert "forecastBasis" in COST_ROUTE


def test_sector_comparison_reads_the_exact_evaluated_quarter_with_paging():
    assert "getScreensForQuarter" in QUERIES
    assert "selectAll<ScreenRow>" in QUERIES
    assert "productSimilarity" in STOCK
    assert "trailing4qPer" not in STOCK, "PER은 자체 계산하지 않고 네이버 값을 써야 한다"


def test_quarter_chart_uses_opm_and_daily_price_matches_its_period():
    for label in ("매출", "매출액 YoY", "영업이익", "영업이익 YoY", "OPM", "수주잔고", "신규수주"):
        assert label in QUARTER_CHART
    assert 'dataKey="close"' not in QUARTER_CHART
    assert "fromDate={dailyFromDate}" in STOCK
    assert ">MACD<" in DAILY_CHART and ">RSI<" in DAILY_CHART
    assert DAILY_CHART.count('syncId="daily-technical"') == 3
    assert "normalizeDailyRows" in DAILY_CHART
    assert "macdPoints" in DAILY_CHART
    assert "실적 발표" in DAILY_CHART and "ReferenceLine" in DAILY_CHART
    assert "api.finance.naver.com/siseJson.naver" in NAVER
    assert "appendNextQuarterConsensus" in STOCK


def test_stock_detail_uses_live_naver_quote_and_exact_valuation_source():
    for endpoint in ("/integration", "/finance/annual"):
        assert endpoint in NAVER
    for field in ("per4q", "fwdPer", "roe"):
        assert field in NAVER and field in STOCK
    assert "completedCloseAtKst16" in NAVER and "completedCloseAtKst16" in STOCK
    assert "네이버 올해 PER(예상)" in STOCK
    assert "네이버 내년 F.PER" in STOCK


def test_growth_dashboard_title_and_quarter_chart_display_contract():
    assert "발굴 목록" in HOME
    assert "실적 가속 종목" not in HOME
    assert "매출액 YoY" in QUARTER_CHART and "영업이익 YoY" in QUARTER_CHART
    assert "수주잔고 / 신규 수주" in QUARTER_CHART
    assert QUARTER_CHART.count("<LabelList") == 13
    assert "영업이익 / OPM" in QUARTER_CHART
    assert (
        QUARTER_CHART.index("<RevenuePanel")
        < QUARTER_CHART.index("<EarningsPanel")
        < QUARTER_CHART.index('<GrowthLinePanel points={points}')
    )
    assert 'dataKey="revenueYoyActual"' in QUARTER_CHART
    assert 'dataKey="opYoyForecast"' in QUARTER_CHART
    assert '<GrowthLinePanel points={points}' in QUARTER_CHART
    assert 'name="매출액 YoY 확정·잠정"' in QUARTER_CHART
    assert 'name="영업이익 YoY 전망"' in QUARTER_CHART
    assert 'strokeDasharray="5 4"' in QUARTER_CHART
    assert QUARTER_CHART.count("<YAxis") == 7, "매출·GPM과 영업이익·OPM은 금액/마진 축을 분리하고 YoY 두 선은 한 축을 공유해야 한다"
    assert "원값" in QUARTER_CHART and "connectNulls={false}" in QUARTER_CHART
    assert 'dataKey="orderBacklog"' in QUARTER_CHART
    assert 'dataKey="newOrders"' in QUARTER_CHART
    assert "분기별 값 라벨 · 매출액 YoY와 영업이익 YoY를 같은 좌표에서 비교" in STOCK
    assert "각 항목은 독립 축" not in STOCK


def test_ten_quarters_and_every_chart_metric_has_deterministic_meaning():
    assert "CHART_QUARTERS = 10" in (ROOT / "dashboard/lib/chart.ts").read_text(encoding="utf-8")
    assert ".slice(0, CHART_QUARTERS)" in STOCK
    for label in (
        "매출액", "영업이익", "OPM", "매출액 YoY", "영업이익 YoY",
        "수주잔고 · 신규수주", "네이버 일간 종가", "MACD", "RSI",
    ):
        assert label in MEANING
    assert "fundamentalMetricMeanings" in QUARTER_CHART
    assert "priceMeaning" in DAILY_CHART and "macdMeaning" in DAILY_CHART and "rsiMeaning" in DAILY_CHART


def test_llm_stage_timeline_is_event_driven_and_visible():
    for text in (
        "1단계 · 잠정실적", "2단계 · 정기보고서", "3단계 · LLM 추가 분석",
        "동일 단계·동일 근거의 실패도 반복 결제하지 않는다",
    ):
        assert text in STOCK


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


def test_pri_v4_exposes_five_price_reflection_factors_and_underlying_evidence():
    for label in (
        "실적 발표~현재 주가 반응", "이익 전망 반영", "PEG(주가 수익 성장 비율)",
        "밸류에이션", "가격 모멘텀·과열",
    ):
        assert label in PRI_BREAKDOWN
    for key in (
        "earnings_reaction", "expectation_gap", "earnings_vs_multiple",
        "valuation_burden", "momentum_overheat",
    ):
        assert f'key: "{key}"' in TYPES


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
    assert "기본" in DISCOVERY and "내림" in DISCOVERY and "오름" in DISCOVERY
    for category in ("성장 가속", "매출 YoY 둔화 + 영익 YoY 가속", "턴어라운드", "기타", "전 종목"):
        assert category in DISCOVERY
    assert 'gate: "opportunity"' in filters
    assert 'r.category !== gate' in DISCOVERY
    assert "turnaround: s.turnaround" in page
    for field in ("revenueQoq", "opQoq", "per4q", "forwardPer", "roe", "forwardRoe"):
        assert field in page and field in DISCOVERY
    assert '"revenue_qoq"' in QUERIES and '"op_qoq"' in QUERIES
    assert "ETF 테마 {r.sectorTheme}" not in DISCOVERY
    for label in (
        'label="매출 QoQ"', 'label="영업이익 YoY"', 'label="영업이익 QoQ"',
        'label="올해 PER(예상)"', 'label="내년 F.PER"', 'label="올해 ROE(예상)"', 'label="내년 F.ROE"',
    ):
        assert label in DISCOVERY
    assert "r.turnaround &&" not in DISCOVERY, "등급 칸에는 턴어라운드 문구를 중복 표시하지 않는다"


def test_discovery_defaults_to_current_investment_value_and_freezes_identity_columns():
    page = (ROOT / "dashboard/app/page.tsx").read_text(encoding="utf-8")
    assert 'label="투자 매력도"' in DISCOVERY
    assert "기업 매력도" not in DISCOVERY
    assert "원본" not in DISCOVERY
    assert 'const state = !active ? "기본"' in DISCOVERY
    macro = (ROOT / "dashboard/lib/macroContext.ts").read_text(encoding="utf-8")
    snapshot = (ROOT / "dashboard/lib/macro-daily.json").read_text(encoding="utf-8")
    assert "→ 높은 투자 매력도" in snapshot
    assert "등급 → 최신 분기" in snapshot
    assert "sectorRank.get(a.sector)" in DISCOVERY
    assert "((a.pri ?? Infinity) - (b.pri ?? Infinity))" in DISCOVERY
    for offset in ('left-0', 'left-[112px]', 'left-[156px]'):
        assert offset in DISCOVERY
    assert 'sticky left-[268px]' not in DISCOVERY and 'sticky left-[316px]' not in DISCOVERY
    assert "w-[268px]" in DISCOVERY and "종목 정보" in DISCOVERY
    assert "sectorProcess: sectorInfo.process" in page
    assert '<sup className="ml-1' in DISCOVERY
    assert 'text-[9px]' in DISCOVERY and "{r.sectorProcess}" in DISCOVERY


def test_discovery_uses_verified_us_global_macro_without_blocking_page_render():
    macro = (ROOT / "dashboard/lib/macroContext.ts").read_text(encoding="utf-8")
    snapshot = (ROOT / "dashboard/lib/macro-daily.json").read_text(encoding="utf-8")
    collector = (ROOT / "src/collectors/us_macro_daily.py").read_text(encoding="utf-8")
    filters = (ROOT / "dashboard/lib/discoveryFilters.ts").read_text(encoding="utf-8")
    page = (ROOT / "dashboard/app/page.tsx").read_text(encoding="utf-8")
    for source in ("federalreserve.gov", "bls.gov", "bea.gov", "imf.org"):
        assert source in snapshot or source in collector
    assert "preferredSectors" in macro
    assert "대시보드 렌더는 네트워크 요청을 하지 않는다" in macro
    assert "fetch(" not in macro
    assert "getMacroContext()" in page
    assert "미국·글로벌 매크로" in DISCOVERY
    assert "실적 갱신 자동 계산 흐름" in DISCOVERY
    assert "오늘의 시장 온도" in DISCOVERY and "앞으로 볼 변수" in DISCOVERY
    assert "공식 발표 핵심 요약" in DISCOVERY and "매크로 적합 섹터 TOP" in DISCOVERY
    assert DISCOVERY.count("추천 정렬") == 1
    assert DISCOVERY.index("추천 정렬") < DISCOVERY.index('<table className="w-full min-w-[1840px]')
    assert 'text-[#f7c948]' in DISCOVERY and "text-2xl font-black" in DISCOVERY
    assert "macroContext.summary.current" in DISCOVERY
    assert "macroContext.summary.forward" in DISCOVERY
    assert "cyclePrimarySort(sorts, key)" in DISCOVERY
    assert "return [...sorts, { key, dir: \"asc\" }]" in filters
    assert 'if (sorts[index].dir === "desc") return removeSortRule(sorts, key)' in filters
    assert 'const nextState = !active ? "오름차순"' in DISCOVERY
    assert "removeSortRule(sorts, rule.key)" in DISCOVERY


def test_dashboard_refresh_yields_to_interaction_and_stock_links_do_not_prefetch():
    refresh = (ROOT / "dashboard/components/AutoRefresh.tsx").read_text(encoding="utf-8")
    error_page = (ROOT / "dashboard/app/error.tsx").read_text(encoding="utf-8")
    assert "INTERACTION_GRACE_MS" in refresh
    assert "pendingRef.current" in refresh
    assert "pointerdown" in refresh and "keydown" in refresh and "wheel" in refresh
    assert "클릭/입력 중에는 보류" in refresh
    assert "prefetch={false}" in DISCOVERY
    assert (ROOT / "dashboard/app/error.tsx").exists()
    assert "reset();" in error_page
    assert "window.location.reload();" in error_page


def test_outcome_uses_next_quarter_naver_consensus_and_narrative_sources_are_visible():
    assert "getAllConsensusForQuarter" in QUERIES and "getAllConsensusForQuarter" in OUTCOME
    for field in (
        "nextRevenueYoy", "nextOpYoy", "nextRevenueQoq", "nextOpQoq",
        "projectedAccelRate", "projectedAccelDelta",
    ):
        assert field in SECTOR_EARNINGS and field in OUTCOME
    assert "nextRisingSectors" in OUTCOME
    assert "narrative_verification" in ANALYSIS_VIEW
    assert "지난 4개 분기 경영진 내러티브 검증" in ANALYSIS_SECTION


def test_every_stock_can_request_llm_analysis_and_links_are_exact():
    assert "<AnalysisRequestButton" in STOCK
    assert "자동 분석 대상은 아니지만 위 버튼을 누르면" in STOCK
    assert "(1단계) 잠정실적 발표 초기 분석" in STOCK
    assert "(2단계) 분기/반기/사업보고서 공시 분석" in STOCK
    assert "(3단계) LLM 추가 분석 · 최근 공개자료 반영 완료" in STOCK
    assert "stockeasyStockUrl(code)" in STOCK
    assert "naverDisclosureUrl" not in STOCK
