# PRD Ref: §4.1(D), §5.1(L2″), §5.3 · traps.md T1, T11, T12
"""게이트 통과 종목 정밀 재무의 순수 계산 테스트 (외부 I/O 없음)."""

from __future__ import annotations

import pytest

from src.finance.detail import (
    cumulative_value,
    extract_accounts,
    select_total_shares,
    shares_yoy,
    standalone_value,
    ttm_value,
)


def _row(account_id: str, amount: str, **extra) -> dict:
    row = {
        "sj_div": "CF",
        "account_id": account_id,
        "account_nm": "",
        "account_detail": "-",
        "thstrm_amount": amount,
    }
    row.update(extra)
    return row


def test_extract_accounts_uses_stable_ids_and_current_bs_values():
    rows = [
        _row(
            "ifrs-full_CashFlowsFromUsedInOperatingActivities",
            "600",
            frmtrm_q_amount="400",
        ),
        _row(
            "ifrs-full_CurrentTradeReceivables",
            "120",
            sj_div="BS",
            account_nm="매출채권",
        ),
        _row(
            "ifrs-full_Inventories",
            "80",
            sj_div="BS",
            account_nm="재고자산",
        ),
        _row("ifrs-full_Assets", "1000", sj_div="BS"),
        _row("ifrs-full_Liabilities", "400", sj_div="BS"),
        _row("ifrs-full_Equity", "600", sj_div="BS"),
    ]

    result = extract_accounts(rows)

    assert result.cfo.current_cumulative == 600
    assert result.cfo.prior_same_cumulative == 400
    assert result.receivables == 120
    assert result.inventory == 80
    assert result.assets == 1000
    assert result.liabilities == 400
    assert result.equity == 600


def test_extract_accounts_sums_ppe_and_intangible_capex_without_double_counting():
    rows = [
        _row(
            "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
            "70",
        ),
        _row(
            "ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
            "-30",
        ),
        # 같은 PPE의 회사 사용자 정의 중복 행은 표준 ID가 있으면 선택하지 않는다.
        _row("dart_PurchaseOfPropertyPlantAndEquipment", "999", account_nm="유형자산의 취득"),
    ]

    result = extract_accounts(rows)

    assert result.capex.current_cumulative == 100


def test_extract_accounts_accepts_spaced_custom_current_receivables_name():
    rows = [
        _row(
            "custom_CurrentReceivables",
            "455",
            sj_div="BS",
            account_nm="유동매출채권 등",
        )
    ]
    assert extract_accounts(rows).receivables == 455


def test_interim_ttm_uses_current_plus_prior_annual_minus_prior_same_period():
    # 2026 H1 600 + 2025 FY 1000 - 2025 H1 400 = TTM 1200.
    assert ttm_value(quarter=2, current=600, prior_same=400, prior_annual=1000) == 1200


def test_fourth_quarter_ttm_is_the_current_annual_value():
    assert ttm_value(quarter=4, current=1234, prior_same=None, prior_annual=None) == 1234


def test_ttm_is_missing_when_any_required_interim_value_is_missing():
    assert ttm_value(quarter=2, current=600, prior_same=None, prior_annual=1000) is None
    assert ttm_value(quarter=2, current=600, prior_same=400, prior_annual=None) is None


def test_standalone_is_cumulative_difference_except_q1():
    # 반기 누적 600 - 1분기 누적 250 = 2분기 단독 350.
    assert standalone_value(quarter=2, current=600, previous=250) == 350
    assert standalone_value(quarter=1, current=250, previous=None) == 250
    assert standalone_value(quarter=3, current=900, previous=None) is None


def test_cumulative_value_never_guesses_from_unknown_amount():
    assert cumulative_value(None) is None
    assert cumulative_value("-") is None
    assert cumulative_value("1,234") == 1234


def test_select_total_shares_prefers_sum_row_and_keeps_zero_distinct():
    rows = [
        {"se": "보통주", "istc_totqy": "100"},
        {"se": "우선주", "istc_totqy": "10"},
        {"se": "합계", "istc_totqy": "110"},
        {"se": "비고", "istc_totqy": "-"},
    ]
    assert select_total_shares(rows) == 110
    assert select_total_shares([{"se": "합계", "istc_totqy": "0"}]) == 0


def test_select_total_shares_falls_back_to_largest_valid_total():
    assert select_total_shares(
        [{"se": "보통주", "istc_totqy": "100"}, {"se": "우선주", "istc_totqy": "10"}]
    ) == 100


def test_shares_yoy_requires_positive_prior_denominator():
    assert shares_yoy(105, 100) == pytest.approx(5.0)
    assert shares_yoy(105, 0) is None
    assert shares_yoy(None, 100) is None
