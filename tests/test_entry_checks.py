# PRD Ref: §8.8 — JARVIS entry_checks(M1·M2·M5) · K1 경계값 회귀
"""JARVIS `rules.yaml > entry_core`의 경계(≤ −10%, ≤ 12%, < 50, ≤ 0.30%, ≤ 3봉,
2일 연속)를 **정확히 경계 위 값**으로 고정한다. 순수 함수만 다룬다(외부 I/O 없음)."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.config import constants as C
from src.notify.entry_checks_run import (
    compose_row,
    first_announcements,
    k1_targets,
    prior_year_actual,
    stage1,
)
from src.screener.entry_checks import (
    Bar,
    annual_consensus_ok,
    confirmed_bars,
    first_session_after,
    invalidation,
    k1_breakout,
    m1_fundamental,
    m1_price,
    m2_check,
    m2_decide,
    m5_check,
)

KST = ZoneInfo("Asia/Seoul")


def _qi(year: int, quarter: int) -> int:
    return year * 4 + quarter - 1


def _series(**overrides) -> dict[int, dict]:
    """2026.2Q 평가 기준 5개 분기. 손계산: 매출 YoY 5→12, 영업익 YoY 8→20 가속."""
    rows = {
        _qi(2025, 2): {"ttm_revenue": 1000, "ttm_op": 100, "revenue": 240, "op": 20},
        _qi(2025, 3): {"revenue": 250, "op": 22},
        _qi(2025, 4): {"revenue": 260, "op": 24},
        _qi(2026, 1): {"revenue_yoy": 5.0, "op_yoy": 8.0, "op": 25, "revenue": 270},
        _qi(2026, 2): {
            "revenue_yoy": 12.0, "op_yoy": 20.0, "op": 30, "revenue": 280,
            "ttm_revenue": 1050, "ttm_op": 120,
        },
    }
    for key, value in overrides.items():
        quarter, field = key.split("__")
        rows[{"t": _qi(2026, 2), "t1": _qi(2026, 1), "t4": _qi(2025, 2)}[quarter]][field] = value
    return rows


def _fin(series=None, **kwargs):
    kwargs.setdefault("base_effect_warning", False)
    return m1_fundamental(series or _series(), _qi(2026, 2), **kwargs)


# ═══ M1 재무 ═══════════════════════════════════════════════════════
def test_m1_fundamental_passes_hand_computed_case():
    result = _fin()
    assert result["pass"] is True
    assert result["rev_yoy"] == [12.0, 5.0] and result["op_yoy"] == [20.0, 8.0]
    assert result["ttm_rev_growth"] == 5.0 and result["ttm_op_growth"] == 20.0
    assert result["annual_consensus_ok"] is None  # 컨센서스 없음 = 데이터 없음, 통과


@pytest.mark.parametrize("overrides", [
    {"t__revenue_yoy": 5.0},          # 가속 아님(같음)
    {"t__op_yoy": 8.0},
    {"t1__revenue_yoy": 0.0},         # YoY > 0 아님(0)
    {"t1__op_yoy": -1.0},
    {"t__op": 0},                     # 흑자 아님
    {"t__ttm_revenue": 1000},         # TTM 증가 아님(같음)
    {"t__ttm_op": 100},
])
def test_m1_fundamental_boundaries_fail(overrides):
    assert _fin(_series(**overrides))["pass"] is False


def test_sign_change_quarter_is_fail_not_unknown():
    series = _series(t__op_yoy=None, t__op_status_label="흑전")
    result = _fin(series)
    assert result["pass"] is False
    assert result["checks"]["op_accelerating"] is False


def test_missing_data_is_none_not_false():
    assert _fin(_series(t__revenue_yoy=None))["pass"] is None
    assert _fin(base_effect_warning=None)["pass"] is None
    assert _fin(base_effect_warning=True)["pass"] is False


def test_annual_consensus_must_exceed_prior_year_when_present():
    up = {"revenue_est": 1100, "op_est": 130}
    assert _fin(annual_consensus=up, prior_year_actual=(1000, 100))["pass"] is True
    flat = {"revenue_est": 1000, "op_est": 130}
    assert annual_consensus_ok(flat, (1000, 100)) is False
    assert _fin(annual_consensus=flat, prior_year_actual=(1000, 100))["pass"] is False
    assert annual_consensus_ok({"revenue_est": None, "op_est": 1}, (1, 1)) is None


def test_prior_year_actual_needs_all_four_quarters():
    series = {_qi(2025, q): {"revenue": 10 * q, "op": q} for q in (1, 2, 3, 4)}
    assert prior_year_actual(series, 2025) == (100.0, 10.0)
    del series[_qi(2025, 3)]
    assert prior_year_actual(series, 2025) is None


# ═══ M1 가격 ═══════════════════════════════════════════════════════
def _bars(closes: list[float], start: str = "20250101") -> list[Bar]:
    """평일만 이어 붙인 확정 일봉. 저가·고가는 종가 ±1%."""
    out, day = [], datetime.strptime(start, "%Y%m%d")
    for close in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        out.append(Bar(day.strftime("%Y%m%d"), close, close * 1.01, close * 0.99, close, 1000))
        day += timedelta(days=1)
    return out


def test_m1_price_pb_exact_minus_ten_percent_from_post_earnings_high():
    closes = [10_000.0] * 70 + [9_500.0] * 9 + [9_000.0]
    bars = _bars(closes)
    announced = bars[60].date
    result = m1_price(bars, announcement_date=announced, pri=49.99)
    assert result["drawdown_from_post_earnings_high"] == -10.0
    assert result["price_state"] == "PB" and result["pass"] is True
    near = m1_price(_bars(closes[:-1] + [9_001.0]), announcement_date=announced, pri=10)
    assert near["checks"]["correction"] is False


def test_m1_price_52w_drawdown_exact_minus_fifteen():
    closes = [10_000.0] * 60 + [8_500.0] * 30
    result = m1_price(_bars(closes), announcement_date=None, pri=10)
    assert result["drawdown_from_52w_high"] == -15.0
    assert result["price_state"] == "PB"


def test_m1_price_sideways_exact_boundaries():
    # 직전 21번째 종가 100 → 오늘 105(+5.0%) · 최근 20일 범위 100~112(12.0%)
    closes = [100.0] * 60 + [100.0] + [106.0] * 9 + [112.0, 100.0] + [104.0] * 7 + [105.0]
    assert len(closes) == 80
    result = m1_price(_bars(closes), announcement_date=None, pri=10)
    assert result["range_20d_pct"] == 12.0 and result["ret_20d_pct"] == 5.0
    assert result["checks"]["sideways"] is True and result["price_state"] == "SW"
    wider = closes[:-2] + [112.01, 105.0]
    assert m1_price(_bars(wider), announcement_date=None, pri=10)["checks"]["sideways"] is False


def test_m1_price_pri_fifty_fails_and_missing_pri_is_none():
    closes = [10_000.0] * 60 + [8_000.0] * 30
    assert m1_price(_bars(closes), announcement_date=None, pri=50)["pass"] is False
    assert m1_price(_bars(closes), announcement_date=None, pri=None)["pass"] is None


def test_confirmed_bars_drop_intraday_today():
    bars = [Bar("20260930", 1, 1, 1, 100), Bar("20261001", 1, 1, 1, 101)]
    before_close = datetime(2026, 10, 1, 14, 0, tzinfo=KST)
    after_close = datetime(2026, 10, 1, C.KOREA_MARKET_COMPLETED_HOUR_KST, 5, tzinfo=KST)
    assert [b.date for b in confirmed_bars(bars, before_close)] == ["20260930"]
    assert [b.date for b in confirmed_bars(bars, after_close)] == ["20260930", "20261001"]


# ═══ M2 ═══════════════════════════════════════════════════════════
def _m2(hist: list[float], *, gap: float, close: float = 250.0) -> dict:
    """gap = Signal − MACD(원). hist와 독립적으로 갭 경계를 시험한다."""
    macd = [0.0] * len(hist)
    signal = [0.0] * (len(hist) - 1) + [gap]
    return m2_decide(macd, signal, hist, close)


def test_m2_gap_exactly_030_percent_passes():
    result = _m2([-0.9, -0.8, -0.7, -0.6], gap=0.75)  # 0.75×100/250 = 0.30%
    assert result["gap_pct_of_close"] == 0.30 and result["pass"] is True
    assert result["state"] == "near" and result["hist_rising_bars"] == 3


def test_m2_projected_three_bars_passes_four_fails():
    assert _m2([-6.0, -5.0, -4.0, -3.0], gap=10.0)["projected_bars"] == 3
    assert _m2([-6.0, -5.0, -4.0, -3.0], gap=10.0)["pass"] is True
    four = _m2([-6.5, -5.5, -4.5, -3.5], gap=10.0)
    assert four["projected_bars"] == 4 and four["pass"] is False


def test_m2_needs_two_consecutive_improvements():
    one = _m2([-0.5, -0.9, -0.7, -0.6], gap=0.1)
    assert one["hist_rising_bars"] == 2 and one["pass"] is True
    broken = _m2([-0.5, -0.4, -0.7, -0.6], gap=0.1)
    assert broken["hist_rising_bars"] == 1 and broken["pass"] is False


def test_m2_cross_today_allowed_and_day_after_rejected():
    today = _m2([-0.3, -0.2, -0.1, 0.05], gap=-0.05)
    assert today["cross_today"] is True and today["pass"] is True and today["projected_bars"] == 0
    after = _m2([-0.2, -0.1, 0.05, 0.1], gap=-0.1)
    assert after["state"] == "above" and after["pass"] is False and after["days_above_signal"] == 2


def test_m2_check_on_real_series_shape():
    closes = [100.0 + i * 0.5 for i in range(80)] + [140.0 - i * 1.5 for i in range(20)]
    result = m2_check(_bars(closes))
    assert result is not None and len(result["hist"]) == 4
    assert result["as_of"] == _bars(closes)[-1].date
    assert m2_check(_bars(closes[:59])) is None


# ═══ M5 ═══════════════════════════════════════════════════════════
def test_m5_two_day_paths_and_preference():
    foreign = m5_check([("20260930", 5, -1), ("20260929", 3, -2), ("20260926", -1, 9)])
    # 합산은 3일(4·1·8)이지만 같은 주체 2일 연속이 더 강한 증거라 외국인을 쓴다.
    assert foreign["pass"] is True and foreign["path"] == "foreign" and foreign["streak_days"] == 2
    assert foreign["streaks"]["combined"] == 3
    inst = m5_check([("20260930", 5, 3), ("20260929", -1, 2)])
    assert inst["path"] == "institution" and inst["streaks"]["foreign"] == 1
    combined = m5_check([("20260930", 5, -1), ("20260929", -1, 3)])
    assert combined["path"] == "combined" and combined["streak_days"] == 2
    one_day = m5_check([("20260930", 5, 5), ("20260929", -5, -5)])
    assert one_day["pass"] is False and one_day["path"] is None
    assert m5_check([("20260930", 1, 1)]) is None


def test_m5_zero_is_not_net_buying_and_longest_streak_wins():
    zero = m5_check([("20260930", 0, 0), ("20260929", 5, 5)])
    assert zero["pass"] is False
    longest = m5_check([
        ("20260930", 1, 1), ("20260929", 1, 1), ("20260926", -1, 1), ("20260925", 1, 1),
    ])
    assert longest["path"] == "institution" and longest["streak_days"] == 4
    assert longest["foreign_net"] == [1, -1, 1, 1]  # [-3..0] 시간순


def test_kis_investor_parser_drops_unpublished_today():
    from src.collectors.kis_prices import parse_kis_investor_rows

    body = {"output": [
        {"stck_bsop_date": "20261001", "frgn_ntby_qty": "0", "orgn_ntby_qty": "0", "prsn_ntby_qty": ""},
        {"stck_bsop_date": "20260930", "frgn_ntby_qty": "1,200", "orgn_ntby_qty": "-300", "prsn_ntby_qty": "-900"},
    ]}
    assert parse_kis_investor_rows(body) == [("20260930", 1200, -300)]


def test_naver_ohlcv_parser_keeps_open_high_low_volume():
    from src.collectors.quarter_prices import parse_daily_ohlcv

    text = """[['날짜','시가','고가','저가','종가','거래량','외국인소진율'],
    ['20260930', 270000, 276000, 268000, 269500, 1000, 50.1],
    ['20260929', 0, 0, 0, 0, 0, 50.0]]"""
    assert parse_daily_ohlcv(text) == [("20260930", 270000.0, 276000.0, 268000.0, 269500.0, 1000.0)]


# ═══ 무효화선 · K1 ════════════════════════════════════════════════
def test_invalidation_uses_intraday_lows():
    bars = [Bar(f"202609{d:02d}", 100, 110, 90 + d, 100) for d in range(1, 21)]
    lows = invalidation(bars, "PB")
    assert lows["low_10d"] == 101 and lows["low_20d"] == 91 and lows["invalidation_price"] == 101
    assert invalidation(bars, "SW")["invalidation_price"] == 91
    assert invalidation(bars, None)["invalidation_price"] is None


def _k1_bars(*, open_: float, high: float, low: float, close: float, volume: float) -> list[Bar]:
    prior = [Bar(f"2026090{i}" if i < 10 else f"202609{i}", 10_000, 10_100, 9_900, 10_000, 1_000_000)
             for i in range(1, 22)]
    return prior + [Bar("20260922", open_, high, low, close, volume)]


def test_k1_hand_computed_pass_and_each_boundary():
    passing = k1_breakout(_k1_bars(open_=10_300, high=11_000, low=10_200, close=10_800, volume=2_500_000), "20260922")
    assert passing["pass"] is True
    assert passing["gap_open_pct"] == 3.0 and passing["volume_mult"] == 2.5 and passing["close_location"] == 0.75
    low_volume = k1_breakout(_k1_bars(open_=10_300, high=11_000, low=10_200, close=10_800, volume=2_499_999), "20260922")
    assert low_volume["pass"] is False
    weak_close = k1_breakout(_k1_bars(open_=10_300, high=11_000, low=10_000, close=10_690, volume=3_000_000), "20260922")
    assert weak_close["close_location"] == 0.69 and weak_close["pass"] is False
    gap_miss_but_return = k1_breakout(_k1_bars(open_=10_299, high=10_600, low=10_200, close=10_500, volume=3_000_000), "20260922")
    assert gap_miss_but_return["close_return_pct"] == 5.0 and gap_miss_but_return["pass"] is True
    assert k1_breakout(_k1_bars(open_=1, high=1, low=1, close=1, volume=1), "20990101") is None


def test_first_session_after_disclosure():
    sessions = ["20260929", "20260930", "20261001", "20261002"]
    after_close = datetime(2026, 9, 30, 15, 50, tzinfo=KST)
    pre_open = datetime(2026, 9, 30, 8, 10, tzinfo=KST)
    assert first_session_after("20260930", after_close, sessions) == "20261001"
    assert first_session_after("20260930", pre_open, sessions) == "20260930"
    assert first_session_after("20260930", None, sessions) == "20261001"  # 시각 모름 → 다음 날
    assert first_session_after("20261002", None, sessions) is None


def test_k1_targets_filter_grade_base_effect_and_window():
    screens = [
        {"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 3, "grade": "★", "base_effect_warning": False},
        {"code": "000002", "fiscal_year": 2026, "fiscal_quarter": 3, "grade": "△", "base_effect_warning": False},
        {"code": "000003", "fiscal_year": 2026, "fiscal_quarter": 3, "grade": "○", "base_effect_warning": True},
    ]
    disclosures = [
        {"code": code, "fiscal_year": 2026, "fiscal_quarter": 3, "doc_type": "provisional",
         "disclosed_at": "2026-09-29", "detected_at": None, "rcept_no": f"2026092900000{code[-1]}"}
        for code in ("000001", "000002", "000003")
    ] + [{"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 3, "doc_type": "periodic",
          "disclosed_at": "2026-09-29", "rcept_no": "x"}]
    sessions = ["20260928", "20260929", "20260930"]
    targets = k1_targets(disclosures, screens, sessions, "20260930")
    assert [(t["code"], t["d0"]) for t in targets] == [("000001", "20260930")]


# ═══ 행 조립 · 단계 ═══════════════════════════════════════════════
def test_stage1_failure_leaves_m2_m5_null_and_keeps_reason():
    screen = {"fiscal_year": 2026, "fiscal_quarter": 2, "pri": 30, "base_effect_warning": False, "grade": "○"}
    fin = stage1("000001", screen, _series(t__op=0), annual=None, year=2026)
    row = compose_row("000001", "20260930", fin, bars=None, flow=None, announcement_date=None,
                      pri=30, notes=[], computed_at="x")
    assert row["m1_pass"] is False and row["m2_detail"] is None and row["m5_detail"] is None
    assert row["m1_detail"]["checks"]["op_positive"] is False and row["check_date"] == "2026-09-30"


def test_pri_at_fifty_fails_stage1_without_price_fetch():
    screen = {"fiscal_year": 2026, "fiscal_quarter": 2, "pri": 50, "base_effect_warning": False}
    fin = stage1("000001", screen, _series(), annual=None, year=2026)
    assert fin["pass"] is True and fin["stage1_pass"] is False
    row = compose_row("000001", "20260930", fin, bars=None, flow=None, announcement_date=None,
                      pri=50, notes=[], computed_at="x")
    assert row["m1_pass"] is False


def test_stale_bars_make_m1_unknown_and_m2_null():
    screen = {"fiscal_year": 2026, "fiscal_quarter": 2, "pri": 30, "base_effect_warning": False}
    fin = stage1("000001", screen, _series(), annual=None, year=2026)
    bars = _bars([10_000.0] * 60 + [8_000.0] * 30)
    stale_row = compose_row("000001", "20991231", fin, bars=bars, flow=None, announcement_date=None,
                            pri=30, notes=[], computed_at="x")
    assert stale_row["m1_pass"] is None and stale_row["m2_pass"] is None
    assert "stale_bars" in stale_row["m1_detail"]["notes"]
    fresh = compose_row("000001", bars[-1].date, fin, bars=bars, flow=None, announcement_date=None,
                        pri=30, notes=[], computed_at="x")
    assert fresh["m1_pass"] is True and fresh["m1_detail"]["price_state"] == "PB"
    assert fresh["invalidation_price"] == fresh["low_10d"]


def test_stale_flow_is_unknown():
    screen = {"fiscal_year": 2026, "fiscal_quarter": 2, "pri": 30, "base_effect_warning": False}
    fin = stage1("000001", screen, _series(), annual=None, year=2026)
    flow = m5_check([("20260929", 5, 5), ("20260926", 5, 5)])
    row = compose_row("000001", "20260930", fin, bars=None, flow=flow, announcement_date=None,
                      pri=30, notes=[], computed_at="x")
    assert row["m5_pass"] is None and row["m5_detail"]["path"] == "foreign"


def test_first_announcements_accepts_dart_yyyymmdd():
    rows = [
        {"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 2, "disclosed_at": "20260814"},
        {"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 2, "disclosed_at": "2026-08-01T00:00:00+00:00"},
    ]
    assert first_announcements(rows) == {("000001", 2026, 2): "2026-08-01"}


# ═══ JARVIS rules.yaml 대조 (T215) ════════════════════════════════
def _jarvis_rules() -> Path | None:
    from src.utils.env import optional_env

    root = Path(__file__).resolve().parents[1]
    candidates = [optional_env("JARVIS_RULES_PATH")] + [
        str(parent / "JARVIS" / "config" / "rules.yaml") for parent in root.parents
    ]
    return next((Path(c) for c in candidates if c and Path(c).exists()), None)


def test_thresholds_match_jarvis_entry_core():
    path = _jarvis_rules()
    if path is None:
        pytest.skip("JARVIS 저장소 없음 — 같은 PC에서만 대조한다")
    yaml = pytest.importorskip("yaml")
    rules = yaml.safe_load(path.read_text(encoding="utf-8"))
    m1, m2, m5 = (rules["entry_core"][key] for key in ("M1_earnings_up_price_not", "M2_macd_pre_cross", "M5_flow_2days"))
    assert m1["quarterly"]["consecutive_quarters_yoy_positive"] == C.ENTRY_M1_CONSECUTIVE_YOY_QUARTERS
    assert m1["annual"]["ttm_revenue_growth_min_pct"] == C.ENTRY_M1_TTM_REVENUE_GROWTH_MIN_PCT
    assert m1["annual"]["ttm_op_growth_min_pct"] == C.ENTRY_M1_TTM_OP_GROWTH_MIN_PCT
    price = m1["price_not_reflected"]
    assert price["correction"]["from_post_earnings_high_max_pct"] == C.ENTRY_M1_POST_EARNINGS_DRAWDOWN_MAX_PCT
    assert price["correction"]["or_from_52w_high_max_pct"] == C.ENTRY_M1_HIGH_52W_DRAWDOWN_MAX_PCT
    assert price["sideways"]["range_20d_max_pct"] == C.ENTRY_M1_RANGE_20D_MAX_PCT
    assert price["sideways"]["abs_return_20d_max_pct"] == C.ENTRY_M1_ABS_RETURN_20D_MAX_PCT
    assert price["reflection_max"]["kr_pri"] == C.ENTRY_M1_PRI_MAX
    assert tuple(m2["params"]) == C.ENTRY_M2_MACD_PARAMS
    assert m2["hist_rising_bars_min"] == C.ENTRY_M2_HIST_RISING_BARS_MIN
    assert m2["near_cross_gap_pct_of_close_max"] == C.ENTRY_M2_NEAR_CROSS_GAP_PCT_OF_CLOSE_MAX
    assert m2["or_projected_bars_to_cross_max"] == C.ENTRY_M2_PROJECTED_BARS_TO_CROSS_MAX
    assert m2["allow_cross_today"] is C.ENTRY_M2_ALLOW_CROSS_TODAY
    assert m5["kr"]["days"] == C.ENTRY_M5_STREAK_DAYS
    k1 = rules["breakout_watch"]["K1_kr"]
    assert tuple(k1["grades"]) == C.K1_GRADES
    assert k1["gap_open_min_pct"] == C.K1_GAP_OPEN_MIN_PCT
    assert k1["or_close_return_min_pct"] == C.K1_CLOSE_RETURN_MIN_PCT
    assert k1["volume_mult_min"] == C.K1_VOLUME_MULT_MIN
    assert k1["close_location_min"] == C.K1_CLOSE_LOCATION_MIN
    assert rules["tech_display"]["high_lookback_days"] == C.ENTRY_HIGH_LOOKBACK_SESSIONS
    invalidation_rule = rules["entry_gate"]["invalidation"]
    assert (invalidation_rule["PB"], invalidation_rule["SW"]) == ("low_10d", "low_20d")
