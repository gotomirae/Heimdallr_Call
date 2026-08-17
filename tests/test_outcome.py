# PRD Ref: §2 검토⑥, §6
"""결과 추적 순수 함수 테스트. 외부 I/O 없이 돈다."""

from __future__ import annotations

import pytest

from src.analysis.outcome import (
    DISPLAY_HORIZONS,
    HORIZONS,
    REASON_HALTED,
    REASON_NOT_ENOUGH_DAYS,
    Outcome,
    base_trading_day,
    group_stats,
    horizon_column,
    horizon_label,
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


# ═══════════════════════════════════════════════════════════════════
# 발표 전 / 발표 당일 시점 (2026-08-17 추가)
#
# ★ 구간의 **방향**이 시점마다 다르다. 뒤집으면 부호가 통째로 반대가 되는데
#   숫자는 그럴듯하게 나와서 화면만 봐서는 못 잡는다.
# ═══════════════════════════════════════════════════════════════════
#: 발표일 = 20260610. 그 앞뒤로 거래일이 넉넉히 있는 계열.
_DAYS = ["202606%02d" % d for d in (1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 15, 16, 17)]
#: 100부터 1씩 오르다가 발표일(20260610=index 7, 값 107)만 기억해 두면 손계산이 쉽다.
_CLOSES = {d: 100.0 + i for i, d in enumerate(_DAYS)}
_INDEX = {d: 1000.0 for d in _DAYS}  # 지수는 고정 → 초과수익 = 종목 수익률


def test_horizon_column_names_avoid_minus_sign():
    """`ret_d-5`는 컬럼명이 될 수 없다 — 음수는 `m`으로 쓴다."""
    assert horizon_column(-5) == "m5"
    assert horizon_column(0) == "0"
    assert horizon_column(20) == "20"


def test_day_zero_is_previous_close_to_announce_close():
    """발표 당일 = **직전 거래일 종가 → 발표일 종가**.

    손계산: 06-09(106) → 06-10(107) = +0.943%
    """
    h = measure(_CLOSES, _INDEX, "20260610")[0]
    assert h.ret_pct == pytest.approx((107 / 106 - 1) * 100)
    assert h.excess_pp == pytest.approx(h.ret_pct)  # 지수 고정


def test_minus_five_is_five_sessions_before_to_announce():
    """발표 전 5일 = **5거래일 전 종가 → 발표일 종가**.

    _DAYS에서 발표일(20260610)의 직전 거래일은 06-09(106)이고,
    거기서 5거래일 거슬러 오르면 06-03(102)이다.
    손계산: 102 → 107 = +4.902%
    """
    h = measure(_CLOSES, _INDEX, "20260610")[-5]
    assert h.ret_pct == pytest.approx((107 / 102 - 1) * 100)


def test_forward_horizon_starts_at_announce_close():
    """발표 후 N일은 **발표일 종가**에서 출발한다(방향이 반대면 부호가 뒤집힌다).

    손계산: 06-10(107) → 06-17(112) = +4.673%  (5거래일 뒤)
    """
    h = measure(_CLOSES, _INDEX, "20260610")[5]
    assert h.ret_pct == pytest.approx((112 / 107 - 1) * 100)


def test_pre_announcement_none_when_not_enough_history():
    """★ 발표 전 거래일이 모자라면 None이다.

    있는 만큼으로 당겨 쓰면 '발표 전 5일'이 실제로는 2일이 되는데,
    숫자는 정상으로 보인다.
    """
    short = {d: _CLOSES[d] for d in _DAYS[6:]}  # 발표일 앞에 1거래일뿐
    h = measure(short, {d: 1000.0 for d in _DAYS[6:]}, "20260610")[-5]
    assert h.ret_pct is None
    assert h.reason == REASON_NOT_ENOUGH_DAYS


def test_trading_days_after_counts_sessions_not_calendar():
    """음수 방향도 **거래일**로 센다 — 주말·휴장이 끼어도 개수만 본다."""
    assert trading_days_after(_CLOSES, "20260610", -1) == "20260609"
    assert trading_days_after(_CLOSES, "20260610", -5) == "20260603"
    assert trading_days_after(_CLOSES, "20260610", 0) == "20260610"
    assert trading_days_after(_CLOSES, "20260610", 5) == "20260617"


def test_display_horizons_are_what_user_asked_for():
    assert DISPLAY_HORIZONS == (-5, 0, 5, 20, 60)
    assert all(d in HORIZONS for d in DISPLAY_HORIZONS)


def test_db_row_uses_m_prefix_for_negative():
    o = Outcome(code="A", fiscal_year=2026, fiscal_quarter=2,
                horizons=measure(_CLOSES, _INDEX, "20260610"))
    row = o.as_db_row()
    assert "ret_dm5" in row and "excess_dm5" in row
    assert "ret_d0" in row and "excess_d0" in row
    assert not any("-" in k for k in row), "컬럼명에 '-'가 들어가면 PostgREST가 죽는다"

def test_report_uses_horizon_column_for_db_keys():
    """★ 리포트가 컬럼명을 손으로 만들면 음수 시점에서 KeyError로 죽는다.

    실측(2026-08-17): `outcome_run`의 리포트가 `f"excess_d{days}"`를 써서
    `excess_d-5`를 찾다가 KeyError로 죽었다. **수집·저장은 이미 성공한 뒤**라
    481건이 DB에 들어갔는데도 프로세스가 exit 1이었다 — 부분 성공이 실패로 보인다.
    컬럼명은 반드시 `horizon_column()`을 거쳐야 한다.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "src" / "analysis" / "outcome_run.py").read_text(
        encoding="utf-8"
    )
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    for bad in ('excess_d{days}', 'ret_d{days}'):
        assert bad not in code, (
            f"'{bad}'로 컬럼명을 만들고 있다 — 음수 시점에서 KeyError로 죽는다. "
            "horizon_column(days)를 써라"
        )
    assert "horizon_column" in code, "리포트가 horizon_column을 쓰지 않는다"


def test_horizon_column_round_trips_for_every_horizon():
    """모든 시점이 유효한 컬럼명을 만들어야 한다 — '-'가 들어가면 PostgREST가 죽는다."""
    for days in HORIZONS:
        for prefix in ("ret_d", "excess_d"):
            name = f"{prefix}{horizon_column(days)}"
            assert "-" not in name and "+" not in name, f"{name}은 컬럼명이 될 수 없다"
            assert name.replace("_", "").isalnum(), f"{name}에 이상한 문자가 있다"
