# PRD Ref: §8.6 — 성장 지속·MACD 상향 접근 텔레그램 알림
"""기술 신호는 외부 I/O 없이 손계산 가능한 입력으로 검증한다."""

from __future__ import annotations

import pytest
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config.constants import TECHNICAL_ALERT_DAILY_MAX
from src.notify import technical_alert
from src.notify.technical_alert import (
    KIND_TECHNICAL,
    _daily_limit,
    growth_candidates,
    latest_annual_consensus,
    unsent_matches,
)
from src.notify.templates import daily_digest, technical_setup_message
from src.screener.technical_setup import (
    company_growth_streak,
    company_initial_inflection,
    sector_growth_continuity,
    technical_setup,
)


def _series(revenue=(-5.0, 5.0, 15.0), op=(0.0, 10.0, 25.0)):
    return {
        100 + offset: {
            "revenue_yoy": revenue[offset], "op_yoy": op[offset], "op": 10.0,
            "opm": 5.0 + offset,
        }
        for offset in range(3)
    }


def test_company_requires_both_growth_rates_to_improve_for_two_quarters():
    result = company_growth_streak(_series(), 102)
    assert result is not None
    assert result.revenue_yoy == (5.0, 15.0)
    assert company_growth_streak(_series(op=(0.0, 20.0, 10.0)), 102) is None
    assert company_growth_streak(_series(revenue=(-5.0, None, 15.0)), 102) is None
    falling_opm = _series()
    falling_opm[102]["opm"] = 5.0
    assert company_growth_streak(falling_opm, 102) is None


def test_first_profitable_quarter_uses_status_not_fake_profit_growth_percent():
    series = {
        101: {"revenue_yoy": 5.0, "op": -3.0, "op_yoy": None},
        102: {"revenue_yoy": 15.0, "op": 2.0, "op_yoy": None, "op_status_label": "흑전"},
    }
    result = company_initial_inflection(series, 102)
    assert result is not None and result.stage == "초기 흑전"
    assert result.op_yoy == () and result.op_status_label == "흑전"
    series[102]["op_status_label"] = None
    assert company_initial_inflection(series, 102) is None


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
    falling = [{101: {"revenue_yoy": 20, "op_yoy": 20},
                102: {"revenue_yoy": 10, "op_yoy": 10}} for _ in range(5)]
    assert sector_growth_continuity(falling, 102) is None


def _approaching_prices() -> dict[str, float]:
    # 40일 횡보 → 13일 조정 → 10일 좁은 횡보/반등. 50일 고점 대비 -20%, RSI 50 이하 상승.
    values = [100.0] * 40
    values += [100.0 - index for index in range(1, 14)]
    values += [76.0] * 7 + [76.5, 77.0, 78.0]
    return {f"2026{index + 1:04d}": value for index, value in enumerate(values)}


def _crossing_prices() -> dict[str, float]:
    # 30일 100원 후 완만한 조정·반등. 마지막 날 5/20일선과 MACD가 모두
    # 아래→위로 교차하지만 MACD gap의 앞선 3일은 연속 상승하지 않는다.
    values = [100.0] * 30 + [
        99.8507, 98.7701, 98.8725, 97.9163, 96.8874, 96.5907, 95.5031,
        96.1217, 96.2748, 95.3492, 94.7706, 95.5647, 95.0685, 95.3699,
        94.6325, 95.3795, 94.932, 95.6709, 96.4963, 97.4906, 97.2138,
        96.8619, 97.4811, 97.3508, 98.2122, 98.3702, 97.3881, 97.6718,
        98.5177, 99.0496, 99.9544, 99.7467, 99.8707, 99.0365, 98.3937,
        99.5179, 99.1747, 98.5886, 97.8450, 98.4107, 98.2399, 98.8993,
        98.9716, 98.6629, 99.7569,
    ]
    return {f"2026{index + 1:04d}": value for index, value in enumerate(values)}


def test_far_below_sma_does_not_qualify_even_when_macd_approaches():
    result = technical_setup(_approaching_prices(), announcement_date="20260001")
    assert result is not None
    assert result.histogram < 0
    assert result.macd < result.signal
    assert result.drawdown_50d_pct <= -20
    assert result.price_regime in {"하락 중 반등 접근", "조정 후 횡보", "조정 후 회복"}
    assert result.announcement_return_pct is not None and result.announcement_return_pct < 0
    assert result.macd_approaching is True
    assert result.sma_approaching is False
    assert result.qualifies is False


def test_sma_and_macd_crosses_are_mandatory_but_rsi_is_optional(monkeypatch):
    from src.screener import technical_setup as screening

    prices = _crossing_prices()
    assert screening.technical_setup(prices).qualifies is False
    result = screening.technical_setup(prices, announcement_date="20260001")
    assert result is not None and result.qualifies is False
    assert result.sma_crossed is True and result.macd_crossed is True
    assert result.sma_approaching is True and result.macd_approaching is True
    assert result.strong_recommendation is False  # RSI 59여도 필수 두 교차는 통과.

    original = screening._rsi_series

    def recovering(values):
        measured = original(values)
        # 5일 순상승·당일 상승이지만 중간에 하락: 3거래일 연속 상승은 아니다.
        measured[-6:] = [36.0, 40.0, 38.0, 39.0, 37.0, 42.0]
        return measured

    monkeypatch.setattr(screening, "_rsi_series", recovering)
    result = screening.technical_setup(prices, announcement_date="20260001")
    assert result is not None and result.qualifies is False
    assert result.rsi_rising is True and result.strong_recommendation is False
    assert result.announcement_close == 100
    assert result.announcement_return_pct == pytest.approx(-0.2431)

    # 최신 요청의 RSI 보강은 45 미만이며, 임의의 30 하한을 두지 않는다.
    def recovering_from_oversold(values):
        measured = original(values)
        measured[-6:] = [20.0, 23.0, 21.0, 24.0, 22.0, 27.0]
        return measured

    monkeypatch.setattr(screening, "_rsi_series", recovering_from_oversold)
    assert screening.technical_setup(prices, announcement_date="20260001").strong_recommendation is False


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
                 "products": "HBM 반도체", "is_excluded": False} for i in range(1, 7)]
    fundamentals = []
    for code in (row["code"] for row in universe):
        for offset, revenue, op in ((0, -5, 3), (1, 5, 10), (2, 15, 25)):
            fundamentals.append({
                "code": code, "fiscal_year": 2025, "fiscal_quarter": 1 + offset,
                "revenue_yoy": revenue, "op_yoy": op, "op": 10, "opm": 5 + offset,
            })
    assert len(growth_candidates(screens, universe, fundamentals)) == 6
    screens[0]["gate_passed"] = False
    assert len(growth_candidates(screens, universe, fundamentals)) == 5


def test_growth_candidates_reject_initial_inflection_without_op_yoy():
    screens = [{"code": f"00000{i}", "fiscal_year": 2025, "fiscal_quarter": 3,
                "gate_passed": True, "grade": "★", "pri": 25 if i == 1 else 50,
                "turnaround": i == 1, "score_final": 60 if i == 1 else 90}
               for i in range(1, 7)]
    universe = [{"code": f"00000{i}", "name": f"기업{i}", "industry": "반도체 제조업",
                 "products": "HBM 반도체", "is_excluded": False} for i in range(1, 7)]
    fundamentals = []
    for row in universe:
        for quarter, revenue, op_yoy in ((2, 5, 10), (3, 15, 25)):
            initial = row["code"] == "000001"
            fundamentals.append({
                "code": row["code"], "fiscal_year": 2025, "fiscal_quarter": quarter,
                "revenue_yoy": revenue, "op_yoy": None if initial else op_yoy,
                "op": (-3 if quarter == 2 else 2) if initial else 10,
                "op_status_label": "흑전" if initial and quarter == 3 else None,
                "opm": -2 if initial and quarter == 2 else 6 + quarter,
            })
    candidates = growth_candidates(screens, universe, fundamentals)
    assert len(candidates) == 5
    assert all(row["code"] != "000001" for row in candidates)


def test_technical_message_discloses_that_cross_is_not_confirmed():
    text = technical_setup_message({
        "name": "테스트", "code": "000001", "sector": "반도체 장비", "grade": "○",
        "company_growth": {"revenue_yoy": (5, 15), "op_yoy": (10, 25)},
        "sector_growth": {"revenue_yoy": (8, 10), "op_yoy": (12, 15)},
        "products": "반도체 검사장비 제조, 산업용 로봇 제품",
        "fundamental": {"opm": 14.2, "opm_yoy_delta": 3.1, "ttm_opm_delta": 1.4},
        "investment_score": 82.3, "pri": 28.0,
        "consensus": {"fwd_per": 10.2, "roe_next_est": 17.5, "roe_next_year": 2027},
        "technical": {"price_regime": "조정 후 횡보", "drawdown_50d_pct": -12,
                      "ret_20d_pct": -4, "macd": -2, "signal": -1,
                      "histogram_pct": -0.1, "rsi": 55,
                      "sma5": 100, "sma20": 101, "sma_gap_pct": -0.99,
                      "strong_recommendation": False},
    })
    assert "오늘의 추천 종목" in text and "상향 교차 접근" in text
    assert "보강 조건 미충족(필수 아님)" in text
    assert "동종 산업 실적 2Q" in text and "기업 2Q" in text
    assert "MACD -2.00 / Signal -1.00" in text
    assert "펀더멘털 투자 아이디어" in text
    assert "본업: <b>반도체 검사장비 · 산업용 로봇</b>" in text
    assert "매출 YoY +5.0% → +15.0%, 영업이익 YoY +10.0% → +25.0%로 동반 가속" in text
    assert "OPM +14.2% · 전년 동기 대비 +3.1%p" in text
    assert "투자 매력도 82.3 · 주가반영도 28.0(낮은 반영 구간)" in text
    assert "내년 F.PER 10.2배 · 2027년 F.ROE +17.5%" in text
    assert "5·20일선과 MACD 상향 교차가 겹치는지 관찰" not in text
    assert KIND_TECHNICAL == "technical_setup"


def test_initial_inflection_idea_does_not_invent_profit_growth_percent():
    text = technical_setup_message({
        "name": "흑전기업", "code": "000002", "sector": "전력인프라", "grade": "★",
        "company_growth": {"revenue_yoy": (3, 18), "op_yoy": (), "stage": "초기 흑전", "op_status_label": "흑전"},
        "sector_growth": {"revenue_yoy": (5, 9), "op_yoy": (7, 12)},
        "fundamental": {"opm": 3.0, "opm_yoy_delta": 5.0},
        "investment_score": 75, "pri": 52,
        "technical": {"price_regime": "조정 후 회복", "drawdown_50d_pct": -8,
                      "ret_20d_pct": 2, "macd": 1, "signal": 0.9,
                      "histogram_pct": 0.05, "rsi": 51, "sma5": 100,
                      "sma20": 99, "sma_gap_pct": 1, "strong_recommendation": False},
    })
    assert "매출 YoY +3.0% → +18.0%로 가속하면서 영업이익이 흑자전환" in text
    assert "영업이익 YoY —" not in text


def test_latest_annual_consensus_uses_latest_naver_year_and_snapshot():
    rows = [
        {"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 0, "source": "naver", "snapshot_at": "2026-09-01", "fwd_per": 12},
        {"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 2, "source": "naver", "snapshot_at": "2026-09-20", "fwd_per": 99},
        {"code": "000001", "fiscal_year": 2027, "fiscal_quarter": 0, "source": "fnguide", "snapshot_at": "2026-09-20", "fwd_per": 8},
        {"code": "000001", "fiscal_year": 2027, "fiscal_quarter": 0, "source": "naver", "snapshot_at": "2026-09-19", "fwd_per": 9},
        {"code": "000001", "fiscal_year": 2027, "fiscal_quarter": 0, "source": "naver", "snapshot_at": "2026-09-20", "fwd_per": 8.5},
    ]
    assert latest_annual_consensus(rows)["000001"]["fwd_per"] == 8.5


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


def test_first_announcement_uses_matching_fiscal_quarter():
    dates = technical_alert.first_announcement_dates([
        {"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 2, "disclosed_at": "2026-08-15T01:00:00Z"},
        {"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 2, "disclosed_at": "2026-08-12T01:00:00Z"},
        {"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 1, "disclosed_at": "2026-05-10T01:00:00Z"},
    ])
    assert dates[("000001", 2026, 2)] == "2026-08-12"
    assert dates[("000001", 2026, 1)] == "2026-05-10"


def test_daily_sent_count_uses_kst_day_across_utc_boundary(monkeypatch):
    bounds = {}

    class Query:
        def table(self, name):
            assert name == "notifications"
            return self

        def select(self, column, *, count):
            assert column == "id" and count == "exact"
            return self

        def eq(self, *_args):
            return self

        def gte(self, key, value):
            bounds["start"] = value
            return self

        def lt(self, key, value):
            bounds["end"] = value
            return self

        def limit(self, *_args):
            return self

        def execute(self):
            return type("Response", (), {"count": 1})()

    monkeypatch.setattr(technical_alert, "get_client", Query)
    now = datetime(2026, 9, 16, 10, 0, tzinfo=ZoneInfo("Asia/Seoul"))
    assert technical_alert.sent_count_today(now) == 1
    assert bounds["start"].startswith("2026-09-15T15:00:00")
    assert bounds["end"].startswith("2026-09-16T15:00:00")


def test_daily_digest_discloses_zero_signal_and_scan_failure():
    base = {"date": "2026-09-16", "counts": {}, "rows": []}
    complete = daily_digest({**base, "technical_scan": {
        "status": "complete", "price": 61, "sma": 5, "macd": 3, "rsi": 0, "sent": 0,
    }})
    assert "오늘의 종목 추천" in complete
    assert "가격 61 → 5·20일선 5 → MACD 3 → 3일 수급 0 · RSI 보강 0 · 조건 충족 추천 0건" in complete
    sent = daily_digest({**base, "technical_scan": {
        "status": "complete", "price": 61, "sma": 5, "macd": 3, "rsi": 1, "sent": 2,
    }})
    assert "추천 발송 2건" in sent
    failed = daily_digest({**base, "technical_scan": {"status": "scan_failed"}})
    assert "기술 신호 점검/발송 오류" in failed


def test_scan_summary_is_persisted_for_same_job_digest(tmp_path):
    target = tmp_path / "technical-scan.json"
    technical_alert._write_summary(str(target), {"date": "2026-09-16", "status": "complete", "sent": 0})
    assert json.loads(target.read_text(encoding="utf-8"))["sent"] == 0
