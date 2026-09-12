# PRD Ref: §8.6 — 산업·기업 성장 지속 + 일봉 MACD 상향 접근
"""기술적 매수 관찰 신호 — 순수 함수. 외부 I/O 금지.

선별 순서는 펀더멘털 → 가격 조정 → MACD/RSI다. MACD만으로 종목을 고르면
횡보하는 모든 종목에서 신호가 반복되므로 산업과 기업 성장 지속을 먼저 요구한다.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from src.config.constants import (
    TECHNICAL_COMPANY_GROWTH_QUARTERS,
    TECHNICAL_CORRECTION_DRAWDOWN_MAX_PCT,
    TECHNICAL_FALLING_RET_20D_RANGE_PCT,
    TECHNICAL_MACD_GAP_MAX_ABS_PCT,
    TECHNICAL_MACD_RISING_DAYS,
    TECHNICAL_RSI_MAX,
    TECHNICAL_RSI_RISING_DAYS,
    TECHNICAL_SECTOR_GROWTH_QUARTERS,
    TECHNICAL_SECTOR_MIN_MEMBERS,
    TECHNICAL_SIDEWAYS_RANGE_10D_MAX_PCT,
    TECHNICAL_SIDEWAYS_RET_10D_ABS_MAX_PCT,
)


@dataclass(frozen=True)
class CompanyGrowth:
    revenue_yoy: tuple[float, ...]
    op_yoy: tuple[float, ...]


@dataclass(frozen=True)
class SectorGrowth:
    revenue_yoy: tuple[float, ...]
    op_yoy: tuple[float, ...]
    members: tuple[int, ...]


@dataclass(frozen=True)
class TechnicalSetup:
    qualifies: bool
    as_of: str
    close: float
    macd: float
    signal: float
    histogram: float
    histogram_pct: float
    rsi: float
    ret_20d_pct: float
    ret_10d_pct: float
    drawdown_50d_pct: float
    range_10d_pct: float
    price_regime: str | None


def _number(row: dict, key: str) -> float | None:
    value = row.get(key)
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def company_growth_streak(
    series: dict[int, dict],
    current_index: int,
    quarters: int = TECHNICAL_COMPANY_GROWTH_QUARTERS,
) -> CompanyGrowth | None:
    """매출·영업이익 YoY가 각각 `quarters`개 분기 연속 엄격히 개선됐는가."""
    ordered = [series.get(current_index - offset) for offset in reversed(range(quarters))]
    if any(row is None for row in ordered):
        return None
    revenue = tuple(_number(row or {}, "revenue_yoy") for row in ordered)
    op = tuple(_number(row or {}, "op_yoy") for row in ordered)
    if any(value is None for value in (*revenue, *op)):
        return None
    revenue_values = tuple(float(value) for value in revenue if value is not None)
    op_values = tuple(float(value) for value in op if value is not None)
    if not all(left < right for left, right in zip(revenue_values, revenue_values[1:])):
        return None
    if not all(left < right for left, right in zip(op_values, op_values[1:])):
        return None
    current = ordered[-1] or {}
    if (_number(current, "op") or 0) <= 0:
        return None
    return CompanyGrowth(revenue_values, op_values)


def sector_growth_continuity(
    member_series: list[dict[int, dict]],
    current_index: int,
    quarters: int = TECHNICAL_SECTOR_GROWTH_QUARTERS,
    min_members: int = TECHNICAL_SECTOR_MIN_MEMBERS,
) -> SectorGrowth | None:
    """같은 섹터의 매출·영업익 YoY 중앙값이 여러 분기 연속 양수인지 판정한다."""
    revenue_medians: list[float] = []
    op_medians: list[float] = []
    member_counts: list[int] = []
    for offset in reversed(range(quarters)):
        measured = []
        for series in member_series:
            row = series.get(current_index - offset) or {}
            revenue, op = _number(row, "revenue_yoy"), _number(row, "op_yoy")
            if revenue is not None and op is not None:
                measured.append((revenue, op))
        if len(measured) < min_members:
            return None
        revenue_median = float(statistics.median(value[0] for value in measured))
        op_median = float(statistics.median(value[1] for value in measured))
        if revenue_median <= 0 or op_median <= 0:
            return None
        revenue_medians.append(revenue_median)
        op_medians.append(op_median)
        member_counts.append(len(measured))
    return SectorGrowth(tuple(revenue_medians), tuple(op_medians), tuple(member_counts))


def _ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    current = sum(values[:period]) / period
    out[period - 1] = current
    alpha = 2 / (period + 1)
    for index in range(period, len(values)):
        current = values[index] * alpha + current * (1 - alpha)
        out[index] = current
    return out


def _rsi_series(values: list[float], periods: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < periods + 1:
        return out
    changes = [current - previous for previous, current in zip(values, values[1:])]
    gains = sum(max(value, 0.0) for value in changes[:periods]) / periods
    losses = sum(max(-value, 0.0) for value in changes[:periods]) / periods
    def value() -> float:
        if losses == 0:
            return 50.0 if gains == 0 else 100.0
        return 100.0 - 100.0 / (1.0 + gains / losses)
    out[periods] = value()
    for index, change in enumerate(changes[periods:], periods + 1):
        gains = (gains * (periods - 1) + max(change, 0.0)) / periods
        losses = (losses * (periods - 1) + max(-change, 0.0)) / periods
        out[index] = value()
    return out


def _rsi(values: list[float], periods: int = 14) -> float | None:
    measured = _rsi_series(values, periods)
    return measured[-1] if measured else None


def _return(values: list[float], sessions: int) -> float:
    return (values[-1] / values[-sessions - 1] - 1.0) * 100.0


def technical_setup(closes: dict[str, float]) -> TechnicalSetup | None:
    """MACD가 Signal 아래에서 위로 붙는 조정/횡보 종목인지 판정한다.

    손계산 기준: histogram은 `MACD − Signal`. 아직 음수지만 3거래일 연속
    커지고 0에 가까우면 상향 크로스 '직전'이며, 0 이상은 이미 크로스한 뒤다.
    """
    clean: dict[str, float] = {}
    for day, value in closes.items():
        if value is None or isinstance(value, bool):
            continue
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            clean[str(day)] = parsed
    days = sorted(clean)
    values = [clean[day] for day in days]
    if len(values) < 60:
        return None

    fast, slow = _ema(values, 12), _ema(values, 26)
    macd = [
        (float(fast[index]) - float(slow[index]))
        if fast[index] is not None and slow[index] is not None else None
        for index in range(len(values))
    ]
    measured_macd = [float(value) for value in macd if value is not None]
    measured_signal = _ema(measured_macd, 9)
    signal: list[float | None] = []
    signal_index = 0
    for value in macd:
        if value is None:
            signal.append(None)
        else:
            signal.append(measured_signal[signal_index])
            signal_index += 1
    histogram = [
        (float(macd[index]) - float(signal[index]))
        if macd[index] is not None and signal[index] is not None else None
        for index in range(len(values))
    ]
    measured_indices = [index for index, value in enumerate(histogram) if value is not None]
    if len(measured_indices) < TECHNICAL_MACD_RISING_DAYS:
        return None
    recent_indices = measured_indices[-TECHNICAL_MACD_RISING_DAYS:]
    recent_hist = [float(histogram[index]) for index in recent_indices if histogram[index] is not None]
    latest = recent_indices[-1]
    previous = recent_indices[-2]
    latest_macd, latest_signal = macd[latest], signal[latest]
    rsi_values = _rsi_series(values)
    latest_rsi = rsi_values[-1] if rsi_values else None
    if latest_macd is None or latest_signal is None or latest_rsi is None:
        return None

    close = values[-1]
    histogram_pct = recent_hist[-1] / close * 100.0
    ret_20d, ret_10d = _return(values, 20), _return(values, 10)
    high_50d = max(values[-50:])
    drawdown_50d = (close / high_50d - 1.0) * 100.0
    last_10 = values[-10:]
    range_10d = (max(last_10) / min(last_10) - 1.0) * 100.0
    falling_floor, falling_ceiling = TECHNICAL_FALLING_RET_20D_RANGE_PCT
    corrected = drawdown_50d <= TECHNICAL_CORRECTION_DRAWDOWN_MAX_PCT
    falling = corrected and falling_floor <= ret_20d < falling_ceiling
    sideways = (
        corrected
        and abs(ret_10d) <= TECHNICAL_SIDEWAYS_RET_10D_ABS_MAX_PCT
        and range_10d <= TECHNICAL_SIDEWAYS_RANGE_10D_MAX_PCT
    )
    previous_macd = macd[previous]
    approaching = (
        recent_hist[-1] < 0
        and histogram_pct >= -TECHNICAL_MACD_GAP_MAX_ABS_PCT
        and all(left < right for left, right in zip(recent_hist, recent_hist[1:]))
        and previous_macd is not None
        and float(latest_macd) > float(previous_macd)
    )
    # RSI 50 이하의 회복 초입만 관찰한다. 50 초과는 이미 반등이 진행됐을 수 있다.
    recent_rsi = [
        float(value) for value in rsi_values[-TECHNICAL_RSI_RISING_DAYS:]
        if value is not None
    ]
    not_overheated = (
        latest_rsi <= TECHNICAL_RSI_MAX
        and len(recent_rsi) == TECHNICAL_RSI_RISING_DAYS
        and all(left < right for left, right in zip(recent_rsi, recent_rsi[1:]))
    )
    regime = "하락 중 반등 접근" if falling else "조정 후 횡보" if sideways else None
    return TechnicalSetup(
        qualifies=bool(regime and approaching and not_overheated),
        as_of=days[-1], close=close,
        macd=float(latest_macd), signal=float(latest_signal),
        histogram=recent_hist[-1], histogram_pct=histogram_pct,
        rsi=latest_rsi, ret_20d_pct=ret_20d, ret_10d_pct=ret_10d,
        drawdown_50d_pct=drawdown_50d, range_10d_pct=range_10d,
        price_regime=regime,
    )
