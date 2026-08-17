# PRD Ref: §6(quarterly_fundamentals), §2 검토①②, §4 · traps.md T12, T14
"""파생지표 계산 — 성장률 · 마진 · TTM · 2년 스택.

★ 외부 I/O 금지. 순수 함수만 둔다.

지켜야 할 것 두 가지가 전부다:

1. **부호가 바뀌는 구간에서 % 계산 금지** (T12).
   분모가 0 이하이면 `None`을 돌려주고 `op_status_label`에
   '흑전'|'적전'|'적자축소'|'적자확대' 중 하나를 넣는다.
   적자 기업의 "영업이익 −50억 → −10억"을 +80% 성장으로 쓰면 게이트가 통째로 뒤집힌다.

2. **TTM은 4개 분기가 전부 있을 때만 계산한다.**
   하나라도 없으면 `None`. 결측을 0으로 채우면 TTM이 실제보다 낮게 나와
   **가짜 악화**로 보이는데 에러는 나지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass

#: (회계연도, 분기) → 연속된 정수 인덱스. t-1 / t-4 / t-8 계산을 단순하게 만든다.
def qindex(year: int, quarter: int) -> int:
    return year * 4 + (quarter - 1)


def qkey(index: int) -> tuple[int, int]:
    return divmod(index, 4)[0], divmod(index, 4)[1] + 1


@dataclass(frozen=True)
class QuarterPoint:
    """분기 원자료 1건."""

    revenue: float | None = None
    op: float | None = None
    np: float | None = None


@dataclass
class Derived:
    """분기 파생지표 1건. 측정 불가는 전부 None (0이 아니다)."""

    revenue_yoy: float | None = None
    revenue_qoq: float | None = None
    op_yoy: float | None = None
    op_qoq: float | None = None
    np_yoy: float | None = None
    op_status_label: str | None = None
    opm: float | None = None
    opm_yoy_delta: float | None = None
    opm_qoq_delta: float | None = None
    npm: float | None = None
    ttm_revenue: float | None = None
    ttm_op: float | None = None
    ttm_opm: float | None = None
    ttm_revenue_qoq: float | None = None
    ttm_opm_delta: float | None = None
    rev_2y_stack: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def growth_pct(current: float | None, base: float | None) -> float | None:
    """성장률(%). 분모가 0 이하이면 계산하지 않는다.

    매출처럼 **음수가 될 수 없는 항목**에 쓴다. 매출 100 → 0은 −100%로
    의미가 있으므로 분자는 제한하지 않는다.
    """
    if current is None or base is None:
        return None
    if base <= 0:
        return None
    return (current - base) / base * 100.0


def profit_growth_pct(current: float | None, base: float | None) -> float | None:
    """손익 항목 성장률(%). **부호가 바뀌면 계산하지 않는다** (T12).

    ★ 분모만 막으면 부족하다. 흑자(+100) → 적자(−30)는 분모가 양수라
      `growth_pct`가 −130%를 내놓는데, 이건 "성장률 −130%"가 아니라
      **적자전환**이다. 숫자로 남기면 스코어 A2·B축이 그 값을 그대로 먹는다.
      실측: 이 구분을 안 했을 때 '적전' 447건 전부에 %가 붙었다.

    부호가 바뀌는 구간은 `op_status_label`이 담당한다.
    """
    if current is None or base is None:
        return None
    if base <= 0 or current <= 0:
        return None
    return (current - base) / base * 100.0


def revenue_surprise_pct(actual: float | None, estimate: float | None) -> float | None:
    """매출 서프라이즈(%). 스코어 C2의 입력.

    매출 추정치는 음수가 될 수 없으므로 분모만 막는다 — `growth_pct`와 같은 규칙이다.
    """
    return growth_pct(actual, estimate)


def op_surprise_pct(actual: float | None, estimate: float | None) -> float | None:
    """영업이익 서프라이즈(%). 스코어 C1의 입력. **부호가 바뀌면 계산하지 않는다.**

    ★ 성장률과 똑같은 함정이 여기에도 있다(T25). 적자를 예상했는데(−100억)
      흑자가 났다면(+50억) `(50−(−100))/(−100) = −150%`가 나온다.
      **최고의 서프라이즈가 최악의 점수로 뒤집힌다** — `_tiered`는 −150을
      "기준 미달"로 읽어 0점을 준다. 에러는 없다.
    ★ 반대(흑자 예상 → 적자)도 분모가 양수라 통과해버리므로 분자도 함께 막는다.

    부호가 바뀌는 구간은 `op_surprise_label`이 담당한다.
    """
    return profit_growth_pct(actual, estimate)


def op_surprise_label(actual: float | None, estimate: float | None) -> str | None:
    """영업이익 서프라이즈 부호 전환 라벨. 정상 구간(둘 다 양수)이면 None.

    `op_status_label`과 같은 규칙이되 비교 대상이 '전년동기'가 아니라 '컨센서스'다.
    """
    if actual is None or estimate is None:
        return None
    if estimate > 0 and actual > 0:
        return None  # 정상 — % 계산이 가능하다
    if estimate <= 0 < actual:
        return "흑전 서프라이즈"  # 적자 예상 → 흑자: % 대신 라벨로 남긴다
    if estimate > 0 >= actual:
        return "적자 쇼크"  # 흑자 예상 → 적자
    return "적자 예상 부합"  # 둘 다 0 이하


def op_status_label(current: float | None, base: float | None) -> str | None:
    """영업이익 부호 전환 라벨. 정상 구간(둘 다 양수)이면 None."""
    if current is None or base is None:
        return None
    if base > 0 and current > 0:
        return None  # 정상 — growth_pct로 % 계산이 가능하다
    if base <= 0 < current:
        return "흑전"
    if base > 0 >= current:
        return "적전"
    # 둘 다 0 이하
    # 정확히 같은 값은 '축소'도 '확대'도 아니지만 실무상 발생하지 않는다.
    # 판정 불가(None)로 두면 "적자"라는 사실 자체가 사라지므로 '적자축소'에 붙인다.
    return "적자축소" if current >= base else "적자확대"


def margin_pct(numerator: float | None, revenue: float | None) -> float | None:
    """마진(%). 매출이 0 이하이면 계산하지 않는다."""
    if numerator is None or revenue is None or revenue <= 0:
        return None
    return numerator / revenue * 100.0


def delta_pp(current: float | None, base: float | None) -> float | None:
    """%p 차이. 마진은 음수여도 뺄셈이 의미를 가지므로 부호 제한이 없다."""
    if current is None or base is None:
        return None
    return current - base


def _ttm(series: Mapping[int, QuarterPoint], index: int, field: str) -> float | None:
    """t-3 ~ t의 4분기 합. **하나라도 없으면 None** — 0으로 채우지 않는다."""
    total = 0.0
    for offset in range(4):
        point = series.get(index - offset)
        if point is None:
            return None
        value = getattr(point, field)
        if value is None:
            return None
        total += value
    return total


def derive_series(
    points: Mapping[tuple[int, int], QuarterPoint],
) -> dict[tuple[int, int], Derived]:
    """한 종목의 분기 시계열 전체에 대해 파생지표를 계산한다."""
    series = {qindex(y, q): p for (y, q), p in points.items()}
    out: dict[tuple[int, int], Derived] = {}

    for index, point in series.items():
        prev = series.get(index - 1)  # 직전 분기 (Q1이면 전년 4Q)
        yoy = series.get(index - 4)  # 전년 동기
        two_year = series.get(index - 8)  # 2년 전 동기

        derived = Derived()

        # ── 성장률 ──
        derived.revenue_yoy = growth_pct(point.revenue, yoy.revenue if yoy else None)
        derived.revenue_qoq = growth_pct(point.revenue, prev.revenue if prev else None)
        # 손익 항목은 부호 전환 구간에서 % 계산을 막는다 (T12)
        derived.op_yoy = profit_growth_pct(point.op, yoy.op if yoy else None)
        derived.op_qoq = profit_growth_pct(point.op, prev.op if prev else None)
        derived.np_yoy = profit_growth_pct(point.np, yoy.np if yoy else None)
        derived.op_status_label = op_status_label(point.op, yoy.op if yoy else None)

        # ── 마진 ──
        derived.opm = margin_pct(point.op, point.revenue)
        derived.npm = margin_pct(point.np, point.revenue)
        derived.opm_yoy_delta = delta_pp(
            derived.opm, margin_pct(yoy.op, yoy.revenue) if yoy else None
        )
        derived.opm_qoq_delta = delta_pp(
            derived.opm, margin_pct(prev.op, prev.revenue) if prev else None
        )

        # ── TTM (계절성 제거) ──
        derived.ttm_revenue = _ttm(series, index, "revenue")
        derived.ttm_op = _ttm(series, index, "op")
        derived.ttm_opm = margin_pct(derived.ttm_op, derived.ttm_revenue)

        prev_ttm_revenue = _ttm(series, index - 1, "revenue")
        prev_ttm_op = _ttm(series, index - 1, "op")
        derived.ttm_revenue_qoq = growth_pct(derived.ttm_revenue, prev_ttm_revenue)
        derived.ttm_opm_delta = delta_pp(
            derived.ttm_opm, margin_pct(prev_ttm_op, prev_ttm_revenue)
        )

        # ── 2년 스택 (기저효과 방어 — PRD §2 검토①) ──
        derived.rev_2y_stack = growth_pct(
            point.revenue, two_year.revenue if two_year else None
        )

        out[qkey(index)] = derived

    return out
