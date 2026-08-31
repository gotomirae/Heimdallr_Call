# PRD Ref: §9.1-3 — 실제 주간 주가 차트
from src.collectors.quarter_prices import weekly_last_closes
from datetime import date, timedelta

from src.finance.backfill import preliminary_delta, recent_periodic_targets


def test_weekly_last_closes_uses_actual_last_trading_day():
    closes = {
        "20260803": 100.0,
        "20260807": 110.0,
        "20260810": 120.0,
        "20260814": 130.0,
    }
    assert weekly_last_closes(closes) == {
        "20260807": 110.0,
        "20260814": 130.0,
    }


def test_final_numbers_preserve_delta_from_preliminary():
    result = preliminary_delta(
        {"is_estimate": True, "revenue": 100, "op": 10, "np": -3},
        {"revenue": 110, "op": 12, "np": 2},
    )
    assert result["revenue"]["delta_pct"] == 10
    assert result["op"]["delta"] == 2
    assert "delta_pct" not in result["np"]  # 적자↔흑자에 성장률을 만들지 않는다


def test_recent_periodic_targets_skip_already_refreshed_final(monkeypatch):
    disclosed = (date.today() - timedelta(days=1)).isoformat()
    rows = {
        "earnings_disclosures": [
            {"code": "000001", "doc_type": "periodic", "fiscal_year": 2026,
             "fiscal_quarter": 2, "disclosed_at": disclosed},
            {"code": "000002", "doc_type": "periodic", "fiscal_year": 2026,
             "fiscal_quarter": 2, "disclosed_at": disclosed},
        ],
        "quarterly_fundamentals": [
            {"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 2,
             "is_estimate": False, "updated_at": date.today().isoformat()},
            {"code": "000002", "fiscal_year": 2026, "fiscal_quarter": 2,
             "is_estimate": True, "updated_at": date.today().isoformat()},
        ],
    }
    monkeypatch.setattr(
        "src.finance.backfill.select_all", lambda table, columns: rows[table]
    )
    targets = recent_periodic_targets(3)
    assert [row["code"] for row in targets] == ["000002"]
