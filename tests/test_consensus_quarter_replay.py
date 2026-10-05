# PRD Ref: §5.1 · §9.3 — 2026-10-05 실제 응답 재생
from pathlib import Path

from src.collectors.consensus import parse_wisereport_quarterly


def test_real_quarter_table_not_annual_or_yoy_column():
    html = (Path(__file__).parent / "fixtures/naver_quarterly_005930_20261005.html").read_text(encoding="utf-8")
    rows = parse_wisereport_quarterly(html, "005930")
    assert [(r.fiscal_year,r.fiscal_quarter) for r in rows] == [(2026,3),(2026,4)]
    # 실제 원문 3Q 매출 2,007,657억원, 영익 1,069,435억원. YoY 133.28열은 금액 아님.
    assert rows[0].revenue_est == 200765700000000
    assert rows[0].op_est == 106943500000000
    assert rows[0].eps_est == 13504
    assert parse_wisereport_quarterly(html.replace("억원", "단위 미상"), "005930") == []
    assert parse_wisereport_quarterly(html.replace("2026.09(E)", "2026(E)").replace("2026.12(E)", "2027(E)"), "005930") == []
