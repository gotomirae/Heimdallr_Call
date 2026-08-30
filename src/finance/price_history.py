# PRD Ref: §5.4, §7.1 · traps.md T101, T115
"""LLM 주가 시계열의 canonical current-price 계약.

분기말 종가는 네이버 일봉, 현재가·PRI·52주 위치는 KIS 기반 price snapshot에서 온다.
두 Source를 그대로 병기하지 않고 현재 분기 마지막 행을 snapshot 값으로 정규화한다.
"""

from __future__ import annotations

from datetime import date
from typing import Any


class PriceHistoryConflict(ValueError):
    """Source의 날짜·종목 계약이 충돌해 안전하게 하나를 고를 수 없음."""


def _day(value: Any, *, field: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError) as exc:
        raise PriceHistoryConflict(f"{field}={value!r}: YYYY-MM-DD 날짜가 아니다") from exc


def _quarter(day: date) -> tuple[int, int]:
    return day.year, (day.month - 1) // 3 + 1


def canonicalize_price_history(
    quarter_prices: list[dict],
    price_snapshot: dict | None,
) -> list[dict]:
    """과거 분기말 종가와 canonical 현재가를 한 시계열로 만든다.

    `price_snapshots`는 PRI·52주 위치와 함께 수집된 현재 시점 계약이므로 현재 분기 행의
    단일 출처로 쓴다. `quarter_prices`가 오히려 더 최신이면 값을 추측하지 않고 차단한다.
    """
    rows: list[dict] = []
    periods: set[tuple[int, int]] = set()
    for original in quarter_prices:
        row = dict(original)
        try:
            period = (int(row["fiscal_year"]), int(row["fiscal_quarter"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise PriceHistoryConflict("quarter_prices의 연도·분기가 유효하지 않다") from exc
        if period in periods:
            raise PriceHistoryConflict(f"quarter_prices 분기 중복: {period[0]}.{period[1]}Q")
        periods.add(period)
        row["is_current"] = False
        row.setdefault("source", "quarter_prices")
        rows.append(row)
    rows.sort(key=lambda row: (row["fiscal_year"], row["fiscal_quarter"]))

    snapshot = price_snapshot or {}
    close = snapshot.get("close", snapshot.get("current_price"))
    snap_date = snapshot.get("snap_date")
    if close is None or snap_date in (None, ""):
        return rows
    if isinstance(close, bool) or not isinstance(close, (int, float)) or close <= 0:
        raise PriceHistoryConflict(f"price_snapshots.close={close!r}: 양의 숫자가 아니다")

    current_day = _day(snap_date, field="price_snapshots.snap_date")
    snapshot_code = snapshot.get("code")
    for row in rows:
        row_code = row.get("code")
        if snapshot_code and row_code and row_code != snapshot_code:
            raise PriceHistoryConflict(
                f"주가 종목코드 불일치: quarter_prices={row_code}, "
                f"price_snapshots={snapshot_code}"
            )
        trade_date = row.get("trade_date")
        if trade_date and _day(trade_date, field="quarter_prices.trade_date") > current_day:
            raise PriceHistoryConflict(
                "quarter_prices가 price_snapshots보다 더 최신이다 — "
                "어느 값을 현재가로 쓸지 추측하지 않는다"
            )

    current_period = _quarter(current_day)
    if any(
        (row["fiscal_year"], row["fiscal_quarter"]) > current_period
        for row in rows
    ):
        raise PriceHistoryConflict("price snapshot 기준일 뒤의 분기 주가가 섞였다")

    # 현재 달력분기의 Naver 행은 제거하고 KIS snapshot 한 행으로 대체한다.
    rows = [
        row
        for row in rows
        if (row["fiscal_year"], row["fiscal_quarter"]) != current_period
    ]
    rows.append({
        "code": snapshot_code,
        "fiscal_year": current_period[0],
        "fiscal_quarter": current_period[1],
        "close": close,
        "trade_date": str(snap_date)[:10],
        "is_current": True,
        "source": "price_snapshots",
    })
    return rows
