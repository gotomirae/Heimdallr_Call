# PRD Ref: §4.3 (주가반영도 PRI) · ADR 5
"""주가반영도 지수 PRI (0~100, **낮을수록 아직 안 올랐음**) — 순수 함수.

스코어와 합산하지 않는다(ADR 5). 공개된 원자료가 없는 항목은 0점으로
추정하지 않고 분모에서 뺀다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

from src.config.constants import (
    PRI_CORE_MIN_DENOMINATOR,
    PRI_DRIVER_SHARE_ANCHORS_PCT,
    PRI_IMPLIED_GROWTH_GAP_ANCHORS_PCT,
    PRI_IMPLIED_GROWTH_YEARS,
    PRI_NEW_WEIGHTS,
    PRI_EVENT_ANCHORS_PCT,
    PRI_OVERHEAT_ANCHORS_PCT,
    PRI_OVERHEAT_DRAWDOWN_ANCHORS_PCT,
    PRI_OVERHEAT_MIN_SIGNALS,
    PRI_OVERHEAT_RET_5D_ANCHORS_PCT,
    PRI_OVERHEAT_RSI_ANCHORS,
    PRI_PEER_PEG_PREMIUM_ANCHORS_PCT,
    PRI_REVISION_GAP_ANCHORS_PCT,
    PRI_VALUATION_ANCHORS_PCT,
    PRI_RELATIVE_RETURN_ANCHORS_PCT,
    P1_HIGH_DRAWDOWN_FLOOR_PCT,
    P2_ANNOUNCEMENT_RETURN_MAX_PCT,
    P3_PER_PREMIUM_MAX_PCT,
    P4_FOREIGN_NET_RATIO_ANCHORS_PCT,
    P5_RSI_ANCHORS,
    PRI_MIN_DENOMINATOR,
    PRI_WEIGHTS,
)


@dataclass(frozen=True)
class PriInput:
    """전부 Optional. 시세 수집 실패가 스크리닝 전체를 막으면 안 된다."""

    high_52w_drawdown_pct: float | None = None
    announcement_return_pct: float | None = None
    per_vs_9q_avg_pct: float | None = None
    foreign_net_ratio_5d_pct: float | None = None
    rsi_14: float | None = None
    # PRI 3.0 — 가격 반응·성장 정당화·밸류·과열 축. confidence는 점수에 합산하지 않고
    # 측정 가능 배점으로 계산되는 신뢰도 게이트다.
    announcement_excess_return_pct: float | None = None
    earnings_revision_price_gap_pct: float | None = None
    valuation_reflection_pct: float | None = None
    relative_return_pct: float | None = None
    price_return_12m_pct: float | None = None
    earnings_growth_12m_pct: float | None = None
    multiple_expansion_pct: float | None = None
    multiple_expansion_share_pct: float | None = None
    implied_growth_required_pct: float | None = None
    forecast_earnings_growth_pct: float | None = None
    implied_growth_gap_pct: float | None = None
    growth_adjusted_pe: float | None = None
    peer_median_growth_adjusted_pe: float | None = None
    peer_peg_premium_pct: float | None = None
    overheat_score_pct: float | None = None
    overheat_signal_count: float | None = None
    ret_5d_pct: float | None = None


@dataclass
class PriResult:
    parts: dict[str, float | None] = field(default_factory=dict)
    raw_sum: float = 0.0
    denominator: int = 0
    pri: float | None = None
    measured: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()
    inputs: dict[str, float | None] = field(default_factory=dict)
    confidence: float | None = None
    mode: str = "legacy"

    @property
    def detail(self) -> dict:
        return {
            "parts": self.parts,
            "raw_sum": self.raw_sum,
            "denominator": self.denominator,
            "excluded": list(self.excluded),
            "inputs": self.inputs,
            "confidence": self.confidence,
            "mode": self.mode,
        }


def _p1(drawdown_pct: float | None) -> float | None:
    """52주 신고가 대비 등락률 → 25점."""
    if drawdown_pct is None:
        return None
    full = float(PRI_WEIGHTS["p1"])
    if drawdown_pct <= P1_HIGH_DRAWDOWN_FLOOR_PCT:
        return 0.0
    if drawdown_pct >= 0:
        return full
    return (
        (drawdown_pct - P1_HIGH_DRAWDOWN_FLOOR_PCT)
        / -P1_HIGH_DRAWDOWN_FLOOR_PCT
        * full
    )


def _p2(return_pct: float | None) -> float | None:
    """최초 실적 발표일 종가 대비 현재 등락률 → 25점."""
    if return_pct is None:
        return None
    if return_pct <= 0:
        return 0.0
    return min(return_pct / P2_ANNOUNCEMENT_RETURN_MAX_PCT, 1.0) * PRI_WEIGHTS["p2"]


def _p3(premium_pct: float | None) -> float | None:
    """현재 PER의 과거 9개 분기 평균 대비 할증 → 20점."""
    if premium_pct is None:
        return None
    if premium_pct <= 0:
        return 0.0
    return min(premium_pct / P3_PER_PREMIUM_MAX_PCT, 1.0) * PRI_WEIGHTS["p3"]


def _p4(net_ratio_pct: float | None) -> float | None:
    """발표일부터 5거래일 외국인 순매수 비율 → 10점."""
    if net_ratio_pct is None:
        return None
    low, _, high = P4_FOREIGN_NET_RATIO_ANCHORS_PCT
    full = float(PRI_WEIGHTS["p4"])
    if net_ratio_pct <= low:
        return 0.0
    if net_ratio_pct >= high:
        return full
    return (net_ratio_pct - low) / (high - low) * full


def _p5(rsi: float | None) -> float | None:
    """RSI(14) → 20점. 30·45·70을 0·10·20점 앵커로 선형 보간한다."""
    if rsi is None:
        return None
    low, mid, high = P5_RSI_ANCHORS
    full = float(PRI_WEIGHTS["p5"])
    midpoint = full / 2
    if rsi <= low:
        return 0.0
    if rsi >= high:
        return full
    if rsi <= mid:
        return (rsi - low) / (mid - low) * midpoint
    return midpoint + (rsi - mid) / (high - mid) * midpoint


def _linear(value: float | None, anchors: tuple[float, float], full: float) -> float | None:
    """두 절대 앵커 사이를 0~full로 선형 변환한다."""
    if value is None:
        return None
    low, high = anchors
    if value <= low:
        return 0.0
    if value >= high:
        return float(full)
    return (float(value) - low) / (high - low) * float(full)


def forward_earnings_growth_pct(
    current_ttm_per: float | None, forward_per: float | None
) -> float | None:
    """현재 TTM EPS에서 컨센서스 EPS까지의 이익 성장률.

    같은 주가에서 ``EPS_forward / EPS_ttm = PER_ttm / PER_forward``다. 두 배수의
    분모가 모두 양수일 때만 계산하며, 외부에서 받은 직전 사업연도 PER은 쓰지 않는다(T92).
    """
    if current_ttm_per is None or forward_per is None:
        return None
    if current_ttm_per <= 0 or forward_per <= 0:
        return None
    return (float(current_ttm_per) / float(forward_per) - 1.0) * 100.0


def implied_growth_required_pct(
    current_ttm_per: float | None,
    historical_per: float | None,
    *,
    years: int = PRI_IMPLIED_GROWTH_YEARS,
) -> float | None:
    """현재 가격이 ``years``년 뒤 역사적 정상 PER이 되려면 필요한 연 이익성장률.

    가격을 고정한 보수적 역산이다. DCF인 척 할인율·영구성장률을 추측하지 않고,
    시스템이 실제로 측정한 동일 기업의 과거 PER을 정상 배수로 쓴다.
    """
    if current_ttm_per is None or historical_per is None or years <= 0:
        return None
    if current_ttm_per <= 0 or historical_per <= 0:
        return None
    return ((float(current_ttm_per) / float(historical_per)) ** (1.0 / years) - 1.0) * 100.0


def multiple_expansion_attribution(
    price_return_pct: float | None, earnings_growth_pct: float | None
) -> tuple[float | None, float | None]:
    """12개월 주가 수익을 이익 성장과 PER 변화로 정확히 분해한다.

    ``(1+주가수익) = (1+EPS성장) × (1+PER변화)``. 주가가 오른 경우에만
    로그 기여도로 멀티플 팽창 몫(0~100%)을 계산한다. 하락을 억지로 '상승 이유'로
    설명하지 않는다.
    """
    if price_return_pct is None or earnings_growth_pct is None:
        return None, None
    price_factor = 1.0 + float(price_return_pct) / 100.0
    earnings_factor = 1.0 + float(earnings_growth_pct) / 100.0
    if price_factor <= 0 or earnings_factor <= 0:
        return None, None
    multiple_change = (price_factor / earnings_factor - 1.0) * 100.0
    if price_return_pct <= 0:
        return multiple_change, None
    total_log = math.log(price_factor)
    if abs(total_log) < 1e-12:
        return multiple_change, None
    multiple_share = math.log(price_factor / earnings_factor) / total_log * 100.0
    return multiple_change, min(max(multiple_share, 0.0), 100.0)


def growth_adjusted_pe(
    current_ttm_per: float | None, forecast_growth_pct: float | None
) -> float | None:
    """같은 TTM EPS 기준의 PER ÷ 예상 이익성장률(PEG형 성장단가)."""
    if current_ttm_per is None or forecast_growth_pct is None:
        return None
    if current_ttm_per <= 0 or forecast_growth_pct <= 0:
        return None
    return float(current_ttm_per) / float(forecast_growth_pct)


def peer_peg_premium_pct(value: float | None, peer_median: float | None) -> float | None:
    if value is None or peer_median is None or peer_median <= 0:
        return None
    return (float(value) / float(peer_median) - 1.0) * 100.0


def overheat_score_pct(
    *,
    rsi: float | None,
    ret_5d_pct: float | None,
    high_52w_drawdown_pct: float | None,
) -> tuple[float | None, int]:
    """현재 가격의 단기 과열 프록시. 최소 두 신호가 있어야 계산한다.

    발표일부터 5거래일 외국인 수급은 현재 신호가 아니므로 섞지 않는다(T147).
    """
    signals = [
        _linear(rsi, PRI_OVERHEAT_RSI_ANCHORS, 100.0),
        _linear(ret_5d_pct, PRI_OVERHEAT_RET_5D_ANCHORS_PCT, 100.0),
        _linear(high_52w_drawdown_pct, PRI_OVERHEAT_DRAWDOWN_ANCHORS_PCT, 100.0),
    ]
    measured = [value for value in signals if value is not None]
    if len(measured) < PRI_OVERHEAT_MIN_SIGNALS:
        return None, len(measured)
    return sum(measured) / len(measured), len(measured)


def _compute_new(data: PriInput) -> PriResult:
    """PRI 3.0.

    여덟 개의 가격·성장·밸류·과열 축을 점수화하고 데이터 신뢰도는
    ``confidence``로 별도 표시한다. 신뢰도를 PRI에 더하면 데이터가 부족한
    종목이 실제보다 저반영처럼 보이는 T31 유형의 오류가 재발한다.
    """
    parts = {
        "event": _linear(data.announcement_excess_return_pct, PRI_EVENT_ANCHORS_PCT,
                          PRI_NEW_WEIGHTS["event"]),
        "revision": _linear(data.earnings_revision_price_gap_pct, PRI_REVISION_GAP_ANCHORS_PCT,
                             PRI_NEW_WEIGHTS["revision"]),
        "driver": _linear(data.multiple_expansion_share_pct, PRI_DRIVER_SHARE_ANCHORS_PCT,
                           PRI_NEW_WEIGHTS["driver"]),
        "implied_growth": _linear(data.implied_growth_gap_pct, PRI_IMPLIED_GROWTH_GAP_ANCHORS_PCT,
                                   PRI_NEW_WEIGHTS["implied_growth"]),
        "valuation_history": _linear(data.valuation_reflection_pct, PRI_VALUATION_ANCHORS_PCT,
                                      PRI_NEW_WEIGHTS["valuation_history"]),
        "valuation_peer": _linear(data.peer_peg_premium_pct, PRI_PEER_PEG_PREMIUM_ANCHORS_PCT,
                                   PRI_NEW_WEIGHTS["valuation_peer"]),
        "relative": _linear(data.relative_return_pct, PRI_RELATIVE_RETURN_ANCHORS_PCT,
                             PRI_NEW_WEIGHTS["relative"]),
        "overheat": _linear(data.overheat_score_pct, PRI_OVERHEAT_ANCHORS_PCT,
                             PRI_NEW_WEIGHTS["overheat"]),
    }
    inputs = {
        "announcement_excess_return_pct": data.announcement_excess_return_pct,
        "earnings_revision_price_gap_pct": data.earnings_revision_price_gap_pct,
        "valuation_reflection_pct": data.valuation_reflection_pct,
        "relative_return_pct": data.relative_return_pct,
        "price_return_12m_pct": data.price_return_12m_pct,
        "earnings_growth_12m_pct": data.earnings_growth_12m_pct,
        "multiple_expansion_pct": data.multiple_expansion_pct,
        "multiple_expansion_share_pct": data.multiple_expansion_share_pct,
        "implied_growth_required_pct": data.implied_growth_required_pct,
        "forecast_earnings_growth_pct": data.forecast_earnings_growth_pct,
        "implied_growth_gap_pct": data.implied_growth_gap_pct,
        "growth_adjusted_pe": data.growth_adjusted_pe,
        "peer_median_growth_adjusted_pe": data.peer_median_growth_adjusted_pe,
        "peer_peg_premium_pct": data.peer_peg_premium_pct,
        "overheat_score_pct": data.overheat_score_pct,
        "overheat_signal_count": data.overheat_signal_count,
        "ret_5d_pct": data.ret_5d_pct,
        "rsi_14": data.rsi_14,
        "high_52w_drawdown_pct": data.high_52w_drawdown_pct,
        "foreign_net_ratio_5d_pct": data.foreign_net_ratio_5d_pct,
    }
    measured = [key for key, value in parts.items() if value is not None]
    excluded = [key for key, value in parts.items() if value is None]
    raw_sum = sum(value for value in parts.values() if value is not None)
    denominator = sum(PRI_NEW_WEIGHTS[key] for key in measured)
    confidence = float(denominator)
    pri = raw_sum / denominator * 100 if denominator >= PRI_CORE_MIN_DENOMINATOR else None
    return PriResult(
        parts=parts,
        raw_sum=raw_sum,
        denominator=denominator,
        pri=pri,
        measured=tuple(measured),
        excluded=tuple(excluded),
        inputs=inputs,
        confidence=confidence,
        mode="v3",
    )


def compute_pri(data: PriInput) -> PriResult:
    # 새 입력이 하나라도 있으면 현대 PRI를 사용한다. 기존 저장 데이터와
    # 순수 함수 회귀 테스트를 위해 구 입력만 전달된 경우에는 legacy 계산을
    # 유지한다 — 현대 가격 입력이 있는 행은 v3가 된다.
    new_values = (
        data.announcement_excess_return_pct,
        data.earnings_revision_price_gap_pct,
        data.multiple_expansion_share_pct,
        data.implied_growth_gap_pct,
        data.valuation_reflection_pct,
        data.peer_peg_premium_pct,
        data.relative_return_pct,
        data.overheat_score_pct,
    )
    if any(value is not None for value in new_values):
        return _compute_new(data)

    parts = {
        "p1": _p1(data.high_52w_drawdown_pct),
        "p2": _p2(data.announcement_return_pct),
        "p3": _p3(data.per_vs_9q_avg_pct),
        "p4": _p4(data.foreign_net_ratio_5d_pct),
        "p5": _p5(data.rsi_14),
    }
    inputs = {
        "high_52w_drawdown_pct": data.high_52w_drawdown_pct,
        "announcement_return_pct": data.announcement_return_pct,
        "per_vs_9q_avg_pct": data.per_vs_9q_avg_pct,
        "foreign_net_ratio_5d_pct": data.foreign_net_ratio_5d_pct,
        "rsi_14": data.rsi_14,
    }
    measured = [key for key, value in parts.items() if value is not None]
    excluded = [key for key, value in parts.items() if value is None]
    raw_sum = sum(value for value in parts.values() if value is not None)
    denominator = sum(PRI_WEIGHTS[key] for key in measured)

    # SC: 항목 하나만으로 '미반영'을 선언하지 않는다(T35).
    pri = raw_sum / denominator * 100 if denominator >= PRI_MIN_DENOMINATOR else None
    return PriResult(
        parts=parts,
        raw_sum=raw_sum,
        denominator=denominator,
        pri=pri,
        measured=tuple(measured),
        excluded=tuple(excluded),
        inputs=inputs,
        confidence=float(denominator),
        mode="legacy",
    )
