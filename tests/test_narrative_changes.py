# PRD Ref: §7.1 · traps.md T110
"""LLM 서술용 절대 증감액은 Python이 계산한다.

모델이 원값 두 개를 보고 직접 뺄셈하면 산수가 맞더라도 CALCULATION layer를
침범한다. 이 테스트는 실제 HJ중공업 수치로 YoY/QoQ 비교 분기와 원 단위 차액을
손계산 대조한다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.analysis.analyze import AnalysisInput, build_user_message
from src.finance.narrative_changes import (
    calculate_narrative_changes,
    select_quarter_window,
)


_HJ_QUARTERS = [
    {"fiscal_year": 2025, "fiscal_quarter": 2,
     "revenue": 507_777_000_000, "op": 5_339_000_000, "opm": 1.1},
    {"fiscal_year": 2026, "fiscal_quarter": 1,
     "revenue": 541_400_000_000, "op": 24_581_000_000, "opm": 6.4},
    {"fiscal_year": 2026, "fiscal_quarter": 2,
     "revenue": 729_908_000_000, "op": 64_853_000_000, "opm": 10.6},
]


def test_hj_absolute_changes_match_hand_calculation():
    """손계산:

    YoY 매출 729,908,000,000 - 507,777,000,000 = 222,131,000,000원
    QoQ 매출 729,908,000,000 - 541,400,000,000 = 188,508,000,000원
    YoY OP   64,853,000,000 -   5,339,000,000 =  59,514,000,000원
    QoQ OP   64,853,000,000 -  24,581,000,000 =  40,272,000,000원
    """
    result = calculate_narrative_changes(_HJ_QUARTERS, 2026, 2)

    assert result.yoy.base_period == (2025, 2)
    assert result.yoy.revenue.delta_krw == 222_131_000_000
    assert result.yoy.op.delta_krw == 59_514_000_000
    assert result.qoq.base_period == (2026, 1)
    assert result.qoq.revenue.delta_krw == 188_508_000_000
    assert result.qoq.op.delta_krw == 40_272_000_000
    assert result.yoy.opm_delta_pp == Decimal("9.5")
    assert result.qoq.opm_delta_pp == Decimal("4.2")


def test_qoq_uses_previous_year_q4_across_year_boundary():
    rows = [
        {"fiscal_year": 2025, "fiscal_quarter": 4, "revenue": 100, "op": 10},
        {"fiscal_year": 2026, "fiscal_quarter": 1, "revenue": 130, "op": 15},
    ]
    result = calculate_narrative_changes(rows, 2026, 1)
    assert result.qoq.base_period == (2025, 4)
    assert result.qoq.revenue.delta_krw == 30


def test_missing_exact_base_stays_none_instead_of_using_nearest_quarter():
    rows = [
        {"fiscal_year": 2025, "fiscal_quarter": 1, "revenue": 90, "op": 9},
        {"fiscal_year": 2026, "fiscal_quarter": 2, "revenue": 130, "op": 15},
    ]
    result = calculate_narrative_changes(rows, 2026, 2)
    assert result.yoy.base_period == (2025, 2)
    assert result.yoy.revenue.base_krw is None
    assert result.yoy.revenue.delta_krw is None
    assert result.qoq.revenue.base_krw is None
    assert result.qoq.revenue.delta_krw is None


def test_missing_amount_is_none_not_zero():
    rows = [
        {"fiscal_year": 2025, "fiscal_quarter": 2, "revenue": None, "op": 0},
        {"fiscal_year": 2026, "fiscal_quarter": 2, "revenue": 100, "op": 20},
    ]
    result = calculate_narrative_changes(rows, 2026, 2)
    assert result.yoy.revenue.base_krw is None
    assert result.yoy.revenue.delta_krw is None
    assert result.yoy.op.base_krw == 0
    assert result.yoy.op.delta_krw == 20
    assert result.yoy.op.status_label == "흑전"


def test_duplicate_period_is_rejected_instead_of_silently_choosing_a_row():
    rows = [
        {"fiscal_year": 2026, "fiscal_quarter": 2, "revenue": 100, "op": 10},
        {"fiscal_year": 2026, "fiscal_quarter": 2, "revenue": 200, "op": 20},
    ]
    with pytest.raises(ValueError, match="중복 분기"):
        calculate_narrative_changes(rows, 2026, 2)


def test_requested_quarter_must_exist_instead_of_returning_all_none():
    rows = [
        {"fiscal_year": 2026, "fiscal_quarter": 1, "revenue": 100, "op": 10},
        {"fiscal_year": 2026, "fiscal_quarter": 3, "revenue": 140, "op": 20},
    ]
    with pytest.raises(ValueError, match="대상 분기 2026.2Q가 없다"):
        calculate_narrative_changes(rows, 2026, 2)


def test_quarter_window_ends_at_requested_quarter_not_latest_database_row():
    """과거 분기 replay에 미래 분기가 섞이면 모델은 당시 알 수 없던 데이터를 본다."""
    rows = [
        {"fiscal_year": 2025, "fiscal_quarter": 4},
        {"fiscal_year": 2026, "fiscal_quarter": 1},
        {"fiscal_year": 2026, "fiscal_quarter": 2},
        {"fiscal_year": 2026, "fiscal_quarter": 3},
    ]
    selected = select_quarter_window(rows, 2026, 2, limit=8)
    assert [(r["fiscal_year"], r["fiscal_quarter"]) for r in selected] == [
        (2025, 4), (2026, 1), (2026, 2)
    ]


def test_quarter_window_does_not_treat_true_as_first_quarter():
    """Python에서는 True == 1이므로 타입을 안 보면 False/None 경계처럼 조용히 섞인다."""
    rows = [{"fiscal_year": 2026, "fiscal_quarter": 1}]
    with pytest.raises(ValueError, match="fiscal_quarter는 정수"):
        select_quarter_window(rows, 2026, True)


def test_user_message_supplies_precomputed_hj_changes():
    message = build_user_message(AnalysisInput(
        code="097230",
        name="HJ중공업",
        board="KOSPI",
        fiscal_year=2026,
        fiscal_quarter=2,
        quarters=_HJ_QUARTERS,
    ))

    assert "## 2-1. 결정론적 절대 증감" in message
    assert "YoY (2025.2Q → 2026.2Q)" in message
    assert "매출: 5,077.8억 → 7,299.1억 · 증감 +2,221.3억" in message
    assert "영업이익: 53.4억 → 648.5억 · 증감 +595.1억" in message
    assert "QoQ (2026.1Q → 2026.2Q)" in message
    assert "증감 +1,885.1억" in message
    assert "영업이익률 변화: +4.2%p" in message
    assert "원 단위로 계산한 뒤 억원 단위로 표시 반올림" in message
    assert "표시값끼리 다시 빼지 마라" in message
