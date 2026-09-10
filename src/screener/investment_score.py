# PRD Ref: §4.2 (기업 투자 매력도) · ADR 2, ADR 5
"""기업 투자 매력도 7축 — 순수 함수. 외부 I/O 금지.

입력 축은 모두 0~100으로 정규화된 관측값이다. 원자료가 없는 축은 0점으로
간주하지 않고 분모에서 제외한다. 산업·피어 비교도 같은 평가 분기·같은 투자
섹터 안에서 만든 값만 받는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.config.constants import (
    INVESTMENT_SCORE_MIN_DENOMINATOR,
    INVESTMENT_SCORE_WEIGHTS,
)


@dataclass(frozen=True)
class InvestmentScoreInput:
    industry_growth: float | None = None
    industry_position: float | None = None
    earnings: float | None = None
    growth_story: float | None = None
    valuation: float | None = None
    roe: float | None = None
    fcf: float | None = None
    inputs: dict[str, float | None] = field(default_factory=dict)


@dataclass(frozen=True)
class InvestmentScoreResult:
    parts: dict[str, float | None]
    raw_sum: float
    denominator: int
    score: float | None
    confidence: float
    inputs: dict[str, float | None]
    mode: str = "investment_v1"

    @property
    def detail(self) -> dict:
        return {
            "mode": self.mode,
            "parts": self.parts,
            "raw_sum": self.raw_sum,
            "denominator": self.denominator,
            "score": self.score,
            "confidence": self.confidence,
            "excluded": [key for key, value in self.parts.items() if value is None],
            "inputs": self.inputs,
        }


def clamp_score(value: float | None) -> float | None:
    if value is None:
        return None
    return min(max(float(value), 0.0), 100.0)


def linear_score(
    value: float | None, anchors: tuple[float, float]
) -> float | None:
    """두 앵커를 0~100으로 선형 변환한다."""
    if value is None:
        return None
    low, high = anchors
    if high <= low:
        raise ValueError("investment score anchors must increase")
    return clamp_score((float(value) - low) / (high - low) * 100.0)


def mean_measured(*values: float | None) -> float | None:
    measured = [float(value) for value in values if value is not None]
    return sum(measured) / len(measured) if measured else None


def percentile_scores(
    values: dict[str, float | None], *, higher_is_better: bool = True
) -> dict[str, float | None]:
    """tie-aware 백분위. 결측은 모집단과 결과에서 모두 제외한다."""
    measured = [float(value) for value in values.values() if value is not None]
    out: dict[str, float | None] = {}
    for key, value in values.items():
        if value is None or not measured:
            out[key] = None
            continue
        current = float(value)
        if higher_is_better:
            better_or_equal = sum(candidate <= current for candidate in measured)
        else:
            better_or_equal = sum(candidate >= current for candidate in measured)
        out[key] = better_or_equal / len(measured) * 100.0
    return out


def compute_investment_score(data: InvestmentScoreInput) -> InvestmentScoreResult:
    normalized = {
        key: clamp_score(getattr(data, key)) for key in INVESTMENT_SCORE_WEIGHTS
    }
    parts = {
        key: (
            None if value is None
            else value / 100.0 * INVESTMENT_SCORE_WEIGHTS[key]
        )
        for key, value in normalized.items()
    }
    denominator = sum(
        INVESTMENT_SCORE_WEIGHTS[key]
        for key, value in normalized.items()
        if value is not None
    )
    raw_sum = sum(value for value in parts.values() if value is not None)
    score = (
        raw_sum / denominator * 100.0
        if denominator >= INVESTMENT_SCORE_MIN_DENOMINATOR else None
    )
    return InvestmentScoreResult(
        parts=parts,
        raw_sum=raw_sum,
        denominator=denominator,
        score=score,
        confidence=float(denominator),
        inputs={**data.inputs, **normalized},
    )
