# PRD Ref: §2 검토⑥, §6
"""결과 추적 순수 함수 테스트. 외부 I/O 없이 돈다."""

from __future__ import annotations

import pytest

from src.analysis.outcome import (
    HORIZONS,
    REASON_HALTED,
    REASON_NOT_ENOUGH_DAYS,
    Outcome,
    base_trading_day,
    group_stats,
    measure,
    median,
    pct_change,
    spearman,
    trading_days_after,
)

#: 거래일 10일. 주말(0705·0706, 0712·0713)이 빠져 있다 — 실제 시장과 같은 모양.
CLOSES = {
    "20260703": 100.0, "20260707": 102.0, "20260708": 104.0,
    "20260709": 103.0, "20260710": 105.0, "20260714": 110.0,
    "20260715": 112.0, "20260716": 111.0, "20260717": 115.0,
    "20260720": 120.0,
}
INDEX = {d: 1000.0 + i * 5 for i, d in enumerate(sorted(CLOSES))}


# ═══ 거래일 세기 ═══
def test_trading_days_counts_sessions_not_calendar_days():
    """★ 캘린더 일수로 세면 휴장일이 섞여 종목마다 다른 날을 비교하게 된다.

    기준 20260707에서 3거래일 뒤는 20260710이다(주말 건너뜀).
    캘린더로 3일을 더하면 20260710이 아니라 존재하지 않는 날이 된다.
    """
    assert trading_days_after(CLOSES, "20260707", 3) == "20260710"


def test_announce_on_holiday_uses_next_session():
    """★ 발표일이 휴장일이면 **다음 거래일**이 기준이다.

    장 마감 후·주말 공시가 실제로 많다. 그날이 시장이 처음 반응할 수 있는 날이다.
    20260705는 토요일 — 기준일은 20260707이어야 한다.
    """
    assert base_trading_day(CLOSES, "20260705") == "20260707"
    assert trading_days_after(CLOSES, "20260705", 1) == "20260708"


def test_returns_none_when_not_enough_sessions():
    """데이터 끝을 넘어가면 None — 있는 것으로 때우지 않는다."""
    assert trading_days_after(CLOSES, "20260717", 5) is None


def test_base_day_none_when_all_dates_are_before():
    assert base_trading_day(CLOSES, "20260801") is None


# ═══ 수익률 ═══
def test_pct_change_hand_check():
    #  (110 − 100) / 100 × 100 = +10.0%
    assert pct_change(100.0, 110.0) == pytest.approx(10.0)


def test_pct_change_blocks_nonpositive_base():
    assert pct_change(0.0, 10.0) is None
    assert pct_change(-5.0, 10.0) is None


# ═══ measure — 손계산 대조 ═══
def test_measure_hand_check():
    """발표 20260707 기준 D+3.

    종목: 기준 102.0 → 3거래일 뒤(20260710) 105.0
          (105 − 102) / 102 × 100 = +2.9411765%
    지수: 정렬 순서상 20260707은 두 번째(1005.0), 20260710은 다섯 번째(1020.0)
          (1020 − 1005) / 1005 × 100 = +1.4925373%
    초과: 2.9411765 − 1.4925373 = +1.4486392%p
    """
    result = measure(CLOSES, INDEX, "20260707", horizons=(3,))[3]
    assert result.ret_pct == pytest.approx(2.9411765, abs=1e-6)
    assert result.index_ret_pct == pytest.approx(1.4925373, abs=1e-6)
    assert result.excess_pp == pytest.approx(1.4486392, abs=1e-6)
    assert result.measured is True


def test_measure_marks_too_early_distinctly():
    """★★ '아직 이르다'와 '0%'를 반드시 구분한다.

    0으로 채우면 평균이 0 쪽으로 끌려가 **아무 효과 없음**으로 보인다.
    """
    result = measure(CLOSES, INDEX, "20260717", horizons=(60,))[60]
    assert result.excess_pp is None
    assert result.reason == REASON_NOT_ENOUGH_DAYS
    assert result.measured is False


def test_measure_handles_halted_stock():
    """거래정지·상폐는 수익률 None + 사유. 조용히 빠지면 생존편향이 된다."""
    result = measure({}, INDEX, "20260707", horizons=(1,))[1]
    assert result.excess_pp is None
    assert result.reason == REASON_HALTED


def test_measure_covers_all_horizons():
    out = measure(CLOSES, INDEX, "20260703")
    assert set(out) == set(HORIZONS)


# ═══ 스냅샷 ═══
def test_outcome_row_keeps_judgement_at_announce():
    """★ 발표 시점의 판단을 그대로 저장한다 — 사후 재계산은 사후확신 편향이다."""
    o = Outcome(
        code="005930", fiscal_year=2026, fiscal_quarter=2,
        announce_date="2026-07-07", grade_at_announce="★",
        score_at_announce=88.0, pri_at_announce=21.0,
        horizons=measure(CLOSES, INDEX, "20260703", horizons=(1,)),
    )
    row = o.as_db_row()
    assert row["grade_at_announce"] == "★"
    assert row["score_at_announce"] == 88.0
    assert "ret_d20" in row and "excess_d60" in row  # 미측정도 열은 있다


# ═══ 스피어만 IC ═══
def test_spearman_perfect_positive():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_spearman_perfect_negative():
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_spearman_handles_ties():
    """동점은 평균 순위. 실제 스코어에는 동점이 흔하다(만점 5종목)."""
    assert spearman([1, 1, 2, 3], [5, 5, 6, 7]) == pytest.approx(1.0)


def test_spearman_uses_only_complete_pairs():
    """★ 한쪽이 None인 걸 0으로 채우면 상관이 조작된다."""
    assert spearman([1, 2, None, 4], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_spearman_needs_three_pairs():
    """표본 2개로는 계산하지 않는다 — 숫자가 나와도 의미가 없다."""
    assert spearman([1, 2], [10, 20]) is None


def test_spearman_none_when_no_variation():
    """전부 같은 값이면 순위가 없다."""
    assert spearman([5, 5, 5], [1, 2, 3]) is None


# ═══ 그룹 요약 ═══
def test_group_stats_reports_unmeasured_count():
    """★ 측정 못 한 행을 조용히 빼면 '표본 26개'가 실제로는 3개인 걸 못 알아본다."""
    rows = [
        {"grade": "★", "excess_d20": 5.0},
        {"grade": "★", "excess_d20": None},
        {"grade": "★", "excess_d20": 9.0},
        {"grade": "·", "excess_d20": 1.0},
    ]
    stats = group_stats(rows, "grade", "excess_d20")
    assert stats["★"]["total"] == 3
    assert stats["★"]["n"] == 2
    assert stats["★"]["unmeasured"] == 1
    assert stats["★"]["median"] == pytest.approx(7.0)
    assert stats["·"]["median"] == pytest.approx(1.0)


def test_group_stats_keeps_none_group():
    """등급 없음(판정 불가)도 하나의 그룹으로 남긴다 — 사라지면 안 된다."""
    stats = group_stats([{"grade": None, "excess_d20": 2.0}], "grade", "excess_d20")
    assert None in stats


def test_median_even_and_odd():
    assert median([1, 2, 3]) == 2
    assert median([1, 2, 3, 4]) == pytest.approx(2.5)
    assert median([]) is None
