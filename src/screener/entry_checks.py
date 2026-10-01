# PRD Ref: §8.8 — JARVIS 진입 필수 조건 M1·M2·M5 · 🔵 K1 실적 돌파 (JARVIS PRD §7.3·§7.4)
"""JARVIS가 읽는 `entry_checks` 판정 — **순수 함수. 외부 I/O 금지.**

임계값은 전부 `src/config/constants.py`의 `ENTRY_*`·`K1_*`이며 JARVIS
`rules.yaml > entry_core`·`breakout_watch.K1_kr`와 같은 값이다(T215).

판정값은 세 가지다. **`False`와 `None`을 구분한다**(CLAUDE.md 컨벤션).
  True  — 조건을 모두 확인했고 충족
  False — 확인된 조건 중 하나라도 불충족
  None  — 불충족은 없지만 측정하지 못한 조건이 있다(데이터 없음)

가격 조건은 **확정 종가 일봉**으로만 계산한다. `price_snapshots.close`는 수집
시각에 따라 장중가일 수 있어 쓰지 않는다(T216).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Sequence

from src.config.constants import (
    ENTRY_HIGH_LOOKBACK_SESSIONS,
    ENTRY_INVALIDATION_PB_SESSIONS,
    ENTRY_INVALIDATION_SW_SESSIONS,
    ENTRY_M1_ABS_RETURN_20D_MAX_PCT,
    ENTRY_M1_CONSECUTIVE_YOY_QUARTERS,
    ENTRY_M1_HIGH_52W_DRAWDOWN_MAX_PCT,
    ENTRY_M1_POST_EARNINGS_DRAWDOWN_MAX_PCT,
    ENTRY_M1_PRI_MAX,
    ENTRY_M1_RANGE_20D_MAX_PCT,
    ENTRY_M1_TTM_OP_GROWTH_MIN_PCT,
    ENTRY_M1_TTM_REVENUE_GROWTH_MIN_PCT,
    ENTRY_M2_ALLOW_CROSS_TODAY,
    ENTRY_M2_HIST_RISING_BARS_MIN,
    ENTRY_M2_MACD_PARAMS,
    ENTRY_M2_NEAR_CROSS_GAP_PCT_OF_CLOSE_MAX,
    ENTRY_M2_PROJECTED_BARS_TO_CROSS_MAX,
    ENTRY_M5_STREAK_DAYS,
    ENTRY_SIDEWAYS_SESSIONS,
    K1_CLOSE_LOCATION_MIN,
    K1_CLOSE_RETURN_MIN_PCT,
    K1_GAP_OPEN_MIN_PCT,
    K1_VOLUME_AVG_SESSIONS,
    K1_VOLUME_MULT_MIN,
    KOREA_MARKET_COMPLETED_HOUR_KST,
)

#: 부호 전환 라벨. 이 구간의 영업이익 YoY는 만들지 않으며(T12) M1은 탈락이다.
SIGN_CHANGE_LABELS = frozenset({"흑전", "적전", "적자축소", "적자확대"})
#: MACD(12,26,9) 히스토그램이 안정되는 최소 일봉 수. 기존 기술 신호와 같은 하한이다.
MIN_MACD_BARS = 60
#: 52주 고점 대비를 계산할 최소 일봉 수. 신규 상장의 짧은 고점을 52주 고점으로 부르지 않는다.
MIN_HIGH_LOOKBACK_BARS = 60


@dataclass(frozen=True)
class Bar:
    """확정 일봉 한 개. `date`는 'YYYYMMDD'."""

    date: str
    open: float | None
    high: float | None
    low: float | None
    close: float
    volume: float | None = None


def _num(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


def all_of(values: Iterable[bool | None]) -> bool | None:
    """AND 결합. False가 하나라도 있으면 False, 없고 None이 있으면 None."""
    seen_none = False
    for value in values:
        if value is False:
            return False
        if value is None:
            seen_none = True
    return None if seen_none else True


def any_of(values: Iterable[bool | None]) -> bool | None:
    """OR 결합. True가 하나라도 있으면 True, 없고 None이 있으면 None."""
    seen_none = False
    for value in values:
        if value is True:
            return True
        if value is None:
            seen_none = True
    return None if seen_none else False


def _change_pct(value: float, base: float) -> float:
    """(value − base) × 100 ÷ base. `value/base − 1`보다 경계가 정확하다:
    9,000/10,000 − 1 = −9.999…%라 '≤ −10%' 경계에서 조용히 탈락한다."""
    return (value - base) * 100.0 / base


def kst_date_key(value: date | datetime) -> str:
    return value.strftime("%Y%m%d")


def confirmed_bars(bars: Sequence[Bar], now_kst: datetime) -> list[Bar]:
    """장 마감 전 오늘 봉과 미래 봉을 버린다 — 확정 종가만 남긴다.

    네이버·KIS 일봉은 장중에도 오늘 봉을 '현재가'로 채워 준다. 그대로 쓰면
    20일 범위·MACD가 장중가로 계산돼 **실행 시각마다 다른 답**이 나온다(T216).
    """
    today = kst_date_key(now_kst)
    completed = now_kst.hour >= KOREA_MARKET_COMPLETED_HOUR_KST
    out = [
        bar for bar in sorted(bars, key=lambda item: item.date)
        if bar.close > 0 and (bar.date < today or (bar.date == today and completed))
    ]
    return out


# ═══ M1 — 재무(DB만으로) ════════════════════════════════════════════
def _yoy_positive(row: dict, key: str) -> bool | None:
    value = _num(row.get(key))
    if value is not None:
        return value > 0
    if key == "op_yoy" and row.get("op_status_label") in SIGN_CHANGE_LABELS:
        return False  # 부호 전환 구간은 YoY>0 연속으로 보지 않는다
    return None


def _ttm_growth(current: float | None, base: float | None, min_pct: float) -> tuple[bool | None, float | None]:
    if current is None or base is None:
        return None, None
    pct = _change_pct(current, base) if base > 0 else None
    if min_pct == 0.0:
        return current > base, pct
    if pct is None:
        return False, None  # 적자 기저 대비 %를 만들지 않는다(T12)
    return pct > min_pct, pct


def m1_fundamental(
    series: dict[int, dict],
    index: int,
    *,
    base_effect_warning: bool | None,
    annual_consensus: dict | None = None,
    prior_year_actual: tuple[float | None, float | None] | None = None,
) -> dict:
    """M1의 재무 부분. 반환 dict의 `pass`가 True/False/None이다.

    손계산(경계): rev_yoy [t-1, t] = [5, 12], op_yoy [t-1, t] = [8, 20], op(t)=10억,
    TTM 매출 1,050 > 1,000, TTM 영업익 120 > 100 → 모두 충족 → True.
    rev_yoy(t)=5=rev_yoy(t-1)이면 가속이 아니므로 False(엄격 부등호).
    """
    quarters = ENTRY_M1_CONSECUTIVE_YOY_QUARTERS
    rows = [series.get(index - offset) for offset in range(quarters)]  # [t, t-1, ...]
    current = rows[0] or {}
    previous = rows[1] or {}
    base_ttm = series.get(index - 4) or {}

    rev_yoy = [_num((row or {}).get("revenue_yoy")) for row in rows]
    op_yoy = [_num((row or {}).get("op_yoy")) for row in rows]
    yoy_checks = [
        _yoy_positive(row or {}, key) for row in rows for key in ("revenue_yoy", "op_yoy")
    ]
    op_now = _num(current.get("op"))
    op_positive = None if op_now is None else op_now > 0
    revenue_accel = (
        None if rev_yoy[0] is None or rev_yoy[1] is None else rev_yoy[0] > rev_yoy[1]
    )
    if op_yoy[0] is None or op_yoy[1] is None:
        # 부호 전환이면 '가속'을 말할 수 없다 → 탈락. 단순 결측은 판정 불가.
        labels = {current.get("op_status_label"), previous.get("op_status_label")}
        op_accel = False if labels & SIGN_CHANGE_LABELS else None
    else:
        op_accel = op_yoy[0] > op_yoy[1]
    ttm_rev_ok, ttm_rev_growth = _ttm_growth(
        _num(current.get("ttm_revenue")), _num(base_ttm.get("ttm_revenue")),
        ENTRY_M1_TTM_REVENUE_GROWTH_MIN_PCT,
    )
    ttm_op_ok, ttm_op_growth = _ttm_growth(
        _num(current.get("ttm_op")), _num(base_ttm.get("ttm_op")),
        ENTRY_M1_TTM_OP_GROWTH_MIN_PCT,
    )
    annual_ok = annual_consensus_ok(annual_consensus, prior_year_actual)
    base_effect_ok = None if base_effect_warning is None else base_effect_warning is False

    checks = {
        "yoy_positive_2q": all_of(yoy_checks),
        "op_positive": op_positive,
        "revenue_accelerating": revenue_accel,
        "op_accelerating": op_accel,
        "ttm_revenue_up": ttm_rev_ok,
        "ttm_op_up": ttm_op_ok,
        # 컨센서스가 '없으면' 통과다(rules.yaml use_annual_consensus_if_available).
        "annual_consensus": True if annual_ok is None else annual_ok,
        "no_base_effect_warning": base_effect_ok,
    }
    return {
        "pass": all_of(checks.values()),
        "rev_yoy": [_round(value, 2) for value in rev_yoy],
        "op_yoy": [_round(value, 2) for value in op_yoy],
        "op_positive": op_positive,
        "op_status_label": current.get("op_status_label"),
        "ttm_rev_growth": _round(ttm_rev_growth, 2),
        "ttm_op_growth": _round(ttm_op_growth, 2),
        "annual_consensus_ok": annual_ok,
        "base_effect_warning": base_effect_warning,
        "checks": checks,
    }


def annual_consensus_ok(
    consensus: dict | None, prior_year_actual: tuple[float | None, float | None] | None,
) -> bool | None:
    """올해(E) 매출·영업이익 > 전년 확정. 어느 한쪽이라도 없으면 None(=데이터 없음)."""
    if not consensus or not prior_year_actual:
        return None
    revenue_est, op_est = _num(consensus.get("revenue_est")), _num(consensus.get("op_est"))
    revenue_actual, op_actual = (_num(value) for value in prior_year_actual)
    if None in (revenue_est, op_est, revenue_actual, op_actual):
        return None
    return bool(revenue_est > revenue_actual and op_est > op_actual)


# ═══ M1 — 주가 미반영(확정 일봉) ════════════════════════════════════
def m1_price(
    bars: Sequence[Bar], *, announcement_date: str | None, pri: float | None,
) -> dict:
    """조정(PB) 또는 횡보(SW), 그리고 PRI < 50.

    손계산(경계): 발표 후 고점 10,000 → 종가 9,000 = −10.0% → PB 충족(≤ −10%).
    20거래일 종가 범위 100~112 = 12.0%, 20일 수익률 +5.0% → SW 충족(≤ 12, |·| ≤ 5).
    """
    closes = [bar.close for bar in bars]
    days = [bar.date for bar in bars]
    close = closes[-1] if closes else None

    post_high_drawdown: float | None = None
    if close is not None and announcement_date:
        key = announcement_date.replace("-", "")[:8]
        if days and key >= days[0]:
            post = [value for day, value in zip(days, closes) if day >= key]
            if post:
                post_high_drawdown = _change_pct(close, max(post))

    high_drawdown: float | None = None
    if close is not None and len(closes) >= MIN_HIGH_LOOKBACK_BARS:
        high_drawdown = _change_pct(close, max(closes[-ENTRY_HIGH_LOOKBACK_SESSIONS:]))

    sessions = ENTRY_SIDEWAYS_SESSIONS
    range_20d = ret_20d = None
    if len(closes) >= sessions + 1:
        window = closes[-sessions:]
        range_20d = _change_pct(max(window), min(window))
        ret_20d = _change_pct(closes[-1], closes[-sessions - 1])

    correction = any_of([
        None if post_high_drawdown is None
        else post_high_drawdown <= ENTRY_M1_POST_EARNINGS_DRAWDOWN_MAX_PCT,
        None if high_drawdown is None else high_drawdown <= ENTRY_M1_HIGH_52W_DRAWDOWN_MAX_PCT,
    ])
    sideways = (
        None if range_20d is None or ret_20d is None
        else range_20d <= ENTRY_M1_RANGE_20D_MAX_PCT
        and abs(ret_20d) <= ENTRY_M1_ABS_RETURN_20D_MAX_PCT
    )
    price_state = "PB" if correction is True else "SW" if sideways is True else None
    pri_value = _num(pri)
    pri_ok = None if pri_value is None else pri_value < ENTRY_M1_PRI_MAX
    return {
        "pass": all_of([any_of([correction, sideways]), pri_ok]),
        "drawdown_from_post_earnings_high": _round(post_high_drawdown, 2),
        "drawdown_from_52w_high": _round(high_drawdown, 2),
        "range_20d_pct": _round(range_20d, 2),
        "ret_20d_pct": _round(ret_20d, 2),
        "pri": _round(pri_value, 2),
        "price_state": price_state,
        "announcement_date": announcement_date,
        "checks": {"correction": correction, "sideways": sideways, "pri_below_max": pri_ok},
    }


# ═══ M2 — MACD(12,26,9) 상향 교차 직전 ═════════════════════════════
def _ema(values: Sequence[float], period: int) -> list[float]:
    """첫 값을 시드로 쓰는 EMA. JARVIS `lib/engine/technicals.ts`와 같은 정의다.

    시드를 다르게 잡으면(SMA 시드) 같은 일봉으로도 MACD가 미세하게 달라져
    경계값에서 JARVIS 표시와 이 판정이 갈린다.
    """
    alpha = 2.0 / (period + 1.0)
    out: list[float] = []
    for index, value in enumerate(values):
        out.append(value if index == 0 else value * alpha + out[-1] * (1.0 - alpha))
    return out


def macd_lines(closes: Sequence[float]) -> tuple[list[float], list[float], list[float]]:
    fast, slow, signal_period = ENTRY_M2_MACD_PARAMS
    fast_ema, slow_ema = _ema(closes, fast), _ema(closes, slow)
    macd = [a - b for a, b in zip(fast_ema, slow_ema)]
    signal = _ema(macd, signal_period)
    hist = [m - s for m, s in zip(macd, signal)]
    return macd, signal, hist


def _rising_streak(hist: Sequence[float]) -> int:
    streak = 0
    for index in range(len(hist) - 1, 0, -1):
        if hist[index] > hist[index - 1]:
            streak += 1
        else:
            break
    return streak


def _positive_streak(hist: Sequence[float]) -> int:
    streak = 0
    for value in reversed(hist):
        if value > 0:
            streak += 1
        else:
            break
    return streak


def m2_check(bars: Sequence[Bar]) -> dict | None:
    """MACD < Signal · 히스토그램 2일 연속 개선 · (갭 ≤ 0.30% 또는 추정 교차 ≤ 3봉).

    당일 교차(어제 hist ≤ 0, 오늘 hist > 0)는 `cross_today=true`로 통과시킨다.
    이미 위에 있으면(교차 다음 날 이후) 추격 방지로 탈락한다.
    손계산(경계): hist [-0.9, -0.6, -0.3], 종가 100 → gap 0.30% → 통과.
    추정 교차 = ceil(0.3 / 0.3) = 1봉.
    """
    if len(bars) < MIN_MACD_BARS:
        return None
    closes = [bar.close for bar in bars]
    macd, signal, hist = macd_lines(closes)
    return {**m2_decide(macd, signal, hist, closes[-1]), "as_of": bars[-1].date}


def m2_decide(
    macd: Sequence[float], signal: Sequence[float], hist: Sequence[float], close: float,
) -> dict:
    """MACD 선 세 개와 종가로 M2를 판정한다(순수). 경계값 테스트의 대상이다."""
    h, previous = hist[-1], hist[-2]
    # `×100 ÷ 종가` 순서: 0.75×100/250이 리터럴 0.30과 정확히 같아 경계가 흔들리지 않는다.
    gap_pct = (signal[-1] - macd[-1]) * 100.0 / close
    cross_today = h > 0 and previous <= 0
    improving = h > previous
    rising = _rising_streak(hist)
    projected = math.ceil(-h / (h - previous)) if improving and h <= 0 else None
    if cross_today:
        state, passed = "cross_today", bool(ENTRY_M2_ALLOW_CROSS_TODAY)
        projected = 0
    elif h > 0:
        state, passed = "above", False
    else:
        near = rising >= ENTRY_M2_HIST_RISING_BARS_MIN and (
            gap_pct <= ENTRY_M2_NEAR_CROSS_GAP_PCT_OF_CLOSE_MAX
            or (projected is not None and projected <= ENTRY_M2_PROJECTED_BARS_TO_CROSS_MAX)
        )
        state, passed = ("near" if near else "below"), near
    return {
        "pass": passed,
        "close": close,
        "macd": _round(macd[-1], 6),
        "signal": _round(signal[-1], 6),
        "hist": [_round(value, 6) for value in hist[-4:]],
        "gap_pct_of_close": _round(gap_pct, 4),
        "projected_bars": projected,
        "hist_rising_bars": rising,
        "cross_today": cross_today,
        "days_above_signal": _positive_streak(hist),
        "state": state,
    }


# ═══ M5 — 수급 2거래일 연속 ═════════════════════════════════════════
def _streak(values: Sequence[float]) -> int:
    count = 0
    for value in values:
        if value > 0:
            count += 1
        else:
            break
    return count


def m5_check(rows: Sequence[tuple[str, float, float]], *, source: str = "kis") -> dict | None:
    """`rows` = [(YYYYMMDD, 외국인 순매수, 기관 순매수)] — 날짜 순서는 상관없다.

    외국인·기관·합산 각각의 '오늘부터 거꾸로 센' 연속 순매수 일수를 구한다.
    외국인·기관 중 2일 이상인 더 긴 쪽(동률이면 외국인)을, 둘 다 아니면 합산을 쓴다.
    손계산: 외국인 [+5, −1](오늘, 어제) · 기관 [+3, +2] → 기관 2일 연속 통과.
    """
    ordered = sorted(rows, key=lambda row: row[0], reverse=True)
    if len(ordered) < ENTRY_M5_STREAK_DAYS:
        return None
    foreign = [float(row[1]) for row in ordered]
    institution = [float(row[2]) for row in ordered]
    combined = [a + b for a, b in zip(foreign, institution)]
    streaks = {
        "foreign": _streak(foreign),
        "institution": _streak(institution),
        "combined": _streak(combined),
    }
    # 같은 주체의 연속 매수가 합산보다 강한 증거다. 합산은 둘 다 아닐 때만 쓴다.
    def pick(paths: tuple[str, ...]) -> tuple[int, int, str] | None:
        eligible = [
            (streaks[path], -order, path) for order, path in enumerate(paths)
            if streaks[path] >= ENTRY_M5_STREAK_DAYS
        ]
        return max(eligible) if eligible else None

    best = pick(("foreign", "institution")) or pick(("combined",))
    recent = list(reversed(ordered[:4]))  # [-3..0] 시간순
    return {
        "pass": best is not None,
        "path": best[2] if best else None,
        "streak_days": best[0] if best else 0,
        "streaks": streaks,
        "as_of": ordered[0][0],
        "dates": [row[0] for row in recent],
        "foreign_net": [int(row[1]) for row in recent],
        "inst_net": [int(row[2]) for row in recent],
        "source": source,
    }


# ═══ 무효화선 ═══════════════════════════════════════════════════════
def recent_low(bars: Sequence[Bar], sessions: int) -> float | None:
    """최근 N거래일 **저가**의 최저. 저가가 없으면 종가로 대신한다."""
    if len(bars) < sessions:
        return None
    window = bars[-sessions:]
    return min((bar.low if bar.low and bar.low > 0 else bar.close) for bar in window)


def invalidation(bars: Sequence[Bar], price_state: str | None) -> dict:
    low_10d = recent_low(bars, ENTRY_INVALIDATION_PB_SESSIONS)
    low_20d = recent_low(bars, ENTRY_INVALIDATION_SW_SESSIONS)
    price = low_10d if price_state == "PB" else low_20d if price_state == "SW" else None
    return {"low_10d": low_10d, "low_20d": low_20d, "invalidation_price": price}


# ═══ 🔵 K1 실적 돌파 ════════════════════════════════════════════════
def first_session_after(
    disclosed_on: str, detected_at_kst: datetime | None, sessions: Sequence[str],
) -> str | None:
    """공시 후 첫 정규장(D0). `disclosed_on`='YYYYMMDD', `sessions`=거래일 목록.

    DART 목록은 접수 **날짜**만 준다. 접수 시각을 모르는 채 당일을 D0로 잡으면
    장 마감 후 공시의 '반응 전' 봉을 돌파일로 읽는다(T217). 그래서 폴링이 공시를
    **당일 09:00 전**에 감지했다는 증거가 있을 때만 당일을 D0로 인정하고, 나머지는
    다음 거래일이다.
    """
    pre_open_same_day = bool(
        detected_at_kst is not None
        and kst_date_key(detected_at_kst) == disclosed_on
        and detected_at_kst.hour < 9
    )
    for session in sorted(sessions):
        if session > disclosed_on or (pre_open_same_day and session == disclosed_on):
            return session
    return None


def k1_breakout(bars: Sequence[Bar], d0: str) -> dict | None:
    """D0 봉의 갭·종가수익률·거래량 배수·종가위치. 판정에 필요한 값이 없으면 None.

    손계산: 전일 10,000 · 시가 10,300(+3.0%) · 고가 11,000 · 저가 10,200 · 종가 10,800,
    거래량 250만 vs 직전 20일 평균 100만(×2.5) → 종가위치 (10,800−10,200)/800 = 0.75 → 통과.
    """
    index = next((i for i, bar in enumerate(bars) if bar.date == d0), None)
    if index is None or index < K1_VOLUME_AVG_SESSIONS:
        return None
    bar, previous = bars[index], bars[index - 1]
    prior_volumes = [b.volume for b in bars[index - K1_VOLUME_AVG_SESSIONS:index]]
    if (
        bar.open is None or bar.high is None or bar.low is None or bar.volume is None
        or previous.close <= 0 or any(v is None for v in prior_volumes)
    ):
        return None
    avg_volume = sum(float(v) for v in prior_volumes if v is not None) / len(prior_volumes)
    gap_pct = _change_pct(bar.open, previous.close)
    ret_pct = _change_pct(bar.close, previous.close)
    volume_mult = bar.volume / avg_volume if avg_volume > 0 else None
    close_location = (
        (bar.close - bar.low) / (bar.high - bar.low) if bar.high > bar.low else None
    )
    price_ok = gap_pct >= K1_GAP_OPEN_MIN_PCT or ret_pct >= K1_CLOSE_RETURN_MIN_PCT
    passed = all_of([
        price_ok,
        None if volume_mult is None else volume_mult >= K1_VOLUME_MULT_MIN,
        None if close_location is None else close_location >= K1_CLOSE_LOCATION_MIN,
    ])
    return {
        "pass": passed,
        "d0": d0,
        "d0_open": bar.open,
        "d0_high": bar.high,
        "d0_low": bar.low,
        "d0_close": bar.close,
        "prev_close": previous.close,
        "gap_open_pct": _round(gap_pct, 2),
        "close_return_pct": _round(ret_pct, 2),
        "volume": bar.volume,
        "avg_volume_20d": _round(avg_volume, 1),
        "volume_mult": _round(volume_mult, 2),
        "close_location": _round(close_location, 3),
    }
