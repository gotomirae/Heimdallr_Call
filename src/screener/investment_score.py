# PRD Ref: §4.2 (기업 투자 매력도) · ADR 2, ADR 5
"""기업 투자 매력도 7축 — 순수 함수. 외부 I/O 금지.

입력 축은 모두 0~100으로 정규화된 관측값이다. 원자료가 없는 축은 0점으로
간주하지 않고 분모에서 제외한다. 산업·피어 비교도 같은 평가 분기·같은 투자
섹터 안에서 만든 값만 받는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from src.config.constants import (
    INVESTMENT_SCORE_MIN_DENOMINATOR,
    INVESTMENT_SCORE_WEIGHTS,
    INDUSTRY_POSITION_WEIGHTS,
    INDUSTRY_POSITION_MIN_DENOMINATOR,
    INDUSTRY_POSITION_SHARE_ANCHORS,
    INDUSTRY_POSITION_GLOBAL_NAMES,
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
    position_evidence: dict | None = None


@dataclass(frozen=True)
class InvestmentScoreResult:
    parts: dict[str, float | None]
    raw_sum: float
    denominator: int
    score: float | None
    confidence: float
    inputs: dict[str, float | None]
    mode: str = "investment_v1"
    position_evidence: dict | None = None

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
            "industry_position_evidence": self.position_evidence,
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
        position_evidence=data.position_evidence,
    )


def industry_position_from_report(sections: dict, url: str, name: str) -> dict:
    """공시의 자사 귀속 문장만 측정한다. 경쟁사/전망/모호한 다중 비율은 결측.

    회사의 공시 주장이지 독립 시장조사 검증은 아니다. 제품·시장 범위는 원문 인용으로
    보존하며 이름 없는 글로벌 고객이나 제품 한정 독점을 회사 전체 독점으로 확대하지 않는다.
    """
    values = {key: None for key in INDUSTRY_POSITION_WEIGHTS}
    evidence = []
    owner = re.compile(r"당사|자사|우리\s*회사|" + re.escape(name))
    for text in sections.values():
        if not isinstance(text, str):
            continue
        for sentence in re.split(r"[\n。]|(?<=[다요])\.\s+", text):
            if not owner.search(sentence) or len(sentence) > 500:
                continue
            if re.search(r"추정|예상|목표|전망|예정|가능|과거|아니|없|경쟁사", sentence):
                continue
            observed = {}
            percentages = re.findall(r"(?<![\d.])(\d+(?:\.\d+)?)\s*%", sentence)
            if "점유율" in sentence and len(percentages) == 1:
                value = float(percentages[0])
                if 0 <= value <= 100:
                    if re.search(r"글로벌|세계|전세계", sentence):
                        observed["global_share"] = value
                    elif "국내" in sentence:
                        observed["domestic_share"] = value
            if re.search(r"(?:세계|글로벌|국내)\s*유일|독점\s*(?:공급|생산|사업)", sentence):
                observed["exclusive"] = 100.0
            if any(company.lower() in sentence.lower() for company in INDUSTRY_POSITION_GLOBAL_NAMES) and re.search(r"공급하고|공급하였|납품하고|납품하였|공급계약.*체결|납품.*고객", sentence):
                observed["global_chain"] = 100.0
            # 같은 축 복수 문장은 제품/기간 범위를 임의 비교하지 않는다.
            for key, value in observed.items():
                if any(item["axis"] == key for item in evidence):
                    values[key] = None
                    evidence.append({"axis": key, "value": value, "quote": sentence.strip(), "url": url, "ambiguous": True})
                else:
                    values[key] = value
                    evidence.append({"axis": key, "value": value, "quote": sentence.strip(), "url": url})
    denominator = sum(INDUSTRY_POSITION_WEIGHTS[key] for key, value in values.items() if value is not None)
    normalized = {key: linear_score(value, INDUSTRY_POSITION_SHARE_ANCHORS[key]) if key in INDUSTRY_POSITION_SHARE_ANCHORS else value for key, value in values.items()}
    score = sum((value or 0) * INDUSTRY_POSITION_WEIGHTS[key] for key, value in normalized.items()) / denominator if denominator >= INDUSTRY_POSITION_MIN_DENOMINATOR else None
    return {"mode": "disclosure_position_v2", "score": score, "denominator": denominator,
            "values": values, "evidence": evidence, "limitation": "공시상 자사 주장·제품 범위 한정. 독립 시장조사 미검증이며 단일 축만 있으면 점수 보류."}
