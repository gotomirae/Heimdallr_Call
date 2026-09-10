# PRD Ref: §4.2 (기업 투자 매력도) · ADR 2, ADR 5

import pytest

from src.screener.investment_score import (
    InvestmentScoreInput,
    compute_investment_score,
    linear_score,
    mean_measured,
    percentile_scores,
)
from src.screener.matrix import classify


def test_investment_score_full_axes_preserves_weighted_100_point_contract():
    result = compute_investment_score(InvestmentScoreInput(
        industry_growth=100,
        industry_position=50,
        earnings=90,
        growth_story=70,
        valuation=60,
        roe=50,
        fcf=40,
    ))
    # 손계산: 10+5+22.5+14+12+4+2.8 = 70.3
    assert result.denominator == 100
    assert result.raw_sum == pytest.approx(70.3)
    assert result.score == pytest.approx(70.3)
    assert result.mode == "investment_v1"


def test_investment_score_excludes_missing_axes_and_requires_60_points():
    enough = compute_investment_score(InvestmentScoreInput(
        earnings=90, growth_story=70, valuation=60,
    ))
    # 25+20+20=65, 손계산 (22.5+14+12)/65*100
    assert enough.denominator == 65
    assert enough.score == pytest.approx(74.6153846154)

    thin = compute_investment_score(InvestmentScoreInput(
        industry_growth=100, earnings=100,
    ))
    assert thin.denominator == 35
    assert thin.score is None


def test_peer_percentile_direction_and_ties_are_explicit():
    values = {"cheap": 5.0, "mid": 10.0, "expensive": 20.0, "missing": None}
    low_is_good = percentile_scores(values, higher_is_better=False)
    assert low_is_good["cheap"] == pytest.approx(100.0)
    assert low_is_good["expensive"] == pytest.approx(100 / 3)
    assert low_is_good["missing"] is None

    tied = percentile_scores({"a": 10.0, "b": 10.0, "c": 5.0})
    assert tied["a"] == tied["b"] == pytest.approx(100.0)


def test_growth_helpers_never_turn_missing_into_zero():
    assert linear_score(None, (-10.0, 30.0)) is None
    assert linear_score(-10.0, (-10.0, 30.0)) == 0.0
    assert linear_score(30.0, (-10.0, 30.0)) == 100.0
    assert mean_measured(None, None) is None
    assert mean_measured(20.0, None, 80.0) == 50.0


def test_current_price_stays_in_separate_pri_axis():
    assert "price" not in InvestmentScoreInput.__dataclass_fields__
    assert classify(80.0, 30.0).grade == "★"
    assert classify(80.0, 50.0).grade == "○"
    assert classify(80.0, 70.0).grade == "△"
    assert classify(70.0, 30.0).grade == "○"
    assert classify(70.0, 70.0).grade == "·"
    assert classify(50.0, 70.0).grade == "✕"
