# PRD Ref: §8.6 — 산업·기업 성장 지속 + 일봉 MACD 상향 접근
"""기술적 매수 관찰 신호 — 순수 함수. 외부 I/O 금지.

펀더멘털·주가 미반영을 먼저 확인하고 5·20일선과 MACD 상향 교차 접근을 본다.
RSI 회복은 필수가 아니라 강력 추천 표시를 위한 보강 근거다.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from src.config.constants import (
    TECHNICAL_COMPANY_GROWTH_QUARTERS,
    TECHNICAL_FALLING_RET_20D_RANGE_PCT,
    TECHNICAL_MACD_GAP_MAX_ABS_PCT,
    TECHNICAL_MIN_HIGH_DRAWDOWN_PCT,
    TECHNICAL_POST_ANNOUNCEMENT_CORRECTION_PCT,
    TECHNICAL_RSI_STRONG_MAX,
    TECHNICAL_RSI_TREND_DAYS,
    TECHNICAL_SECTOR_GROWTH_QUARTERS,
    TECHNICAL_SECTOR_MIN_MEMBERS,
    TECHNICAL_SIDEWAYS_RANGE_10D_MAX_PCT,
    TECHNICAL_SIDEWAYS_RET_10D_ABS_MAX_PCT,
    TECHNICAL_SMA_GAP_MAX_ABS_PCT,
)


@dataclass(frozen=True)
class CompanyGrowth:
    revenue_yoy: tuple[float, ...]
    op_yoy: tuple[float | None, ...]
    opm: tuple[float, ...] = ()
    stage: str = "지속 가속"
    op_status_label: str | None = None


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
    drawdown_52w_pct: float
    range_10d_pct: float
    price_regime: str | None
    announcement_date: str | None
    announcement_close: float | None
    announcement_return_pct: float | None
    post_announcement_drawdown_pct: float | None
    sma5: float
    sma20: float
    sma_gap_pct: float
    sma_approaching: bool
    sma_crossed: bool
    macd_approaching: bool
    macd_crossed: bool
    rsi_rising: bool
    strong_recommendation: bool


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
    opm = tuple(_number(row or {}, "opm") for row in ordered)
    if not all(left < right for left, right in zip(revenue_values, revenue_values[1:])):
        return None
    if not all(left < right for left, right in zip(op_values, op_values[1:])):
        return None
    if any(value is None for value in opm):
        return None
    opm_values = tuple(float(value) for value in opm if value is not None)
    if opm_values[-1] <= opm_values[-2]:
        return None
    current = ordered[-1] or {}
    if (_number(current, "op") or 0) <= 0:
        return None
    return CompanyGrowth(revenue_values, op_values, opm_values)


def company_initial_inflection(
    series: dict[int, dict], current_index: int
) -> CompanyGrowth | None:
    """전년 적자→당기 흑자와 매출 가속이 동시에 확인된 첫 분기를 찾는다.

    부호 전환 구간의 영업이익 성장률은 %로 만들지 않는다(T12). 수주 증가는
    여기서 추정하지 않으며 별도 공시 확인 사항으로 남긴다.
    """
    previous, current = series.get(current_index - 1), series.get(current_index)
    if not previous or not current or current.get("op_status_label") != "흑전":
        return None
    prior_revenue, revenue = _number(previous, "revenue_yoy"), _number(current, "revenue_yoy")
    prior_op, op = _number(previous, "op"), _number(current, "op")
    if (
        prior_revenue is None or revenue is None or prior_op is None or op is None
        or revenue <= 0 or revenue <= prior_revenue or prior_op > 0 or op <= 0
    ):
        return None
    return CompanyGrowth(
        revenue_yoy=(prior_revenue, revenue),
        op_yoy=(), stage="초기 흑전", op_status_label="흑전",
    )


def sector_growth_continuity(
    member_series: list[dict[int, dict]],
    current_index: int,
    quarters: int = TECHNICAL_SECTOR_GROWTH_QUARTERS,
    min_members: int = TECHNICAL_SECTOR_MIN_MEMBERS,
) -> SectorGrowth | None:
    """같은 섹터의 매출·영업익 YoY 중앙값이 양수이며 매 분기 상승하는지 판정한다."""
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
    if not all(a < b for a, b in zip(revenue_medians, revenue_medians[1:])):
        return None
    if not all(a < b for a, b in zip(op_medians, op_medians[1:])):
        return None
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


def technical_setup(
    closes: dict[str, float], *, announcement_date: str | None = None
) -> TechnicalSetup | None:
    """5·20일선과 MACD의 상향 교차 직전 또는 당일을 판정한다.

    손계산 기준: gap은 5일선−20일선, histogram은 MACD−Signal이다.
    두 값 모두 음수권에서 좁혀지거나 직전 음수→당일 양수 교차해야 한다.
    3거래일 연속 상승은 요구하지 않는다.
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
    if len(measured_indices) < 2:
        return None
    recent_indices = measured_indices[-2:]
    recent_hist = [float(histogram[index]) for index in recent_indices if histogram[index] is not None]
    latest = recent_indices[-1]
    previous = recent_indices[-2]
    latest_macd, latest_signal = macd[latest], signal[latest]
    rsi_values = _rsi_series(values)
    latest_rsi = rsi_values[-1] if rsi_values else None
    if latest_macd is None or latest_signal is None or latest_rsi is None:
        return None

    close = values[-1]
    announcement_close: float | None = None
    announcement_return_pct: float | None = None
    post_announcement_drawdown_pct: float | None = None
    post_announcement_corrected = False
    if announcement_date:
        announcement_key = announcement_date.replace("-", "")[:8]
        post_values = [clean[day] for day in days if day > announcement_key]
        if post_values and announcement_key >= days[0]:
            announcement_close = post_values[0]
            announcement_return_pct = (close / announcement_close - 1.0) * 100.0
            post_announcement_drawdown_pct = (
                close / max(post_values) - 1.0
            ) * 100.0
            post_announcement_corrected = (
                post_announcement_drawdown_pct
                <= TECHNICAL_POST_ANNOUNCEMENT_CORRECTION_PCT
            )
    histogram_pct = recent_hist[-1] / close * 100.0
    sma5 = sum(values[-5:]) / 5
    sma20 = sum(values[-20:]) / 20
    previous_sma5 = sum(values[-6:-1]) / 5
    previous_sma20 = sum(values[-21:-1]) / 20
    sma_gap_pct = (sma5 / sma20 - 1.0) * 100.0
    previous_sma_gap_pct = (previous_sma5 / previous_sma20 - 1.0) * 100.0
    sma_crossed = previous_sma_gap_pct < 0 <= sma_gap_pct
    sma_approaching = (
        sma5 > previous_sma5
        and (
            (-TECHNICAL_SMA_GAP_MAX_ABS_PCT <= sma_gap_pct < 0
             and sma_gap_pct > previous_sma_gap_pct)
            or sma_crossed
        )
    )
    ret_20d, ret_10d = _return(values, 20), _return(values, 10)
    high_50d = max(values[-50:])
    drawdown_50d = (close / high_50d - 1.0) * 100.0
    high_52w = max(values[-252:])
    drawdown_52w = (close / high_52w - 1.0) * 100.0
    last_10 = values[-10:]
    range_10d = (max(last_10) / min(last_10) - 1.0) * 100.0
    falling_floor, falling_ceiling = TECHNICAL_FALLING_RET_20D_RANGE_PCT
    below_announcement = (
        announcement_return_pct is not None and announcement_return_pct < 0
    )
    deep_correction = min(
        drawdown_52w,
        post_announcement_drawdown_pct if post_announcement_drawdown_pct is not None else 0.0,
    ) <= TECHNICAL_MIN_HIGH_DRAWDOWN_PCT
    falling = deep_correction and (below_announcement or post_announcement_corrected) and falling_floor <= ret_20d < falling_ceiling
    sideways = (
        deep_correction and (below_announcement or post_announcement_corrected)
        and abs(ret_10d) <= TECHNICAL_SIDEWAYS_RET_10D_ABS_MAX_PCT
        and range_10d <= TECHNICAL_SIDEWAYS_RANGE_10D_MAX_PCT
    )
    previous_macd = macd[previous]
    macd_crossed = recent_hist[-2] < 0 <= recent_hist[-1]
    approaching = (
        previous_macd is not None
        and float(latest_macd) > float(previous_macd)
        and (
            (-TECHNICAL_MACD_GAP_MAX_ABS_PCT <= histogram_pct < 0
             and recent_hist[-1] > recent_hist[-2])
            or macd_crossed
        )
    )
    # RSI 45 미만에서 단기·5거래일 방향이 함께 위면 강력 보강. 연속 상승은 요구하지 않는다.
    prior_rsi = rsi_values[-TECHNICAL_RSI_TREND_DAYS - 1]
    yesterday_rsi = rsi_values[-2]
    rsi_rising = (
        latest_rsi < TECHNICAL_RSI_STRONG_MAX
        and prior_rsi is not None and yesterday_rsi is not None
        and latest_rsi > float(prior_rsi)
        and latest_rsi > float(yesterday_rsi)
    )
    # 5·20일선 상향 접근에는 이미 며칠간 반등한 경우가 많다. 가격이 여전히
    # 실적 발표 직후보다 낮거나 발표 후 고점에서 조정 중이면 회복 구간도 허용한다.
    price_underreflected = (below_announcement or post_announcement_corrected) and deep_correction
    regime = (
        "하락 중 반등 접근" if falling else
        "조정 후 횡보" if sideways else
        "조정 후 회복" if price_underreflected else None
    )
    qualifies = bool(regime and sma_approaching and approaching)
    return TechnicalSetup(
        qualifies=qualifies,
        as_of=days[-1], close=close,
        macd=float(latest_macd), signal=float(latest_signal),
        histogram=recent_hist[-1], histogram_pct=histogram_pct,
        rsi=latest_rsi, ret_20d_pct=ret_20d, ret_10d_pct=ret_10d,
        drawdown_50d_pct=drawdown_50d, drawdown_52w_pct=drawdown_52w,
        range_10d_pct=range_10d,
        price_regime=regime,
        announcement_date=announcement_date,
        announcement_close=announcement_close,
        announcement_return_pct=announcement_return_pct,
        post_announcement_drawdown_pct=post_announcement_drawdown_pct,
        sma5=sma5, sma20=sma20, sma_gap_pct=sma_gap_pct,
        sma_approaching=sma_approaching, sma_crossed=sma_crossed,
        macd_approaching=approaching,
        macd_crossed=macd_crossed,
        rsi_rising=rsi_rising,
        strong_recommendation=qualifies and rsi_rising,
    )
