# PRD Ref: §2 검토①②, §6 · traps.md T12
"""P2.5 파생지표 테스트. 전부 외부 I/O 없이 돈다.

손계산 대조는 P2에서 DART로 확인한 실측값을 쓴다.
"""

from __future__ import annotations

import pytest

from src.finance.derive import (
    Derived,
    QuarterPoint,
    delta_pp,
    derive_series,
    growth_pct,
    margin_pct,
    op_status_label,
    op_surprise_label,
    op_surprise_pct,
    profit_growth_pct,
    qindex,
    qkey,
    revenue_surprise_pct,
)


# ═══ 분기 인덱스 ═══
def test_qindex_is_contiguous_across_years():
    assert qindex(2026, 1) - qindex(2025, 4) == 1
    assert qindex(2026, 1) - qindex(2025, 1) == 4
    assert qindex(2026, 1) - qindex(2024, 1) == 8


def test_qkey_roundtrip():
    for year, quarter in [(2025, 1), (2025, 4), (2026, 2)]:
        assert qkey(qindex(year, quarter)) == (year, quarter)


# ═══ T12 — 부호가 바뀌는 구간에서 % 계산 금지 ═══
def test_growth_is_none_when_base_is_negative():
    """적자 −50 → −10을 +80% 성장으로 쓰면 게이트가 통째로 뒤집힌다."""
    assert growth_pct(-10, -50) is None


def test_growth_is_none_when_base_is_zero():
    assert growth_pct(100, 0) is None


def test_growth_is_none_on_turnaround():
    assert growth_pct(30, -20) is None  # 흑자전환


def test_growth_normal_case():
    assert growth_pct(120, 100) == pytest.approx(20.0)
    assert growth_pct(80, 100) == pytest.approx(-20.0)


def test_growth_missing_input():
    assert growth_pct(None, 100) is None
    assert growth_pct(100, None) is None


def test_revenue_growth_allows_drop_to_zero():
    """매출은 음수가 될 수 없다. 100 → 0은 −100%로 의미가 있다."""
    assert growth_pct(0, 100) == pytest.approx(-100.0)


def test_profit_growth_blocks_sign_flip_even_with_positive_base():
    """★ 실제로 있었던 버그(2026-08-13).

    흑자(+100) → 적자(−30)는 분모가 양수라 일반 성장률 함수가 −130%를 내놓는다.
    이건 성장률이 아니라 **적자전환**이다. 실측에서 '적전' 447건 전부에
    %가 붙어 있었고, 그대로 두면 스코어 A2·B축이 그 값을 먹는다.
    """
    assert growth_pct(-30, 100) == pytest.approx(-130.0)  # 일반 함수는 계산한다
    assert profit_growth_pct(-30, 100) is None  # 손익 함수는 막는다
    assert profit_growth_pct(0, 100) is None  # 0도 흑자가 아니다


def test_profit_growth_normal_case():
    assert profit_growth_pct(150, 100) == pytest.approx(50.0)
    assert profit_growth_pct(80, 100) == pytest.approx(-20.0)


def test_profit_growth_blocks_turnaround_and_deeper_loss():
    assert profit_growth_pct(30, -20) is None  # 흑전
    assert profit_growth_pct(-50, -10) is None  # 적자확대


@pytest.mark.parametrize(
    "current,base,expected",
    [
        (30, -20, "흑전"),
        (-30, 20, "적전"),
        (-10, -50, "적자축소"),
        (-50, -10, "적자확대"),
        (0, 20, "적전"),  # 0도 흑자가 아니다
        (20, 0, "흑전"),
        (50, 20, None),  # 정상 구간 — % 계산이 가능하다
    ],
)
def test_op_status_label(current, base, expected):
    assert op_status_label(current, base) == expected


def test_op_status_label_missing():
    assert op_status_label(None, 10) is None
    assert op_status_label(10, None) is None


# ═══ 마진 ═══
def test_margin_allows_negative_numerator():
    """적자 마진은 음수로 나와야 한다. 여기서 None을 주면 적자 심화를 못 본다."""
    assert margin_pct(-20, 100) == pytest.approx(-20.0)


def test_margin_is_none_when_revenue_not_positive():
    assert margin_pct(10, 0) is None
    assert margin_pct(10, -5) is None


def test_delta_pp_works_with_negative_margins():
    assert delta_pp(-3.0, -8.0) == pytest.approx(5.0)


# ═══ TTM — 4개 분기가 전부 있을 때만 ═══
def _series(values: dict[tuple[int, int], tuple]) -> dict:
    return {k: QuarterPoint(revenue=v[0], op=v[1]) for k, v in values.items()}


def test_ttm_requires_four_quarters():
    points = _series(
        {
            (2025, 1): (100, 10),
            (2025, 2): (110, 12),
            (2025, 3): (120, 14),
        }
    )
    out = derive_series(points)
    assert out[(2025, 3)].ttm_revenue is None  # 3개뿐


def test_ttm_computed_when_four_present():
    points = _series(
        {
            (2025, 1): (100, 10),
            (2025, 2): (110, 12),
            (2025, 3): (120, 14),
            (2025, 4): (130, 16),
        }
    )
    out = derive_series(points)
    assert out[(2025, 4)].ttm_revenue == 460
    assert out[(2025, 4)].ttm_op == 52
    assert out[(2025, 4)].ttm_opm == pytest.approx(52 / 460 * 100)


def test_ttm_is_none_when_a_quarter_has_null_value():
    """결측을 0으로 채우면 TTM이 낮게 나와 '가짜 악화'로 보인다."""
    points = {
        (2025, 1): QuarterPoint(revenue=100, op=10),
        (2025, 2): QuarterPoint(revenue=None, op=12),
        (2025, 3): QuarterPoint(revenue=120, op=14),
        (2025, 4): QuarterPoint(revenue=130, op=16),
    }
    out = derive_series(points)
    assert out[(2025, 4)].ttm_revenue is None
    assert out[(2025, 4)].ttm_op == 52  # op는 4개가 다 있으므로 계산된다


def test_ttm_smooths_seasonality():
    """계절성이 강한 시계열에서 TTM OPM 변동이 분기 OPM 변동보다 작아야 한다.

    이것이 QoQ 대신 TTM을 쓰는 이유다(PRD §2 검토②).
    """
    points = _series(
        {
            (2025, 1): (100, 5),
            (2025, 2): (200, 40),
            (2025, 3): (100, 5),
            (2025, 4): (200, 40),
            (2026, 1): (110, 6),
            (2026, 2): (220, 45),
        }
    )
    out = derive_series(points)
    quarterly = [out[k].opm for k in [(2025, 4), (2026, 1), (2026, 2)]]
    ttm = [out[k].ttm_opm for k in [(2025, 4), (2026, 1), (2026, 2)]]
    assert max(quarterly) - min(quarterly) > max(ttm) - min(ttm)


# ═══ 2년 스택 ═══
def test_rev_2y_stack_needs_t_minus_8():
    points = _series({(2024, 1): (100, 10), (2026, 1): (150, 20)})
    out = derive_series(points)
    assert out[(2026, 1)].rev_2y_stack == pytest.approx(50.0)


def test_rev_2y_stack_is_none_without_history():
    points = _series({(2025, 1): (100, 10), (2026, 1): (150, 20)})
    out = derive_series(points)
    assert out[(2026, 1)].rev_2y_stack is None


# ═══ QoQ는 연도 경계를 넘어야 한다 ═══
def test_qoq_crosses_year_boundary():
    points = _series({(2025, 4): (100, 10), (2026, 1): (120, 15)})
    out = derive_series(points)
    assert out[(2026, 1)].revenue_qoq == pytest.approx(20.0)


# ═══ 실측 손계산 — 리노공업(058470) 2025, 매출/영업이익 (원) ═══
#   2025.1Q 매출 78,410,243,553 · 영업 34,937,759,810
#   2025.2Q 매출 112,522,064,123 · 영업 53,444,357,551
#   손계산:
#     2Q OPM       = 53,444,357,551 / 112,522,064,123 = 47.4967803%
#     2Q QoQ 매출   = 34,111,820,570 / 78,410,243,553   = +43.5042911%
#     1Q OPM       = 34,937,759,810 / 78,410,243,553   = 44.5576474%
#     2Q OPM QoQ Δ = 47.4967803 − 44.5576474          = +2.9391329%p
def test_rino_2025_2q_hand_check():
    points = {
        (2025, 1): QuarterPoint(revenue=78_410_243_553, op=34_937_759_810),
        (2025, 2): QuarterPoint(revenue=112_522_064_123, op=53_444_357_551),
    }
    out = derive_series(points)[(2025, 2)]
    assert out.opm == pytest.approx(47.4967803, abs=1e-6)
    assert out.revenue_qoq == pytest.approx(43.5042911, abs=1e-6)
    assert out.opm_qoq_delta == pytest.approx(2.9391329, abs=1e-6)
    assert out.revenue_yoy is None  # 전년 동기 없음
    assert out.ttm_revenue is None  # 4분기 미충족


# ═══ 실측 손계산 — 삼성전자(005930) 2026.1Q vs 2025.1Q (원) ═══
#   2025.1Q 매출 79,140,503,000,000 · 영업 6,685,272,000,000
#   2026.1Q 매출 133,873,444,000,000 · 영업 57,232,797,000,000
#   손계산:
#     매출 YoY = 54,732,941 / 79,140,503        = +69.1592028%
#     2026 1Q OPM = 57,232,797 / 133,873,444    = 42.7514190%
#     2025 1Q OPM =  6,685,272 /  79,140,503    =  8.4473459%
#     OPM YoY Δ = 42.7514190 − 8.4473459        = +34.3040732%p
def test_samsung_2026_1q_hand_check():
    points = {
        (2025, 1): QuarterPoint(revenue=79_140_503_000_000, op=6_685_272_000_000),
        (2026, 1): QuarterPoint(revenue=133_873_444_000_000, op=57_232_797_000_000),
    }
    out = derive_series(points)[(2026, 1)]
    assert out.revenue_yoy == pytest.approx(69.1592028, abs=1e-6)
    assert out.opm == pytest.approx(42.7514190, abs=1e-6)
    assert out.opm_yoy_delta == pytest.approx(34.3040732, abs=1e-6)
    assert out.op_status_label is None  # 둘 다 흑자 — 정상 구간


def test_label_and_percent_are_mutually_exclusive():
    """라벨이 붙은 행에는 op_yoy가 절대 있으면 안 된다 (T12).

    이 불변식이 깨지면 부호 전환 구간의 % 가 스코어로 흘러든다.
    """
    cases = [
        ((2025, 1), QuarterPoint(revenue=100, op=100)),
        ((2026, 1), QuarterPoint(revenue=100, op=-30)),  # 적전
    ]
    out = derive_series(dict(cases))[(2026, 1)]
    assert out.op_status_label == "적전"
    assert out.op_yoy is None


def test_derived_defaults_are_all_none():
    d = Derived()
    assert all(v is None for v in d.as_dict().values())


# ═══ 컨센서스 서프라이즈 (스코어 C축 입력) ═══
def test_revenue_surprise_basic():
    """삼성전자 2026.2Q 실측: 컨센 1,738,644억 · 실제 1,714,995억 → −1.36%"""
    assert revenue_surprise_pct(1_714_995e8, 1_738_644e8) == pytest.approx(-1.360, abs=1e-3)


def test_op_surprise_basic():
    """삼성전자 2026.2Q 실측: 컨센 850,494억 · 실제 894,924억 → +5.22%"""
    assert op_surprise_pct(894_924e8, 850_494e8) == pytest.approx(5.224, abs=1e-3)


def test_op_surprise_none_when_loss_expected_but_profit_came():
    """★ 적자 예상(−100) → 흑자(+50)에서 %를 내면 −150%가 된다.

    최고의 서프라이즈가 최악의 점수로 뒤집힌다 — `_tiered`가 기준 미달로 읽어 0점.
    에러는 없다. 그래서 % 대신 None + 라벨이다.
    """
    assert op_surprise_pct(50.0, -100.0) is None
    assert op_surprise_label(50.0, -100.0) == "흑전 서프라이즈"


def test_op_surprise_none_when_profit_expected_but_loss_came():
    """반대 방향은 분모가 양수라 그냥 두면 통과해버린다 — 분자도 막는다."""
    assert op_surprise_pct(-30.0, 100.0) is None
    assert op_surprise_label(-30.0, 100.0) == "적자 쇼크"


def test_op_surprise_label_none_in_normal_range():
    """둘 다 양수면 라벨이 아니라 %로 판정한다."""
    assert op_surprise_label(120.0, 100.0) is None
    assert op_surprise_pct(120.0, 100.0) == pytest.approx(20.0)


def test_op_surprise_both_negative():
    assert op_surprise_pct(-50.0, -100.0) is None
    assert op_surprise_label(-50.0, -100.0) == "적자 예상 부합"


def test_surprise_none_when_estimate_missing():
    assert op_surprise_pct(100.0, None) is None
    assert revenue_surprise_pct(100.0, None) is None
    assert op_surprise_label(100.0, None) is None


def test_revenue_surprise_allows_negative_result():
    """매출이 추정치를 밑도는 것은 정상적인 음수 서프라이즈다 — 막지 않는다."""
    assert revenue_surprise_pct(80.0, 100.0) == pytest.approx(-20.0)
