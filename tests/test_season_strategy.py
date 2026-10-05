# PRD Ref: §9.3 · ADR 28
from copy import deepcopy
from datetime import date, timedelta

import pytest

from src.analysis.season_strategy import create_plan, feedback, review_plan, season_of


def plan():
    return create_plan(date(2026, 10, 5),
        [{"code": "000001", "name": "실측예제", "board": "KOSDAQ", "sector": "반도체 장비"}],
        [{"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 2,
          "gate_passed": True, "grade": "★", "base_effect_warning": False, "pri": 0, "score_final": 80}],
        [{"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 2, "revenue": 100}],
        [{"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 3,
          "snapshot_at": "2026-10-04", "n_estimates": 2, "revenue_est": 120, "op_est": -10},
         {"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 3,
          "snapshot_at": "2026-10-06", "n_estimates": 2, "revenue_est": 999}], [], [], [], {}, [])


@pytest.mark.parametrize("day,year,quarter", [(date(2027,1,1),2026,4),
    (date(2026,4,1),2026,1),(date(2026,7,1),2026,2),(date(2026,10,1),2026,3)])
def test_upcoming_earnings_are_previous_calendar_quarter(day, year, quarter):
    assert (season_of(day)["target_year"], season_of(day)["target_quarter"]) == (year,quarter)


def test_no_future_consensus_and_real_zero_pri_is_preserved():
    p = plan()
    assert p["candidates"][0]["expected_revenue"] == 120
    assert p["candidates"][0]["pri"] == 0
    assert p["late_start"]


def test_strategy_returns_begin_after_actual_creation_and_use_index_calendar():
    p = plan()
    original = deepcopy(p)
    days = [(date(2026,10,6) + timedelta(days=i)).strftime("%Y%m%d") for i in range(61)]
    index = {d: 100 for d in days}
    stock = {d: 100 + i for i,d in enumerate(days)}
    stock["20261001"] = 1  # 월초로 소급하면 수익률 9900%라는 거짓 결과.
    index[days[20]] = 110
    stock.pop(days[40])  # 누락된 종목 봉으로 D40을 D41로 당기지 않는다.
    review = review_plan(p, date(2027,1,1), {"000001": stock}, {"KOSDAQ": index}, [])
    row = review["stocks"][0]
    # 손계산: 120/100-1 = 20%, 지수 110/100-1 = 10% → 10%p.
    assert row["horizons"]["20"]["excess"] == pytest.approx(10)
    assert "40" not in row["horizons"]
    assert row["base_date"] == "20261006"
    assert p == original


def test_failed_price_refresh_preserves_measured_review():
    p = plan()
    p["review"] = {"stocks": [{"code": "000001", "base_date": "20261006",
        "horizons": {"60": {"excess": 0, "date": "2027-01-05"}},
        "current": {"date": "20270105", "return": 0, "excess": 0}}]}
    review = review_plan(p, date(2027,1,6), {}, {}, [])
    assert review["stocks"][0]["horizons"]["60"]["excess"] == 0
    assert review["stocks"][0]["current"]["return"] == 0


def test_feedback_requires_mature_dated_results_and_two_seasons():
    prior = {"id": "2026-07", "review": {"stocks": [{"sector": "장비",
        "horizons": {"60": {"date": "2026-09-30", "excess": -1}}} for _ in range(10)]}}
    assert feedback([prior], "2026-10-01")[0]["applied"] is False
    second = deepcopy(prior)
    second["id"] = "2026-04"
    assert feedback([prior,second], "2026-10-01")[0]["action"] == "재확인 우선"
    assert feedback([prior], "2026-09-30") == []


def test_sign_flip_is_amount_gap_never_percentage():
    p = plan()
    f = [{"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 3,
          "revenue": 132, "op": 5, "op_status_label": "흑전"}]
    r = review_plan(p, date(2026,12,1), {}, {}, f)["stocks"][0]["earnings"]
    assert r["revenue_gap_pct"] == pytest.approx(10)
    assert r["op_gap"] == 15
    assert "op_gap_pct" not in r


def test_unknown_gate_or_base_effect_is_not_false():
    p = create_plan(date(2026,10,5), [{"code": "1"}], [{"code": "1", "fiscal_year": 2026,
        "fiscal_quarter": 2, "gate_passed": True, "grade": "★", "base_effect_warning": None}],
        [], [], [], [], [], {}, [])
    assert p["candidates"] == []
