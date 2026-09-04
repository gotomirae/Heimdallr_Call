# PRD Ref: §4 전체 · 부록 A · ADR 2, 5
"""P3 스크리너 테스트. 전부 외부 I/O 없이 돈다.

손계산은 검산할 수 있도록 계산 과정을 주석에 남긴다.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.config import constants as C
from src.config.constants import (
    SCORE_DENOM_FINAL_NO_CONSENSUS,
    SCORE_DENOM_FINAL_WITH_CONSENSUS,
    SCORE_DENOM_FLASH_NO_CONSENSUS,
    SCORE_DENOM_FLASH_WITH_CONSENSUS,
)
from src.screener.gate import GateInput, evaluate_gate
from src.screener.matrix import CIRCLE, CROSS, DOT, STAR, TRIANGLE, classify
from src.screener.pri import PriInput, compute_pri
from src.screener.run import _qi as _qi_helper
from src.screener.run import (
    build_inputs,
    code_index_is_future,
    last_reportable_index,
    percentile_by_period,
    score_stage_fields,
    target_index,
)
from src.screener.score import ScoreInput, active_score, compute_score, has_consensus


def _healthy_gate(**overrides) -> GateInput:
    base = dict(
        revenue_t=1200.0, revenue_t1=1000.0, revenue_t4=900.0,
        op_t=200.0, op_t1=150.0, op_t4=100.0,
        revenue_yoy_t=33.3, revenue_yoy_t1=11.1,
        # 영업이익 YoY도 가속해야 통과한다 (50.0 → 100.0)
        op_yoy_t=100.0, op_yoy_t1=50.0,
        # G4 — OPM도 전년보다 올라야 통과한다 (2026-08-22 추가)
        opm_yoy_delta=3.0,
        revenue_last4=(1000.0, 950.0, 920.0, 900.0),
    )
    base.update(overrides)
    return GateInput(**base)


def test_final_input_wires_accounting_quality_without_guessing_missing_values():
    """확정행만 D축을 열고, 운전자본 YoY는 합계의 전년동기 증감률로 계산한다.

    매출채권+재고 120+80=200, 전년 100+60=160 → +25%.
    """
    index = _qi_helper(2026, 2)
    series = {
        index: {
            "fiscal_year": 2026, "fiscal_quarter": 2, "is_estimate": False,
            "revenue": 1_200.0, "op": 180.0, "revenue_yoy": 30.0, "op_yoy": 50.0,
            "opm_yoy_delta": 2.0, "ttm_revenue": 4_000.0, "ttm_op": 500.0,
            "ttm_cfo": 350.0, "shares_yoy": 1.5, "receivables": 120.0, "inventory": 80.0,
        },
        index - 1: {
            "revenue": 1_000.0, "op": 150.0, "revenue_yoy": 20.0, "op_yoy": 30.0,
            "ttm_revenue": 3_800.0, "ttm_op": 450.0,
        },
        index - 4: {
            "revenue": 900.0, "op": 120.0, "receivables": 100.0, "inventory": 60.0,
        },
        index - 5: {"revenue": 850.0, "op": 110.0},
    }
    _, score = build_inputs(
        series,
        {"is_excluded": False},
        index,
        None,
        price={"avg_value_20d": 2_000_000_000},
    )
    assert score.is_final is True
    assert score.ttm_cfo == 350.0
    assert score.ttm_op == 500.0
    assert score.shares_yoy == 1.5
    assert score.receivables_inventory_yoy == pytest.approx(25.0)
    assert score.avg_value_20d == 2_000_000_000


def test_flash_input_does_not_open_d_axis_even_if_price_exists():
    index = _qi_helper(2026, 2)
    series = {
        index: {
            "fiscal_year": 2026, "fiscal_quarter": 2, "is_estimate": True,
            "revenue": 1_200.0, "op": 180.0,
        }
    }
    _, score = build_inputs(
        series,
        {"is_excluded": False},
        index,
        None,
        price={"avg_value_20d": 2_000_000_000},
    )
    assert score.is_final is False


def test_score_stage_preserves_flash_and_calculates_confirmed_delta():
    assert score_stage_fields(82.0, False, {}) == {
        "score_flash": 82.0,
        "score_final": None,
        "score_delta": None,
    }
    assert score_stage_fields(
        75.0,
        True,
        {"score_flash": 82.0, "gate_detail": {"score_stage": "flash"}},
    ) == {
        "score_flash": 82.0,
        "score_final": 75.0,
        "score_delta": -7.0,
    }


def test_active_score_prefers_confirmed_and_falls_back_to_flash():
    assert active_score({"score_flash": 82.0, "score_final": 75.0}) == 75.0
    assert active_score({"score_flash": 82.0, "score_final": None}) == 82.0
    assert active_score({"score_flash": None, "score_final": None}) is None


def test_legacy_flash_is_not_used_as_a_fake_preliminary_baseline():
    """구버전은 확정행도 score_flash에 썼다. 표식 없는 값으로 delta를 만들면 거짓이다."""
    assert score_stage_fields(75.0, True, {"score_flash": 82.0}) == {
        "score_flash": None,
        "score_final": 75.0,
        "score_delta": None,
    }


def test_percentile_is_period_local_tie_aware_and_missing_last():
    rows = [
        ("A", 2026, 2, 90.0),
        ("B", 2026, 2, 70.0),
        ("C", 2026, 2, 70.0),
        ("D", 2026, 2, None),
        ("E", 2026, 1, 10.0),
    ]
    ranks = percentile_by_period(rows)
    assert ranks[("A", 2026, 2)] == pytest.approx(100.0)
    # 동점 두 종목은 같은 상한 순위: (낮은 값 0 + 동점 2) / 3.
    assert ranks[("B", 2026, 2)] == pytest.approx(200 / 3)
    assert ranks[("C", 2026, 2)] == pytest.approx(200 / 3)
    assert ranks[("D", 2026, 2)] is None
    assert ranks[("E", 2026, 1)] == pytest.approx(100.0)


# ═══════════════════════════════════════════════════════════════════
# 게이트 5케이스 (phases.md P3 검증)
# ═══════════════════════════════════════════════════════════════════
def test_gate_case1_pass():
    r = evaluate_gate(_healthy_gate())
    assert (r.g0, r.g1, r.g2, r.g3, r.g4, r.passed) == (True, True, True, True, True, True)


def test_gate_case2_revenue_not_accelerating():
    """매출 YoY가 전분기보다 낮으면 G1 탈락."""
    r = evaluate_gate(_healthy_gate(revenue_yoy_t=8.0, revenue_yoy_t1=11.1))
    assert r.g1 is False
    assert r.passed is False


def test_gate_case2b_revenue_accelerating_but_negative():
    """가속해도 YoY가 음수면 탈락 (−20% → −5%는 '성장'이 아니다)."""
    r = evaluate_gate(_healthy_gate(revenue_yoy_t=-5.0, revenue_yoy_t1=-20.0))
    assert r.g1 is False


def test_gate_case3_operating_loss():
    """적자는 탈락. 판정 불가(None)가 아니다."""
    r = evaluate_gate(_healthy_gate(op_t=-50.0, op_yoy_t=None, op_status_label="적자축소"))
    assert r.g2 is False
    assert r.passed is False
    assert r.turnaround is True  # 대시보드에는 남기되 텔레그램 발송은 하지 않는다


def test_gate_case4_missing_data_is_none_not_false():
    """★ 데이터 결측은 '탈락'이 아니라 '판정 불가'다."""
    r = evaluate_gate(_healthy_gate(revenue_t4=None))
    assert r.g0 is False
    assert r.passed is None
    assert "revenue_t4" in r.detail["missing"]


def test_gate_case5_sector_excluded():
    r = evaluate_gate(_healthy_gate(is_excluded=True, exclude_reason="bank"))
    assert r.g3 is False
    assert r.passed is False
    assert r.detail["exclude_reason"] == "bank"


def test_gate_young_listing_excluded():
    r = evaluate_gate(_healthy_gate(quarters_since_listing=3))
    assert r.g3 is False


def test_gate_turnaround_counts_as_g2_pass():
    """흑전은 op_yoy가 None이지만 이익이 늘어난 것은 명백하다 (T25)."""
    r = evaluate_gate(_healthy_gate(op_t=200.0, op_yoy_t=None, op_status_label="흑전"))
    assert r.g2 is True
    assert r.turnaround is True


def test_gate_op_growth_must_accelerate():
    """★ 실적 가속의 정의 — 영업이익도 **가속**해야 한다.

    영업이익이 흑자이고 +30% 성장 중이어도, 전분기가 +80%였다면 이익 성장은
    둔화되고 있는 것이다. 매출(G1)과 같은 잣대를 영업이익에도 적용한다.
    """
    r = evaluate_gate(_healthy_gate(op_yoy_t=30.0, op_yoy_t1=80.0))
    assert r.g2 is False
    assert r.passed is False


def test_gate_op_accelerating_but_negative_fails():
    """가속해도 영업이익 YoY가 음수면 탈락 — G1과 대칭이다.

    −30% → −10%는 '덜 나빠진 것'이지 성장이 아니다.
    """
    r = evaluate_gate(_healthy_gate(op_yoy_t=-10.0, op_yoy_t1=-30.0))
    assert r.g2 is False


def test_gate_op_delta_recorded():
    """가속폭을 detail에 남긴다 — 화면에서 '얼마나' 가속했는지 보여준다."""
    r = evaluate_gate(_healthy_gate(op_yoy_t=100.0, op_yoy_t1=50.0))
    assert r.g2 is True
    assert r.detail["op_yoy_delta_pp"] == 50.0


def test_gate_op_undecidable_when_prev_growth_missing():
    """★ 전분기 op_yoy가 없으면 **판정 불가(None)**다. 탈락이 아니다.

    전분기가 흑전/적전이면 op_yoy가 애초에 None으로 저장된다(T25).
    False로 뭉개면 그 종목들이 에러 없이 통째로 사라진다 — 실측 36종목.
    """
    r = evaluate_gate(_healthy_gate(op_yoy_t=100.0, op_yoy_t1=None))
    assert r.g2 is None
    assert r.passed is None


def test_gate_g4_opm_must_rise():
    """★ G4 — 매출·이익이 둘 다 가속해도 **OPM이 내려갔으면 탈락**이다.

    2026-08-22 추가. 매출과 이익이 같이 빨라져도 이익률이 전년보다 낮아졌다면
    '싸게 많이 판 것'이다. G1·G2는 속도를, G4는 질을 본다.
    """
    r = evaluate_gate(_healthy_gate(opm_yoy_delta=-0.5))
    assert r.g1 is True and r.g2 is True  # 속도는 멀쩡하다
    assert r.g4 is False
    assert r.passed is False


def test_gate_g4_is_direction_not_size():
    """★ 게이트는 **방향만** 묻는다 — +0.1%p도 상승이다.

    크기를 요구하면(예: +1.0%p) '조금 오른' 종목이 통째로 탈락한다. 얼마나
    올랐는지는 스코어 B1이 점수로 잰다 — 같은 것을 두 번 재지 않는다.
    """
    assert C.G4_OPM_DELTA_MIN_PP == 0.0
    assert evaluate_gate(_healthy_gate(opm_yoy_delta=0.1)).g4 is True
    # 정확히 0.0은 '상승'이 아니다 (초과 조건)
    assert evaluate_gate(_healthy_gate(opm_yoy_delta=0.0)).g4 is False


def test_gate_g4_missing_is_none_not_false():
    """★ OPM 결측은 **판정 불가(None)**다. 탈락이 아니다.

    적자 구간 등에서 opm_yoy_delta가 비는 종목을 False로 뭉개면
    데이터 결측이 판정으로 둔갑해 그 종목들이 조용히 사라진다 — G1·G2와 같은 규칙이다.
    """
    r = evaluate_gate(_healthy_gate(opm_yoy_delta=None))
    assert r.g4 is None
    assert r.passed is None  # False가 없고 None이 있으면 판정 불가


def test_gate_g4_delta_recorded():
    """상승폭을 detail에 남긴다 — 화면에서 '얼마나' 올랐는지 보여준다."""
    r = evaluate_gate(_healthy_gate(opm_yoy_delta=2.5))
    assert r.detail["opm_yoy_delta_pp"] == 2.5


def test_gate_undecidable_when_growth_missing():
    r = evaluate_gate(_healthy_gate(revenue_yoy_t=None))
    assert r.g1 is None
    assert r.passed is None  # False가 없고 None이 있으면 판정 불가


def test_gate_false_beats_none():
    """False가 하나라도 있으면 '탈락'이 '판정 불가'보다 우선한다."""
    r = evaluate_gate(_healthy_gate(revenue_yoy_t=None, is_excluded=True))
    assert r.g1 is None and r.g3 is False
    assert r.passed is False


# ═══════════════════════════════════════════════════════════════════
# 기저효과 경고 (PRD §4.1)
# ═══════════════════════════════════════════════════════════════════
def test_base_effect_warning_when_no_condition_met():
    r = evaluate_gate(
        _healthy_gate(
            revenue_t=1200.0,
            revenue_last4=(1500.0, 1400.0, 1300.0, 1250.0),  # 분기 최고 아님
            rev_2y_t=5.0, rev_2y_t1=10.0,  # 2년 스택 감속
            ttm_revenue_t=100.0, ttm_revenue_history=(120.0, 110.0),  # TTM 최고 아님
        )
    )
    assert r.base_effect_warning is True
    assert r.base_effect_measurable is True


def test_no_warning_when_any_condition_met():
    r = evaluate_gate(
        _healthy_gate(
            revenue_t=1600.0,
            revenue_last4=(1500.0, 1400.0, 1300.0, 1250.0),  # 분기 최고 경신 ✓
            rev_2y_t=5.0, rev_2y_t1=10.0,
            ttm_revenue_t=100.0, ttm_revenue_history=(120.0, 110.0),
        )
    )
    assert r.base_effect_warning is False


def test_no_warning_when_nothing_measurable():
    """★ 전부 판정 불가면 경고를 붙이지 않는다.

    '데이터가 없다'를 '기저효과다'로 바꿔치기하면 안 된다.
    현재(2026-08) rev_2y_stack이 11.4%뿐이라 실제로 자주 발생한다.
    """
    r = evaluate_gate(_healthy_gate(revenue_last4=()))
    assert r.base_effect_warning is False
    assert r.base_effect_measurable is False


# ═══════════════════════════════════════════════════════════════════
# ★ 정규화 규칙 (PRD §4.2 · ADR 2) — 이 프로젝트에서 가장 중요한 계산
# ═══════════════════════════════════════════════════════════════════
def test_consensus_requires_two_estimates():
    assert has_consensus(None) is False
    assert has_consensus(1) is False  # 1개는 컨센서스가 아니다
    assert has_consensus(2) is True


def _score_base(**overrides) -> ScoreInput:
    base = dict(
        revenue_yoy_t=30.0, revenue_yoy_t1=10.0,  # Δ = 20%p → a1 만점 10
        op_yoy_t=60.0, op_yoy_t1=20.0,  # Δ = 40%p → a2 만점 15
        # ★ a3는 2026-08-22부터 TTM **영업이익**을 본다 (TTM 매출이 아니다)
        ttm_op_t=110.0, ttm_op_t1=100.0,  # +10% ≥ 5% → a3 만점 4
        g1_t=True, g1_t1=True,  # a4 6점
        opm_yoy_delta=5.0,  # b1 만점 14
        ttm_opm_delta=2.0,  # b2 만점 7
        sector_opm_percentile=20.0,  # b4 5점 (상위 25% 이내)
    )
    base.update(overrides)
    return ScoreInput(**base)


def test_denominator_flash_with_consensus_is_82():
    r = compute_score(_score_base(n_estimates=3, op_surprise_pct=25.0, revenue_surprise_pct=12.0))
    assert r.denominator == SCORE_DENOM_FLASH_WITH_CONSENSUS == 82
    assert r.excluded_axes == ("D",)
    assert r.has_consensus is True


def test_denominator_flash_without_consensus_is_67():
    r = compute_score(_score_base(n_estimates=None))
    assert r.denominator == SCORE_DENOM_FLASH_NO_CONSENSUS == 67
    assert set(r.excluded_axes) == {"C", "D"}
    assert r.has_consensus is False


def test_denominator_final_with_consensus_is_100():
    r = compute_score(
        _score_base(
            n_estimates=4, op_surprise_pct=25.0, revenue_surprise_pct=12.0,
            is_final=True, ttm_cfo=100.0, ttm_op=150.0, shares_yoy=1.0,
            receivables_inventory_yoy=5.0, avg_value_20d=2_000_000_000,
        )
    )
    assert r.denominator == SCORE_DENOM_FINAL_WITH_CONSENSUS == 100
    assert r.excluded_axes == ()


def test_denominator_final_without_consensus_is_85():
    r = compute_score(
        _score_base(
            n_estimates=1,  # 1개는 컨센서스가 아니다
            is_final=True, ttm_cfo=100.0, ttm_op=150.0, shares_yoy=1.0,
            receivables_inventory_yoy=5.0, avg_value_20d=2_000_000_000,
        )
    )
    assert r.denominator == SCORE_DENOM_FINAL_NO_CONSENSUS == 85
    assert r.excluded_axes == ("C",)


def test_no_consensus_is_not_structurally_penalized():
    """★★ ADR 2의 핵심.

    A·B가 동일한 두 종목에서, 컨센서스가 없는 쪽이 **구조적으로 불리하면 안 된다.**
    C축을 0점 처리하면 67점 만점을 82점 만점으로 나눠 15점을 손해 본다.
    """
    without = compute_score(_score_base(n_estimates=None))
    # 컨센서스는 있지만 서프라이즈가 0인 종목 (C축 0점)
    with_zero_surprise = compute_score(
        _score_base(n_estimates=5, op_surprise_pct=0.0, revenue_surprise_pct=0.0)
    )
    assert without.score_norm == pytest.approx(100.0)
    assert with_zero_surprise.score_norm < without.score_norm

    # 0점 처리했다면 이렇게 됐을 값 — 실제로는 이러면 안 된다
    penalized = without.raw_sum / SCORE_DENOM_FLASH_WITH_CONSENSUS * 100
    assert penalized < without.score_norm
    assert without.score_norm - penalized == pytest.approx(18.29, abs=0.01)


# ═══════════════════════════════════════════════════════════════════
# 스코어 손계산 3건 (검산 가능하도록 과정을 남긴다)
# ═══════════════════════════════════════════════════════════════════
def test_hand_check_1_partial_axis_and_silent_penalty():
    """손계산 ①  A축 전부 + B축 일부만 측정 — **조용한 감점**을 드러낸다

    a1: Δ = 25.0 − 15.0 = 10.0%p · 10/20 × 10          = 5.0
    a2: Δ = 30.0 − 10.0 = 20.0%p · 20/40 × 15          = 7.5
    a3: TTM 영업익 105 > 100 → 2 · 증가율 5.0% ≥ 5 → +2 = 4.0
    a4: g1_t=True, g1_t1=False                         = 0.0
    A = 5 + 7.5 + 4 + 0                                = 16.5

    b3: op_yoy 30 > rev_yoy 25 → 6                     = 6.0
    b1·b2·b4는 입력이 없어 미측정 → **0점 처리**        (b1 14 + b2 7 + b4 5 = 26점 손실)
    B = 6.0  ← 축이 '측정됨'이므로 32점이 분모에 그대로 들어간다

    분모 = A(35) + B(32) = 67 · C·D는 축 전체 미측정이라 제외
    score_norm = (16.5 + 6) / 67 × 100 = 33.5820895...

    ★ 정규화 단위는 '축'이므로 축 안의 결측은 분모에서 빠지지 않는다.
      그래서 missing_items에 기록해 화면에 드러내야 한다.
    """
    r = compute_score(
        ScoreInput(
            revenue_yoy_t=25.0, revenue_yoy_t1=15.0,
            op_yoy_t=30.0, op_yoy_t1=10.0,
            ttm_op_t=105.0, ttm_op_t1=100.0,
            g1_t=True, g1_t1=False,
        )
    )
    assert r.raw["a1"] == pytest.approx(5.0)
    assert r.raw["a2"] == pytest.approx(7.5)
    assert r.raw["a3"] == pytest.approx(4.0)
    assert r.raw["a4"] == pytest.approx(0.0)
    assert r.score_a == pytest.approx(16.5)
    assert r.score_b == pytest.approx(6.0)
    assert r.denominator == 67
    assert r.score_norm == pytest.approx(33.5820895, abs=1e-6)
    # 조용한 감점이 기록됐는가
    assert r.missing_items == {"b1": 14, "b2": 7, "b4": 5}
    assert r.missing_item_points == 26


def test_hand_check_2_b_axis_interpolation():
    """손계산 ②  B축 선형 보간

    b1: OPM YoY +2.0%p — 구간 (1,3,5)→(5,10,14)
        1%p에서 5점, 3%p에서 10점 → 2%p = 5 + (2−1)/(3−1) × (10−5) = 7.5
    b2: TTM OPM +1.0%p — 구간 (0.5,2)→(3,7)
        0.5%p에서 3점, 2%p에서 7점 → 1%p = 3 + (1−0.5)/(2−0.5) × (7−3) = 4.3333333
    b3: op_yoy 40 > rev_yoy 20                     = 6.0
    b4: 업종 백분위 40% → 상위 50% 이내            = 3.0
    B = 7.5 + 4.3333333 + 6 + 3 = 20.8333333
    """
    r = compute_score(
        ScoreInput(
            revenue_yoy_t=20.0, op_yoy_t=40.0,
            opm_yoy_delta=2.0, ttm_opm_delta=1.0,
            sector_opm_percentile=40.0,
        )
    )
    assert r.raw["b1"] == pytest.approx(7.5)
    assert r.raw["b2"] == pytest.approx(4.3333333, abs=1e-6)
    assert r.raw["b3"] == pytest.approx(6.0)
    assert r.raw["b4"] == pytest.approx(3.0)
    assert r.score_b == pytest.approx(20.8333333, abs=1e-6)


def test_hand_check_3_full_axes_with_d():
    """손계산 ③  확정 시점 · 컨센서스 있음 (분모 100)

    A = 10 + 15 + 4 + 6                            = 35.0 (전 항목 만점)
    B = 14 + 7 + 6 + 5                             = 32.0 (전 항목 만점)
    c1: 영업이익 서프 +25% ≥ 20 → 9
    c2: 매출 서프 +12% ≥ 10 → 6                     C = 15.0
    d1: TTM CFO 100 > 0 → 3 · 100/150 = 0.667 ≥ 0.5 → +3   = 6.0
    d2: 주식수 YoY 1.0% < 2% → 4
    d3: (매출채권+재고) YoY 5% < 매출 YoY 30% → 4
    d4: 거래대금 20억 ≥ 10억 → 4                    D = 18.0
    raw_sum = 35 + 32 + 15 + 18 = 100 · 분모 100 → 100.0점
    """
    r = compute_score(
        _score_base(
            n_estimates=4, op_surprise_pct=25.0, revenue_surprise_pct=12.0,
            is_final=True, ttm_cfo=100.0, ttm_op=150.0, shares_yoy=1.0,
            receivables_inventory_yoy=5.0, avg_value_20d=2_000_000_000,
        )
    )
    assert r.score_a == pytest.approx(35.0)
    assert r.score_b == pytest.approx(32.0)
    assert r.score_c == pytest.approx(15.0)
    assert r.score_d == pytest.approx(18.0)
    assert r.score_norm == pytest.approx(100.0)


def test_raw_values_are_all_returned_for_later_reweighting():
    """raw_a1~raw_d4를 전부 저장해야 나중에 가중치를 바꿔 재계산할 수 있다(검토⑥)."""
    r = compute_score(_score_base(n_estimates=3, op_surprise_pct=5.0, revenue_surprise_pct=3.0))
    row = r.as_db_row()
    for key in ("a1", "a2", "a3", "a4", "b1", "b2", "b3", "b4", "c1", "c2", "d1", "d2", "d3", "d4"):
        assert f"raw_{key}" in row
    assert row["has_consensus"] is True


def test_a2_is_none_on_sign_flip():
    """부호 전환 구간에서 op_yoy가 None이면 a2도 None이어야 한다 (T25)."""
    r = compute_score(_score_base(op_yoy_t=None))
    assert r.raw["a2"] is None


# ═══════════════════════════════════════════════════════════════════
# PRI 손계산 1건 + 정규화
# ═══════════════════════════════════════════════════════════════════
def test_pri_hand_check():
    """손계산: 5축을 모두 측정한다.

    p1: 신고가 대비 -15% → 12.5/25
    p2: 발표일 대비 +15% → 12.5/25
    p3: 9개 분기 PER 평균 대비 +25% → 10/20
    p4: 외국인 순매수 비율 0% → 5/10
    p5: RSI 45 → 10/20
    raw_sum 50 / 분모 100 → PRI 50
    """
    r = compute_pri(
        PriInput(
            high_52w_drawdown_pct=-15.0,
            announcement_return_pct=15.0,
            per_vs_9q_avg_pct=25.0,
            foreign_net_ratio_5d_pct=0.0,
            rsi_14=45.0,
        )
    )
    assert r.parts == pytest.approx({"p1": 12.5, "p2": 12.5, "p3": 10, "p4": 5, "p5": 10})
    assert r.denominator == 100
    assert r.pri == pytest.approx(50.0)


def test_pri_p1_lower_bound():
    r = compute_pri(PriInput(high_52w_drawdown_pct=-30.0))
    assert r.parts["p1"] == 0.0


def test_pri_p1_at_high_is_full_score():
    r = compute_pri(PriInput(high_52w_drawdown_pct=0.0))
    assert r.parts["p1"] == pytest.approx(25.0)


def test_pri_p5_uses_45_as_midpoint():
    assert compute_pri(PriInput(rsi_14=30)).parts["p5"] == 0
    assert compute_pri(PriInput(rsi_14=45)).parts["p5"] == 10
    assert compute_pri(PriInput(rsi_14=70)).parts["p5"] == 20


def test_pri_is_none_when_nothing_measured():
    r = compute_pri(PriInput())
    assert r.pri is None
    assert r.denominator == 0


def test_pri_none_when_only_one_25_point_part_is_measured():
    r = compute_pri(PriInput(high_52w_drawdown_pct=-10.0))
    assert r.parts["p1"] is not None
    assert r.denominator == 25
    assert r.pri is None


def test_pri_measured_when_two_25_point_parts_are_combined():
    r = compute_pri(
        PriInput(high_52w_drawdown_pct=-30.0, announcement_return_pct=0.0)
    )
    assert r.denominator == 50
    assert r.pri is not None


# ═══════════════════════════════════════════════════════════════════
# 매트릭스 9칸 전부
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "score,pri,expected",
    [
        (80, 30, STAR),      # 고스코어 · 미반영
        (80, 50, CIRCLE),    # 고스코어 · 부분반영
        (80, 70, TRIANGLE),  # 고스코어 · 선반영 → 조정 시 담을 종목
        (65, 30, CIRCLE),    # 중스코어 · 미반영
        (65, 50, DOT),
        (65, 70, DOT),
        (50, 30, DOT),
        (50, 50, DOT),
        (50, 70, CROSS),     # 저스코어 · 선반영 → 제외
    ],
)
def test_matrix_all_nine_cells(score, pri, expected):
    assert classify(score, pri).grade == expected


def test_matrix_boundaries_are_inclusive_as_specified():
    assert classify(75, 39.9).grade == STAR  # 스코어 ≥ 75
    assert classify(74.9, 39.9).grade == CIRCLE
    assert classify(80, 40).grade == CIRCLE  # PRI < 40이어야 ★
    assert classify(80, 65).grade == CIRCLE  # PRI ≤ 65까지 ○
    assert classify(80, 65.1).grade == TRIANGLE


def test_notify_only_star_and_circle():
    assert classify(80, 30).notify is True
    assert classify(80, 50).notify is True
    assert classify(80, 70).notify is False  # △는 대시보드에만
    assert classify(50, 50).notify is False


@pytest.mark.parametrize("initial,demoted", [(STAR, CIRCLE), (CIRCLE, DOT)])
def test_base_effect_demotes_one_step(initial, demoted):
    score, pri = {STAR: (80, 30), CIRCLE: (80, 50)}[initial]
    r = classify(score, pri, base_effect_warning=True)
    assert r.base_grade == initial
    assert r.grade == demoted
    assert r.demoted is True


def test_demoted_star_is_still_notified():
    """★→○ 강등이어도 ○는 발송 대상이다."""
    assert classify(80, 30, base_effect_warning=True).notify is True


def test_demoted_circle_is_not_notified():
    assert classify(80, 50, base_effect_warning=True).notify is False


def test_triangle_is_not_demoted():
    r = classify(80, 70, base_effect_warning=True)
    assert r.grade == TRIANGLE and r.demoted is False


def test_no_grade_when_gate_failed():
    r = classify(90, 10, gate_passed=False)
    assert r.grade is None and r.reason == "gate_failed"


def test_no_grade_when_gate_undecidable():
    r = classify(90, 10, gate_passed=None)
    assert r.grade is None and r.reason == "gate_undecidable"


def test_no_grade_without_pri():
    """★ PRI를 모르면 등급을 매기지 않는다.

    스코어만으로 ★를 주면 "이미 다 오른 종목"을 최우선으로 밀어 올릴 수 있다.
    """
    r = classify(90, None)
    assert r.grade is None and r.reason == "insufficient_data"


# ═══════════════════════════════════════════════════════════════════
# 평가 분기 선택 (T36)
# ═══════════════════════════════════════════════════════════════════
def _series(*indices) -> dict:
    return {i: {"revenue": 100.0} for i in indices}


def test_target_index_picks_latest_reported():
    """종목마다 발표 시기가 다르므로 각자의 최신 분기로 평가한다."""
    q = _qi_helper
    series = _series(q(2026, 1), q(2026, 2))
    assert target_index(series, fixed=None, ceiling=q(2026, 2)) == q(2026, 2)


def test_target_index_ignores_future_quarter():
    """아직 끝나지 않은 분기는 고르지 않는다.

    실측: 한스바이오메드(042520)가 2026-08 시점에 2026.3Q 행을 갖고 있다.
    그냥 최신을 고르면 존재할 수 없는 분기로 평가된다.
    """
    q = _qi_helper
    series = _series(q(2025, 4), q(2026, 3))
    assert target_index(series, fixed=None, ceiling=q(2026, 2)) == q(2025, 4)


def test_target_index_skips_rows_without_revenue():
    """매출이 없는 빈 껍데기 행은 '발표'로 치지 않는다."""
    q = _qi_helper
    series = {q(2026, 1): {"revenue": 100.0}, q(2026, 2): {"revenue": None}}
    assert target_index(series, fixed=None, ceiling=q(2026, 2)) == q(2026, 1)


def test_target_index_honours_fixed_quarter():
    """--quarter 2026.1을 주면 그 분기를 그대로 쓴다."""
    q = _qi_helper
    fixed = q(2026, 1)
    assert target_index(_series(q(2026, 2)), fixed=fixed, ceiling=q(2026, 2)) == fixed


def test_target_index_none_when_nothing_reported():
    assert target_index({}, fixed=None, ceiling=_qi_helper(2026, 2)) is None


def test_last_reportable_index_excludes_current_quarter():
    """2026-08-15는 3분기 중간 — 끝난 마지막 분기는 2026.2Q다."""
    assert last_reportable_index(date(2026, 8, 15)) == _qi_helper(2026, 2)
    assert last_reportable_index(date(2026, 1, 2)) == _qi_helper(2025, 4)


# ═══════════════════════════════════════════════════════════════════
# C축 — 부호 전환 서프라이즈 (컨센서스 배선)
# ═══════════════════════════════════════════════════════════════════
def test_c1_full_score_on_turnaround_surprise():
    """★ 적자 예상 → 흑자는 **가능한 최강의 서프라이즈**다.

    실측: 삼성SDI 2026.2Q 컨센 −356억 → 실제 +2,038억.
    %로 계산하면 −672%가 나와 `_tiered`가 0점을 준다(부호가 뒤집힌다).
    라벨 없이 None으로 두면 c1이 '미측정'이 되어 9점을 조용히 잃는다(T26).
    게이트가 흑전을 G2 통과로 처리하는 것과 같은 규칙으로 만점을 준다.
    """
    r = compute_score(
        _score_base(n_estimates=5, op_surprise_pct=None,
                    op_surprise_label="흑전 서프라이즈", revenue_surprise_pct=3.0)
    )
    assert r.raw["c1"] == 9.0
    assert "c1" not in r.missing_items


def test_c1_zero_on_loss_shock():
    """흑자 예상 → 적자는 미측정이 아니라 명백한 0점이다."""
    r = compute_score(
        _score_base(n_estimates=5, op_surprise_pct=None,
                    op_surprise_label="적자 쇼크", revenue_surprise_pct=3.0)
    )
    assert r.raw["c1"] == 0.0


def test_c1_undecided_when_both_sides_negative():
    """둘 다 적자면 판정하지 않는다 — 흑자 전환과 같은 급으로 볼 수 없다."""
    r = compute_score(
        _score_base(n_estimates=5, op_surprise_pct=None,
                    op_surprise_label="적자 예상 부합", revenue_surprise_pct=3.0)
    )
    assert r.raw["c1"] is None
    assert "c1" in r.missing_items  # 조용한 감점으로 드러난다


def test_c1_uses_percentage_in_normal_range():
    """정상 구간(둘 다 양수)에서는 라벨이 없고 %가 점수를 만든다."""
    r = compute_score(
        _score_base(n_estimates=5, op_surprise_pct=12.0, op_surprise_label=None)
    )
    assert r.raw["c1"] == 6.0  # 10% 이상 20% 미만


def test_label_ignored_without_consensus():
    """컨센서스가 없으면 라벨이 있어도 C축은 통째로 미측정이다(ADR 2)."""
    r = compute_score(
        _score_base(n_estimates=None, op_surprise_label="흑전 서프라이즈")
    )
    assert r.raw["c1"] is None
    assert r.denominator == SCORE_DENOM_FLASH_NO_CONSENSUS


# ═══════════════════════════════════════════════════════════════════
# screen_results 잔재 정리 — 지우면 안 되는 것을 지우지 않는가
# ═══════════════════════════════════════════════════════════════════
def test_future_row_is_detected_as_stale():
    """평가 분기보다 뒤에 있는 행은 잔재다(T36 이전에 들어온 미래 분기)."""
    evaluated = {"042520": _qi_helper(2025, 4)}
    row = {"code": "042520", "fiscal_year": 2026, "fiscal_quarter": 3}
    assert code_index_is_future(row, evaluated) is True


def test_past_row_is_kept_as_history():
    """★ 과거 분기 행은 남긴다 — P11(성과 추적)이 쓸 이력이다."""
    evaluated = {"005930": _qi_helper(2026, 2)}
    row = {"code": "005930", "fiscal_year": 2026, "fiscal_quarter": 1}
    assert code_index_is_future(row, evaluated) is False


def test_current_row_is_not_stale():
    evaluated = {"005930": _qi_helper(2026, 2)}
    row = {"code": "005930", "fiscal_year": 2026, "fiscal_quarter": 2}
    assert code_index_is_future(row, evaluated) is False


def test_unevaluated_code_is_never_touched():
    """이번 실행이 평가하지 않은 종목은 건드리지 않는다."""
    row = {"code": "999999", "fiscal_year": 2026, "fiscal_quarter": 3}
    assert code_index_is_future(row, {}) is False


def test_year_boundary_is_compared_by_index_not_quarter():
    """2025.4Q는 2026.1Q보다 **과거**다. 분기 숫자만 비교하면 뒤집힌다."""
    evaluated = {"A": _qi_helper(2026, 1)}
    assert code_index_is_future(
        {"code": "A", "fiscal_year": 2025, "fiscal_quarter": 4}, evaluated
    ) is False
