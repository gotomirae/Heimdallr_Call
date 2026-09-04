# PRD Ref: §4.3 (주가반영도 PRI) · ADR 5
"""주가반영도 지수 PRI (0~100, **낮을수록 아직 안 올랐음**) — 순수 함수.

스코어와 합산하지 않는다(ADR 5). 공개된 원자료가 없는 항목은 0점으로
추정하지 않고 분모에서 뺀다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.config.constants import (
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


@dataclass
class PriResult:
    parts: dict[str, float | None] = field(default_factory=dict)
    raw_sum: float = 0.0
    denominator: int = 0
    pri: float | None = None
    measured: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()
    inputs: dict[str, float | None] = field(default_factory=dict)

    @property
    def detail(self) -> dict:
        return {
            "parts": self.parts,
            "raw_sum": self.raw_sum,
            "denominator": self.denominator,
            "excluded": list(self.excluded),
            "inputs": self.inputs,
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


def compute_pri(data: PriInput) -> PriResult:
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
    )
