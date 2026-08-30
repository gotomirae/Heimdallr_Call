# PRD Ref: §4.2 (스코어 · 정규화 규칙) · 부록 A · ADR 2
"""스코어 A/B/C/D + ★정규화 — **순수 함수. 외부 I/O 금지.**

★★ 이 파일에서 가장 중요한 것은 배점이 아니라 **정규화 규칙**이다 (PRD §4.2 · ADR 2).

    score_norm = raw_sum / (100 − 미측정축_배점) × 100

측정 불가능한 축을 **0점 처리하지 않고 분모에서 제외**한다.
코스닥의 약 60%는 애널리스트 커버리지가 없다. C축을 0점 처리하면 그 종목들이
구조적으로 15점 손해를 보고 상위에서 밀려나 — **이 시스템의 존재 이유가 사라진다.**
SC6(분기 상위 20 중 has_consensus=false 비율 ≥ 30%)으로 상시 감시한다.

모든 임계값은 `src/config/constants.py`에서만 읽는다. 하드코딩 금지.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from src.config.constants import (
    A1_DELTA_MAX_PP,
    A2_DELTA_MAX_PP,
    A3_TTM_OP_GROWTH_BONUS_PCT,
    A_WEIGHTS,
    B1_OPM_TIERS_PP,
    B2_TTM_OPM_TIERS_PP,
    B4_SECTOR_TIERS_PCT,
    B_WEIGHTS,
    C1_SURPRISE_TIERS_PCT,
    C2_SURPRISE_TIERS_PCT,
    C_WEIGHTS,
    D1_CFO_TO_OP_MIN,
    D2_DILUTION_TIERS_PCT,
    D4_LIQUIDITY_TIERS_KRW,
    D_WEIGHTS,
    MIN_ESTIMATES,
    SCORE_WEIGHTS,
)


@dataclass(frozen=True)
class ScoreInput:
    """스코어 입력. **전부 Optional** — 없으면 그 항목만 건너뛴다."""

    # A 성장 가속
    revenue_yoy_t: float | None = None
    revenue_yoy_t1: float | None = None
    op_yoy_t: float | None = None
    op_yoy_t1: float | None = None
    ttm_revenue_t: float | None = None
    ttm_revenue_t1: float | None = None
    #: A3의 입력. **2026-08-22에 TTM 매출 → TTM 영업이익으로 바뀌었다.**
    #: `ttm_revenue_*`는 게이트 기저효과 판정에서 계속 쓰이므로 지우지 않는다.
    ttm_op_t: float | None = None
    ttm_op_t1: float | None = None
    g1_t: bool | None = None
    g1_t1: bool | None = None
    # B 수익성
    opm_yoy_delta: float | None = None
    ttm_opm_delta: float | None = None
    opm: float | None = None
    sector_opm_percentile: float | None = None  # 업종 내 상위 %(작을수록 좋다)
    # C 서프라이즈
    op_surprise_pct: float | None = None
    revenue_surprise_pct: float | None = None
    #: 부호가 바뀌어 %를 만들 수 없는 구간의 라벨. `derive.op_surprise_label()`이 만든다.
    #: '흑전 서프라이즈' | '적자 쇼크' | '적자 예상 부합' | None(정상 구간)
    op_surprise_label: str | None = None
    n_estimates: int | None = None
    # D 회계 품질
    ttm_cfo: float | None = None
    ttm_op: float | None = None
    shares_yoy: float | None = None
    receivables_inventory_yoy: float | None = None
    avg_value_20d: float | None = None
    # 시점
    is_final: bool = False  # 정기보고서 확정 후인가 (D축 측정 가능)


@dataclass
class ScoreResult:
    raw: dict[str, float | None] = field(default_factory=dict)  # raw_a1 ~ raw_d4
    score_a: float | None = None
    score_b: float | None = None
    score_c: float | None = None
    score_d: float | None = None
    raw_sum: float = 0.0
    denominator: int = 0
    score_norm: float | None = None
    has_consensus: bool = False
    measured_axes: tuple[str, ...] = ()
    excluded_axes: tuple[str, ...] = ()
    #: 측정된 축 **안에서** 값이 없어 0점 처리된 항목과 그 배점.
    #: 정규화 단위는 축이므로 이건 분모에서 빠지지 않는다 — 조용한 감점이다.
    #: 화면에 드러내야 "왜 점수가 낮은지"를 읽을 수 있다.
    missing_items: dict[str, int] = field(default_factory=dict)

    @property
    def missing_item_points(self) -> int:
        return sum(self.missing_items.values())

    def as_db_row(self) -> dict:
        """screen_results에 넣을 형태. raw_* 를 전부 저장해야 사후 재계산이 가능하다."""
        row = {f"raw_{k}": v for k, v in self.raw.items()}
        row.update(
            score_a=self.score_a,
            score_b=self.score_b,
            score_c=self.score_c,
            score_d=self.score_d,
            has_consensus=self.has_consensus,
        )
        return row


def active_score(row: dict) -> float | None:
    """소비자가 읽을 현재 점수. 확정치가 있으면 우선하고 없으면 잠정치다."""
    value = row.get("score_final")
    if value is None:
        value = row.get("score_flash")
    return float(value) if value is not None else None


# ═══════════════════════════════════════════════════════════════════
# 보조 — 선형 보간 / 계단
# ═══════════════════════════════════════════════════════════════════
def _linear(value: float | None, cap: float, points: float) -> float | None:
    """0 이하 → 0점, cap 이상 → 만점, 사이는 선형."""
    if value is None:
        return None
    if value <= 0:
        return 0.0
    if value >= cap:
        return float(points)
    return value / cap * points


def _tiered(value: float | None, tiers: tuple[float, ...], scores: tuple[float, ...]) -> float | None:
    """구간별 점수. tiers는 오름차순, 마지막 구간 이상이면 최고점."""
    if value is None:
        return None
    earned = 0.0
    for threshold, score in zip(tiers, scores):
        if value >= threshold:
            earned = score
    return earned


# ═══════════════════════════════════════════════════════════════════
# A. 성장 가속 — 35점
# ═══════════════════════════════════════════════════════════════════
def score_a(data: ScoreInput) -> dict[str, float | None]:
    out: dict[str, float | None] = {}

    # A1 매출 YoY 델타 (10) — Δ≤0→0 · Δ≥20%p→만점 · 선형
    delta = (
        data.revenue_yoy_t - data.revenue_yoy_t1
        if data.revenue_yoy_t is not None and data.revenue_yoy_t1 is not None
        else None
    )
    out["a1"] = _linear(delta, A1_DELTA_MAX_PP, A_WEIGHTS["a1"])

    # A2 영업이익 YoY 델타 (15) — Δ≥40%p→만점
    # ★ A축에서 배점이 가장 큰 항목이다(2026-08-22 10→15). 이 시스템이 찾는 것은
    #   '매출이 는 회사'가 아니라 '이익이 빨라지는 회사'다.
    # ★ 부호 전환 구간에서는 op_yoy가 None이라 여기도 None이 된다(T25). 그게 맞다.
    op_delta = (
        data.op_yoy_t - data.op_yoy_t1
        if data.op_yoy_t is not None and data.op_yoy_t1 is not None
        else None
    )
    out["a2"] = _linear(op_delta, A2_DELTA_MAX_PP, A_WEIGHTS["a2"])

    # A3 TTM 영업이익 상승 (4) — 증가→절반 · 증가율 ≥5%→나머지 절반
    #
    # ★ 2026-08-22에 **TTM 매출 → TTM 영업이익**으로 바뀌었다(사용자 지시).
    #   A축은 이제 매출 1항목·이익 3항목이다.
    # ★ 증가 여부와 증가율은 **판정 가능 조건이 다르다.** 적자 구간(t−1 ≤ 0)에서도
    #   "늘었는가"는 말할 수 있지만 "몇 % 늘었는가"는 부호가 바뀌어 계산할 수 없다
    #   (CLAUDE.md 절대 금지). 그래서 증가 판정만 주고 보너스는 건너뛴다 —
    #   여기서 %를 만들어내면 적자 축소가 수백 %의 '성장'으로 둔갑한다.
    if data.ttm_op_t is None or data.ttm_op_t1 is None:
        out["a3"] = None
    else:
        half = A_WEIGHTS["a3"] / 2
        earned = 0.0
        if data.ttm_op_t > data.ttm_op_t1:
            earned += half
            if data.ttm_op_t1 > 0:
                growth = (data.ttm_op_t - data.ttm_op_t1) / data.ttm_op_t1 * 100
                if growth >= A3_TTM_OP_GROWTH_BONUS_PCT:
                    earned += half
        out["a3"] = earned

    # A4 연속 가속 (6) — 2분기 연속 G1 충족
    if data.g1_t is None or data.g1_t1 is None:
        out["a4"] = None
    else:
        out["a4"] = float(A_WEIGHTS["a4"]) if (data.g1_t and data.g1_t1) else 0.0

    return out


# ═══════════════════════════════════════════════════════════════════
# B. 수익성 — 32점
# ═══════════════════════════════════════════════════════════════════
def score_b(data: ScoreInput) -> dict[str, float | None]:
    out: dict[str, float | None] = {}

    # B1 OPM YoY %p (14) — +1%p→5 · +3%p→10 · +5%p 이상→14 (선형 보간)
    out["b1"] = _interpolate_tiers(
        data.opm_yoy_delta, B1_OPM_TIERS_PP, (5.0, 10.0, float(B_WEIGHTS["b1"]))
    )

    # B2 TTM OPM 추세 %p (7) — +0.5%p→3 · +2%p 이상→7
    out["b2"] = _interpolate_tiers(
        data.ttm_opm_delta, B2_TTM_OPM_TIERS_PP, (3.0, float(B_WEIGHTS["b2"]))
    )

    # B3 영업레버리지 (6) — op_yoy > rev_yoy
    if data.op_yoy_t is None or data.revenue_yoy_t is None:
        out["b3"] = None
    else:
        out["b3"] = float(B_WEIGHTS["b3"]) if data.op_yoy_t > data.revenue_yoy_t else 0.0

    # B4 업종 대비 OPM (5) — 상위 50%→3 · 상위 25%→5
    pct = data.sector_opm_percentile
    if pct is None:
        out["b4"] = None
    elif pct <= B4_SECTOR_TIERS_PCT[1]:
        out["b4"] = float(B_WEIGHTS["b4"])
    elif pct <= B4_SECTOR_TIERS_PCT[0]:
        out["b4"] = 3.0
    else:
        out["b4"] = 0.0

    return out


def _interpolate_tiers(
    value: float | None, tiers: tuple[float, ...], scores: tuple[float, ...]
) -> float | None:
    """구간 사이를 선형 보간한다. 첫 구간 미만은 0점에서 선형으로 올라간다."""
    if value is None:
        return None
    if value <= 0:
        return 0.0
    if value >= tiers[-1]:
        return scores[-1]
    lower_bound, lower_score = 0.0, 0.0
    for threshold, score in zip(tiers, scores):
        if value < threshold:
            span = threshold - lower_bound
            return lower_score + (value - lower_bound) / span * (score - lower_score)
        lower_bound, lower_score = threshold, score
    return scores[-1]


# ═══════════════════════════════════════════════════════════════════
# C. 서프라이즈 — 15점 (컨센서스 보유 종목만)
# ═══════════════════════════════════════════════════════════════════
def has_consensus(n_estimates: int | None) -> bool:
    """추정기관 2곳 미만은 컨센서스로 인정하지 않는다 (PRD §4.2)."""
    return n_estimates is not None and n_estimates >= MIN_ESTIMATES


def _c1_from_label(label: str | None) -> float | None:
    """부호가 바뀌어 %를 못 만드는 구간의 C1 점수.

    ★ `op_surprise_pct`는 부호 전환 구간에서 None을 준다(T25). 그대로 두면
      **적자 예상(−356억) → 흑자(+2,038억)** 같은 최고의 서프라이즈가
      '미측정'으로 빠져 9점을 조용히 잃는다(실측: 삼성SDI 2026.2Q).
      %를 계산하면 −672%가 나와 `_tiered`가 0점을 주므로 그쪽은 더 나쁘다.
    ★ 게이트가 흑전을 G2 통과로 처리하는 것과 **같은 규칙**이다 —
      새 정책이 아니라 기존 설계의 일관된 적용이다.
    ★ 둘 다 적자인 구간은 판정하지 않는다(None). 적자 폭이 예상보다 작은 것은
      개선이지만 얼마나 개선인지 %로 잴 수 없고, 흑자 전환과 같은 급으로 볼 수도 없다.
    """
    if label == "흑전 서프라이즈":
        return float(C_WEIGHTS["c1"])  # 가능한 최강의 서프라이즈
    if label == "적자 쇼크":
        return 0.0  # 흑자 예상 → 적자. 미측정이 아니라 명백한 0점이다.
    return None  # '적자 예상 부합' 또는 라벨 없음 → 호출부가 % 경로를 쓴다


def score_c(data: ScoreInput) -> dict[str, float | None]:
    if not has_consensus(data.n_estimates):
        # 컨센서스가 없으면 **0점이 아니라 미측정**이다. 여기가 이 시스템의 급소다.
        return {"c1": None, "c2": None}

    c1 = _c1_from_label(data.op_surprise_label)
    if c1 is None:
        c1 = _tiered(
            data.op_surprise_pct, C1_SURPRISE_TIERS_PCT, (3.0, 6.0, float(C_WEIGHTS["c1"]))
        )
    return {
        "c1": c1,
        "c2": _tiered(data.revenue_surprise_pct, C2_SURPRISE_TIERS_PCT, (2.0, 4.0, float(C_WEIGHTS["c2"]))),
    }


# ═══════════════════════════════════════════════════════════════════
# D. 회계 품질 — 18점 (정기보고서 확정 후에만 측정 가능)
# ═══════════════════════════════════════════════════════════════════
def score_d(data: ScoreInput) -> dict[str, float | None]:
    if not data.is_final:
        # 잠정실적 시점에는 D축 데이터가 아예 없다(PRD §2 검토⑤).
        # 0점 처리하면 모든 종목이 부당하게 낮아진다 → 미측정으로 둔다.
        return {"d1": None, "d2": None, "d3": None, "d4": None}

    out: dict[str, float | None] = {}

    # D1 현금흐름 정합성 (6) — TTM CFO > 0 → 3 · TTM CFO / TTM OP ≥ 0.5 → +3
    if data.ttm_cfo is None:
        out["d1"] = None
    else:
        earned = 3.0 if data.ttm_cfo > 0 else 0.0
        if data.ttm_op is not None and data.ttm_op > 0:
            if data.ttm_cfo / data.ttm_op >= D1_CFO_TO_OP_MIN:
                earned += 3.0
        out["d1"] = earned

    # D2 주식수 희석 (4) — YoY < +2%→4 · < +5%→2 · 그 이상→0
    if data.shares_yoy is None:
        out["d2"] = None
    elif data.shares_yoy < D2_DILUTION_TIERS_PCT[0]:
        out["d2"] = float(D_WEIGHTS["d2"])
    elif data.shares_yoy < D2_DILUTION_TIERS_PCT[1]:
        out["d2"] = 2.0
    else:
        out["d2"] = 0.0

    # D3 운전자본 (4) — (매출채권+재고) YoY < 매출 YoY
    if data.receivables_inventory_yoy is None or data.revenue_yoy_t is None:
        out["d3"] = None
    else:
        out["d3"] = (
            float(D_WEIGHTS["d3"])
            if data.receivables_inventory_yoy < data.revenue_yoy_t
            else 0.0
        )

    # D4 유동성 (4) — 20일 평균 거래대금 ≥ 10억→4 · ≥ 5억→2
    out["d4"] = _tiered(
        data.avg_value_20d, D4_LIQUIDITY_TIERS_KRW, (2.0, float(D_WEIGHTS["d4"]))
    )
    return out


# ═══════════════════════════════════════════════════════════════════
# ★ 정규화 — 이 프로젝트에서 가장 중요한 계산 규칙
# ═══════════════════════════════════════════════════════════════════
_AXIS_ITEMS = {"A": ("a1", "a2", "a3", "a4"), "B": ("b1", "b2", "b3", "b4"),
               "C": ("c1", "c2"), "D": ("d1", "d2", "d3", "d4")}


def compute_score(data: ScoreInput) -> ScoreResult:
    raw: dict[str, float | None] = {}
    raw.update(score_a(data))
    raw.update(score_b(data))
    raw.update(score_c(data))
    raw.update(score_d(data))

    result = ScoreResult(raw=raw, has_consensus=has_consensus(data.n_estimates))

    measured: list[str] = []
    excluded: list[str] = []
    raw_sum = 0.0
    denominator = 0

    for axis, items in _AXIS_ITEMS.items():
        values = [raw[i] for i in items]
        if all(v is None for v in values):
            # 축 전체가 미측정 → **분모에서 제외**한다 (0점 처리 금지)
            excluded.append(axis)
            setattr(result, f"score_{axis.lower()}", None)
            continue
        # 축 안의 개별 항목 결측은 0으로 본다 — 정규화의 단위가 '축'이기 때문이다(PRD §4.2).
        # 다만 그 감점은 분모에 반영되지 않으므로 **조용한 감점**이다.
        # 어떤 항목이 얼마를 못 받았는지 반드시 기록해 화면에 드러낸다.
        weights = {"A": A_WEIGHTS, "B": B_WEIGHTS, "C": C_WEIGHTS, "D": D_WEIGHTS}[axis]
        for item, value in zip(items, values):
            if value is None:
                result.missing_items[item] = weights[item]
        axis_score = sum(v for v in values if v is not None)
        setattr(result, f"score_{axis.lower()}", axis_score)
        measured.append(axis)
        raw_sum += axis_score
        denominator += SCORE_WEIGHTS[axis]

    result.raw_sum = raw_sum
    result.denominator = denominator
    result.measured_axes = tuple(measured)
    result.excluded_axes = tuple(excluded)
    result.score_norm = (raw_sum / denominator * 100) if denominator else None
    return result
