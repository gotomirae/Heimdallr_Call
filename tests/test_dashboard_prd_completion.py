# PRD Ref: §9.1 — 운영 대시보드의 잔여 계약
"""DB에 이미 있는 종목 상세 지표가 화면 배선에서 다시 빠지지 않게 한다."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUERIES = (ROOT / "dashboard/lib/queries.ts").read_text(encoding="utf-8")
TYPES = (ROOT / "dashboard/lib/types.ts").read_text(encoding="utf-8")
STOCK = (ROOT / "dashboard/app/stock/[code]/page.tsx").read_text(encoding="utf-8")


def test_query_contract_includes_existing_prd_columns():
    for column in (
        "score_final",
        "score_delta",
        "pctile_in_quarter",
        "ret_3m",
        "ret_6m",
        "ret_12m",
    ):
        assert f'"{column}"' in QUERIES
        assert column in TYPES


def test_stock_detail_renders_prd_evidence_without_inventing_values():
    for label in (
        "분기 내 백분위",
        "EPS YoY",
        "FCF",
        "스코어 Δ",
        "3년 PER 밴드",
        "참고 PEG",
        "섹터 비교",
        "종목별 결과 추적",
        "공시 발췌",
    ):
        assert label in STOCK


def test_integrated_screener_has_the_documented_route():
    route = ROOT / "dashboard/app/screener/page.tsx"
    assert route.exists()
    source = route.read_text(encoding="utf-8")
    assert 'gate", "all"' in source
    assert "redirect" in source


def test_sector_comparison_reads_the_exact_evaluated_quarter_with_paging():
    assert "getScreensForQuarter" in QUERIES
    assert "selectAll<ScreenRow>" in QUERIES
    assert "trailing4qPer" in STOCK
