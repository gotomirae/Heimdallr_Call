# PRD Ref: §4.3 (주가반영도 PRI) · ADR 5
"""주가반영도 지수 PRI (0~100, **낮을수록 미반영**) — 순수 함수. 외부 I/O 금지.

★ 스코어에 합산하지 않는다 (ADR 5). 펀더멘털 강도와 주가 반영도는 다른 축이고,
  한 숫자로 뭉개면 둘 다 못 읽는다. 2축 매트릭스로 병기한다.

스코어와 **같은 정규화 규칙**을 쓴다. P4(발표 반응)는 발표 다음 거래일에만
계산 가능하므로, 즉시 알림 시점에는 P1~P3(85점 만점)을 정규화한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.config.constants import (
    P1_MID_SCORE,
    P1_REL_RETURN_ANCHORS_PP,
    P4_REACTION_MAX_PCT,
    PRI_MIN_DENOMINATOR,
    PRI_WEIGHTS,
)


@dataclass(frozen=True)
class PriInput:
    """전부 Optional. 시세 수집 실패가 스크리닝 전체를 막으면 안 된다(PRD §5.4)."""

    rel_return_3m_pp: float | None = None  # 소속 지수 대비 3개월 초과수익(%p)
    close: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    per_percentile_3y: float | None = None  # 3년 PER 밴드 내 백분위 (0~100)
    reaction_d1_pp: float | None = None  # 발표 D+1 지수대비 초과수익(%)


@dataclass
class PriResult:
    parts: dict[str, float | None] = field(default_factory=dict)
    raw_sum: float = 0.0
    denominator: int = 0
    pri: float | None = None
    measured: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()

    @property
    def detail(self) -> dict:
        """screen_results.pri_detail에 그대로 넣는다."""
        return {
            "parts": self.parts,
            "raw_sum": self.raw_sum,
            "denominator": self.denominator,
            "excluded": list(self.excluded),
            "inputs": self.inputs,
        }

    inputs: dict[str, float | None] = field(default_factory=dict)


def _p1(rel_return_pp: float | None) -> float | None:
    """3개월 상대수익률 → 40점.

    −10%p 이하 → 0 · 0%p → 20 · +30%p 이상 → 40. 두 구간을 각각 선형 보간한다.
    (이미 많이 오른 종목일수록 '반영됐다'고 보아 높은 점수를 준다 — PRI는
     높을수록 선반영이다.)
    """
    if rel_return_pp is None:
        return None
    low, mid, high = P1_REL_RETURN_ANCHORS_PP
    full = float(PRI_WEIGHTS["p1"])
    if rel_return_pp <= low:
        return 0.0
    if rel_return_pp >= high:
        return full
    if rel_return_pp <= mid:
        return (rel_return_pp - low) / (mid - low) * P1_MID_SCORE
    return P1_MID_SCORE + (rel_return_pp - mid) / (high - mid) * (full - P1_MID_SCORE)


def _p2(close: float | None, high: float | None, low: float | None) -> float | None:
    """52주 위치 × 25. 고가와 저가가 같으면(신규 상장 등) 판정 불가."""
    if close is None or high is None or low is None:
        return None
    if high <= low:
        return None
    position = (close - low) / (high - low)
    position = min(max(position, 0.0), 1.0)  # 장중 갱신 지연으로 범위를 벗어날 수 있다
    return position * PRI_WEIGHTS["p2"]


def _p3(per_percentile: float | None) -> float | None:
    """3년 PER 밴드 백분위 × 20. 컨센서스가 없으면 미측정 → 정규화."""
    if per_percentile is None:
        return None
    pct = min(max(per_percentile, 0.0), 100.0)
    return pct / 100.0 * PRI_WEIGHTS["p3"]


def _p4(reaction_pp: float | None) -> float | None:
    """발표 D+1 초과수익 → 15점. 0% 이하 → 0 · +10% 이상 → 만점."""
    if reaction_pp is None:
        return None
    full = float(PRI_WEIGHTS["p4"])
    if reaction_pp <= 0:
        return 0.0
    if reaction_pp >= P4_REACTION_MAX_PCT:
        return full
    return reaction_pp / P4_REACTION_MAX_PCT * full


def compute_pri(data: PriInput) -> PriResult:
    parts = {
        "p1": _p1(data.rel_return_3m_pp),
        "p2": _p2(data.close, data.high_52w, data.low_52w),
        "p3": _p3(data.per_percentile_3y),
        "p4": _p4(data.reaction_d1_pp),
    }

    inputs = {
        "rel_return_3m_pp": data.rel_return_3m_pp,
        "close": data.close,
        "high_52w": data.high_52w,
        "low_52w": data.low_52w,
        "per_percentile_3y": data.per_percentile_3y,
        "reaction_d1_pp": data.reaction_d1_pp,
    }
    measured = [k for k, v in parts.items() if v is not None]
    excluded = [k for k, v in parts.items() if v is None]
    raw_sum = sum(v for v in parts.values() if v is not None)
    denominator = sum(PRI_WEIGHTS[k] for k in measured)

    # SC: PRI 분모가 얇으면 판정하지 않는다 — 0점이 아니라 None이다.
    # ★ P2(52주 위치, 25점) 하나만 측정돼도 산술적으로는 PRI가 나온다.
    #   실측: rel_ret_3m 수집 전 전 종목이 분모 25로 PRI를 받아 ★27 · ○88이 배정됐다.
    #   "3개월간 시장 대비 얼마나 안 올랐나"(P1, 40점)를 모르는 채로 '미반영'을 선언하는 셈이라,
    #   52주 저점 부근이기만 하면 이미 시장을 크게 이긴 종목도 ★가 된다.
    #   스코어 축과 달리 PRI는 항목 하나가 지배적이라 축 단위 정규화만으로는 못 막는다.
    if denominator < PRI_MIN_DENOMINATOR:
        return PriResult(
            parts=parts,
            raw_sum=raw_sum,
            denominator=denominator,
            pri=None,
            measured=tuple(measured),
            excluded=tuple(excluded),
            inputs=inputs,
        )

    return PriResult(
        parts=parts,
        raw_sum=raw_sum,
        denominator=denominator,
        pri=(raw_sum / denominator * 100) if denominator else None,
        measured=tuple(measured),
        excluded=tuple(excluded),
        inputs=inputs,
    )
