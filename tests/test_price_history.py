# PRD Ref: §5.4, §7.1 · traps.md T101, T115
"""LLM 주가 궤적의 current-price 계약을 순수 함수로 검증한다."""

from __future__ import annotations

import pytest

from src.finance.price_history import (
    PriceHistoryConflict,
    canonicalize_price_history,
)


_ROWS = [
    {
        "code": "097230",
        "fiscal_year": 2026,
        "fiscal_quarter": 2,
        "close": 20_150.0,
        "trade_date": "2026-06-30",
    },
    {
        "code": "097230",
        "fiscal_year": 2026,
        "fiscal_quarter": 3,
        "close": 17_120.0,
        "trade_date": "2026-08-27",
    },
]


def test_current_snapshot_replaces_same_quarter_naver_row():
    result = canonicalize_price_history(
        _ROWS,
        {"code": "097230", "snap_date": "2026-08-27", "close": 17_160.0},
    )

    assert len(result) == 2
    assert result[-1] == {
        "code": "097230",
        "fiscal_year": 2026,
        "fiscal_quarter": 3,
        "close": 17_160.0,
        "trade_date": "2026-08-27",
        "is_current": True,
        "source": "price_snapshots",
    }
    assert all(row["close"] != 17_120.0 for row in result)


def test_snapshot_appends_current_quarter_after_last_completed_quarter():
    result = canonicalize_price_history(
        _ROWS[:1],
        {"code": "097230", "snap_date": "2026-08-27", "close": 17_160.0},
    )

    assert [(row["fiscal_year"], row["fiscal_quarter"]) for row in result] == [
        (2026, 2),
        (2026, 3),
    ]
    assert result[-1]["is_current"] is True


def test_newer_naver_trade_date_than_snapshot_is_rejected():
    with pytest.raises(PriceHistoryConflict, match="더 최신"):
        canonicalize_price_history(
            _ROWS,
            {"code": "097230", "snap_date": "2026-08-26", "close": 17_160.0},
        )


def test_missing_snapshot_does_not_label_history_as_current():
    result = canonicalize_price_history(_ROWS, {})

    assert len(result) == 2
    assert all(row["is_current"] is False for row in result)
