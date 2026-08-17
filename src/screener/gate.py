# PRD Ref: §4.1 (게이트) · traps.md T12, T14
"""게이트 판정 — **순수 함수. 외부 I/O 금지.**

전부 AND. 하나라도 실패하면 알림 대상이 아니다.

★ `False`와 `None`을 반드시 구분한다.
  `False` = "조건을 못 넘었다(탈락)"  ·  `None` = "데이터가 없어 판정 불가"
  둘을 뭉개면 데이터 결측 종목이 전부 '탈락'으로 조용히 사라진다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GateInput:
    """게이트 입력. **모든 항목이 Optional이다.**"""

    # G0 — 존재 확인용 원자료
    revenue_t: float | None = None
    revenue_t1: float | None = None
    revenue_t4: float | None = None
    op_t: float | None = None
    op_t1: float | None = None
    op_t4: float | None = None
    # G1 / G2 — 파생지표
    revenue_yoy_t: float | None = None
    revenue_yoy_t1: float | None = None
    op_yoy_t: float | None = None
    op_status_label: str | None = None  # 부호 전환 구간이면 op_yoy가 None이다
    # 기저효과 보조 판정 (PRD §4.1)
    rev_2y_t: float | None = None
    rev_2y_t1: float | None = None
    ttm_revenue_t: float | None = None
    ttm_revenue_history: tuple[float, ...] = ()  # 최근 8분기 TTM (t 포함)
    revenue_last4: tuple[float, ...] = ()  # revenue(t-1..t-4)
    # G3
    is_excluded: bool = False
    exclude_reason: str | None = None
    quarters_since_listing: int | None = None
    min_quarters: int = 5
    fiscal_quarter: int | None = None  # 4Q는 QoQ 관련 판정을 하지 않는다 (T14)


@dataclass
class GateResult:
    g0: bool | None = None
    g1: bool | None = None
    g2: bool | None = None
    g3: bool | None = None
    passed: bool | None = None
    turnaround: bool = False
    base_effect_warning: bool = False
    #: 기저효과 3조건 각각의 판정. None이 섞여 있으면 경고의 신뢰도가 낮다.
    base_effect_checks: dict[str, bool | None] = field(default_factory=dict)
    detail: dict = field(default_factory=dict)

    @property
    def base_effect_measurable(self) -> bool:
        """3조건 중 하나라도 실제로 판정됐는가.

        전부 None인데 경고를 붙이면 "데이터가 없다"를 "기저효과다"로 바꿔치기하는 셈이다.
        """
        return any(v is not None for v in self.base_effect_checks.values())


def _all_present(*values) -> bool:
    return all(v is not None for v in values)


def evaluate_gate(data: GateInput) -> GateResult:
    result = GateResult()

    # ── G0: 판정에 필요한 원자료가 모두 있는가 ──
    result.g0 = _all_present(
        data.revenue_t, data.revenue_t1, data.revenue_t4,
        data.op_t, data.op_t1, data.op_t4,
    )
    if not result.g0:
        # 판정 불가. False(탈락)가 아니라 None으로 둔다.
        result.passed = None
        result.detail["missing"] = [
            name
            for name, value in (
                ("revenue_t", data.revenue_t), ("revenue_t1", data.revenue_t1),
                ("revenue_t4", data.revenue_t4), ("op_t", data.op_t),
                ("op_t1", data.op_t1), ("op_t4", data.op_t4),
            )
            if value is None
        ]
        return result

    # ── G1: 매출 YoY가 가속하고 있으며 양(+)인가 ──
    if _all_present(data.revenue_yoy_t, data.revenue_yoy_t1):
        result.g1 = data.revenue_yoy_t > data.revenue_yoy_t1 and data.revenue_yoy_t > 0
        result.detail["rev_yoy_delta_pp"] = data.revenue_yoy_t - data.revenue_yoy_t1
    else:
        result.g1 = None

    # ── G2: 영업이익이 흑자이고 성장하는가 ──
    # ★ 부호 전환 구간에서는 op_yoy가 None이다(T12·T25). 그때는 라벨로 판정한다.
    if data.op_t is None:
        result.g2 = None
    elif data.op_t <= 0:
        result.g2 = False  # 적자는 탈락 — 판정 불가가 아니다
        result.turnaround = data.op_status_label == "적자축소"
    elif data.op_status_label == "흑전":
        # 전년 적자 → 당기 흑자. %는 못 구하지만 "이익이 늘었다"는 명백하다.
        result.g2 = True
        result.turnaround = True
    elif data.op_yoy_t is None:
        result.g2 = None
    else:
        result.g2 = data.op_yoy_t > 0

    # ── G3: 업종 제외 · 관리종목 · 스팩 · 히스토리 부족 ──
    if data.is_excluded:
        result.g3 = False
        result.detail["exclude_reason"] = data.exclude_reason
    elif (
        data.quarters_since_listing is not None
        and data.quarters_since_listing < data.min_quarters
    ):
        result.g3 = False
        result.detail["exclude_reason"] = "young_listing"
    else:
        result.g3 = True

    # ── 종합: False가 하나라도 있으면 탈락, 없고 None이 있으면 판정 불가 ──
    verdicts = (result.g1, result.g2, result.g3)
    if False in verdicts:
        result.passed = False
    elif None in verdicts:
        result.passed = None
    else:
        result.passed = True

    result.base_effect_warning, result.base_effect_checks = _base_effect(data)
    return result


def _base_effect(data: GateInput) -> tuple[bool, dict[str, bool | None]]:
    """기저효과 경고 (PRD §4.1).

    3개 중 **하나도** 충족하지 못하면 경고. 하나라도 충족하면 경고 없음.
    ★ 전부 판정 불가(None)이면 경고를 붙이지 않는다 —
      "데이터가 없다"를 "기저효과다"로 바꿔치기하면 안 된다.
      대신 `base_effect_measurable`이 False가 되어 화면에서 그 사실을 드러낸다.
    """
    checks: dict[str, bool | None] = {}

    # ① 2년 스택도 가속하는가
    checks["rev_2y_accel"] = (
        data.rev_2y_t > data.rev_2y_t1
        if _all_present(data.rev_2y_t, data.rev_2y_t1)
        else None
    )

    # ② TTM 매출이 최근 8분기 TTM 중 최고인가
    if data.ttm_revenue_t is not None and len(data.ttm_revenue_history) >= 2:
        checks["ttm_revenue_high"] = data.ttm_revenue_t >= max(data.ttm_revenue_history)
    else:
        checks["ttm_revenue_high"] = None

    # ③ 분기 매출이 최근 4분기 최고를 경신했는가
    if data.revenue_t is not None and len(data.revenue_last4) >= 1:
        checks["quarter_revenue_high"] = data.revenue_t > max(data.revenue_last4)
    else:
        checks["quarter_revenue_high"] = None

    measured = [v for v in checks.values() if v is not None]
    warning = bool(measured) and not any(measured)
    return warning, checks
