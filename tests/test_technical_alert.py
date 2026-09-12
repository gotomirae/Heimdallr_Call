# PRD Ref: §8.6 — 성장 지속·MACD 상향 접근 텔레그램 알림
"""기술 신호는 외부 I/O 없이 손계산 가능한 입력으로 검증한다."""

from __future__ import annotations

import pytest

from src.config.constants import TECHNICAL_ALERT_DAILY_MAX
from src.notify import technical_alert
from src.notify.technical_alert import (
    KIND_TECHNICAL,
    _daily_limit,
    growth_candidates,
    unsent_matches,
)
from src.notify.templates import technical_setup_message
from src.screener.technical_setup import (
    company_growth_streak,
    sector_growth_continuity,
    technical_setup,
)


def _series(revenue=(-5.0, 5.0, 15.0), op=(0.0, 10.0, 25.0)):
    return {
        100 + offset: {
            "revenue_yoy": revenue[offset], "op_yoy": op[offset], "op": 10.0,
        }
        for offset in range(3)
    }


def test_company_requires_both_growth_rates_to_improve_for_two_quarters():
    result = company_growth_streak(_series(), 102)
    assert result is not None
    assert result.revenue_yoy == (5.0, 15.0)
    assert company_growth_streak(_series(op=(0.0, 20.0, 10.0)), 102) is None
    assert company_growth_streak(_series(revenue=(-5.0, None, 15.0)), 102) is None


def test_sector_requires_positive_two_quarter_medians_and_five_members():
    members = []
    for value in (5, 7, 9, 11, 13):
        members.append({101: {"revenue_yoy": value, "op_yoy": value + 1},
                        102: {"revenue_yoy": value + 2, "op_yoy": value + 3}})
    result = sector_growth_continuity(members, 102)
    assert result is not None
    assert result.revenue_yoy == (9.0, 11.0)
    assert result.members == (5, 5)
    assert sector_growth_continuity(members[:4], 102) is None
    members[0][101]["op_yoy"] = -100
    members[1][101]["op_yoy"] = -100
    members[2][101]["op_yoy"] = -100
    assert sector_growth_continuity(members, 102) is None


def _approaching_prices() -> dict[str, float]:
    # 40일 횡보 → 13일 조정 → 10일 좁은 횡보/반등. 50일 고점 대비 -20%, RSI 50 이하 상승.
    values = [100.0] * 40
    values += [100.0 - index for index in range(1, 14)]
    values += [76.0] * 7 + [76.5, 77.0, 78.0]
    return {f"2026{index + 1:04d}": value for index, value in enumerate(values)}


def test_technical_setup_is_below_signal_rising_and_not_overheated():
    result = technical_setup(_approaching_prices())
    assert result is not None
    assert result.histogram < 0
    assert result.macd < result.signal
    assert result.rsi <= 50
    assert result.drawdown_50d_pct <= -20
    assert result.price_regime in {"하락 중 반등 접근", "조정 후 횡보"}
    assert result.qualifies is True


def test_no_alert_after_macd_has_already_crossed():
    prices = _approaching_prices()
    prices["20260063"] = 90.0
    result = technical_setup(prices)
    assert result is not None
    assert result.histogram >= 0 or result.qualifies is False


def test_growth_candidates_require_gate_company_and_sector_together():
    screens = [{"code": f"00000{i}", "fiscal_year": 2025, "fiscal_quarter": 3,
                "gate_passed": True, "grade": "○", "score_final": 80}
               for i in range(1, 7)]
    universe = [{"code": f"00000{i}", "name": f"기업{i}", "industry": "반도체 제조업",
                 "products": "반도체", "is_excluded": False} for i in range(1, 7)]
    fundamentals = []
    for code in (row["code"] for row in universe):
        for offset, revenue, op in ((0, -5, 3), (1, 5, 10), (2, 15, 25)):
            fundamentals.append({
                "code": code, "fiscal_year": 2025, "fiscal_quarter": 1 + offset,
                "revenue_yoy": revenue, "op_yoy": op, "op": 10,
            })
    assert len(growth_candidates(screens, universe, fundamentals)) == 6
    screens[0]["gate_passed"] = False
    assert len(growth_candidates(screens, universe, fundamentals)) == 5


def test_technical_message_discloses_that_cross_is_not_confirmed():
    text = technical_setup_message({
        "name": "테스트", "code": "000001", "sector": "반도체 장비", "grade": "○",
        "company_growth": {"revenue_yoy": (5, 15), "op_yoy": (10, 25)},
        "sector_growth": {"revenue_yoy": (8, 10), "op_yoy": (12, 15)},
        "technical": {"price_regime": "조정 후 횡보", "drawdown_50d_pct": -12,
                      "ret_20d_pct": -4, "macd": -2, "signal": -1,
                      "histogram_pct": -0.1, "rsi": 55},
    })
    assert "아직 골든크로스 전" in text
    assert "산업 2Q" in text and "기업 2Q" in text
    assert "MACD -2.00 / Signal -1.00" in text
    assert KIND_TECHNICAL == "technical_setup"


def test_sent_top_row_does_not_block_next_unsent_row(monkeypatch):
    rows = [
        {"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 2},
        {"code": "000002", "fiscal_year": 2026, "fiscal_quarter": 2},
        {"code": "000003", "fiscal_year": 2026, "fiscal_quarter": 2},
    ]
    monkeypatch.setattr(
        technical_alert, "already_sent",
        lambda code, *_args: code == "000001",
    )
    selected, duplicates = unsent_matches(rows, 2)
    assert [row["code"] for row in selected] == ["000002", "000003"]
    assert duplicates == 1


def test_daily_technical_alert_limit_is_two():
    assert TECHNICAL_ALERT_DAILY_MAX == 2
    assert _daily_limit(100) == 2
    assert _daily_limit(1) == 1
    assert _daily_limit(-1) == 0
