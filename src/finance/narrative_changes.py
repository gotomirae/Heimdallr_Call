# PRD Ref: §7.1 · traps.md T12, T110
"""LLM 서술에 공급할 분기 절대 증감액.

순수 계산 계층이다. 외부 I/O가 없고, 매출·영업이익의 정확한 YoY/QoQ 비교 분기가
모두 있을 때만 원 단위 차액을 만든다. 가까운 분기로 물러서거나 결측을 0으로 채우지
않는다. 성장률은 ``derive.py``가 담당하며 이 모듈은 새 비율을 계산하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from src.finance.derive import op_status_label, qindex, qkey


@dataclass(frozen=True)
class AmountChange:
    """한 재무 항목의 원 단위 현재값·기준값·절대 차액."""

    current_krw: Decimal | None
    base_krw: Decimal | None
    delta_krw: Decimal | None
    status_label: str | None = None


@dataclass(frozen=True)
class PeriodComparison:
    """대상 분기와 정확한 비교 분기 한 쌍."""

    kind: str
    current_period: tuple[int, int]
    base_period: tuple[int, int]
    revenue: AmountChange
    op: AmountChange
    opm_delta_pp: Decimal | None


@dataclass(frozen=True)
class NarrativeChanges:
    """LLM에 전달할 YoY/QoQ 절대 증감 두 묶음."""

    yoy: PeriodComparison
    qoq: PeriodComparison


def _index_quarters(
    quarters: list[dict[str, Any]],
) -> dict[tuple[int, int], dict[str, Any]]:
    """분기 키를 검증하고 중복 없는 색인을 만든다."""
    by_period: dict[tuple[int, int], dict[str, Any]] = {}
    for row in quarters:
        year, quarter = row.get("fiscal_year"), row.get("fiscal_quarter")
        if not isinstance(year, int) or isinstance(year, bool):
            raise ValueError(f"유효하지 않은 회계연도: {year!r}")
        valid_quarter = (
            isinstance(quarter, int)
            and not isinstance(quarter, bool)
            and quarter in (1, 2, 3, 4)
        )
        if not valid_quarter:
            raise ValueError(f"유효하지 않은 회계분기: {quarter!r}")
        period = (year, quarter)
        if period in by_period:
            raise ValueError(f"중복 분기: {year}.{quarter}Q")
        by_period[period] = row
    return by_period


def _validate_target(fiscal_year: int, fiscal_quarter: int) -> None:
    if not isinstance(fiscal_year, int) or isinstance(fiscal_year, bool):
        raise ValueError("fiscal_year는 정수여야 한다")
    if not isinstance(fiscal_quarter, int) or isinstance(fiscal_quarter, bool):
        raise ValueError("fiscal_quarter는 정수여야 한다")
    if fiscal_quarter not in (1, 2, 3, 4):
        raise ValueError("fiscal_quarter는 1~4여야 한다")


def select_quarter_window(
    quarters: list[dict[str, Any]],
    fiscal_year: int,
    fiscal_quarter: int,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """요청 분기까지의 최근 ``limit``개 분기만 시간순으로 고른다.

    DB의 최신 행을 기준으로 자르면 과거 replay에 미래 실적이 섞인다. 요청 분기 자체가
    없으면 당시 입력을 재현할 수 없으므로 가까운 분기를 대신 쓰지 않고 실패시킨다.
    """
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise ValueError("limit은 양의 정수여야 한다")
    _validate_target(fiscal_year, fiscal_quarter)
    by_period = _index_quarters(quarters)
    target = (fiscal_year, fiscal_quarter)
    if target not in by_period:
        raise ValueError(f"대상 분기 {fiscal_year}.{fiscal_quarter}Q가 없다")
    target_index = qindex(*target)
    eligible = sorted(
        (period for period in by_period if qindex(*period) <= target_index),
        key=lambda period: qindex(*period),
    )
    return [by_period[period] for period in eligible[-limit:]]


def _amount(row: dict[str, Any] | None, field: str) -> Decimal | None:
    if row is None or row.get(field) is None:
        return None
    value = row[field]
    if isinstance(value, bool):
        raise ValueError(f"{field}: bool은 재무 숫자가 아니다")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field}: 숫자가 아닌 값 {value!r}") from exc
    if not amount.is_finite():
        raise ValueError(f"{field}: 유한하지 않은 값 {value!r}")
    return amount


def _change(
    current: dict[str, Any] | None,
    base: dict[str, Any] | None,
    field: str,
    *,
    with_profit_status: bool = False,
) -> AmountChange:
    current_amount = _amount(current, field)
    base_amount = _amount(base, field)
    delta = (
        current_amount - base_amount
        if current_amount is not None and base_amount is not None
        else None
    )
    status = (
        op_status_label(
            float(current_amount) if current_amount is not None else None,
            float(base_amount) if base_amount is not None else None,
        )
        if with_profit_status
        else None
    )
    return AmountChange(current_amount, base_amount, delta, status)


def calculate_narrative_changes(
    quarters: list[dict[str, Any]], fiscal_year: int, fiscal_quarter: int
) -> NarrativeChanges:
    """대상 분기의 YoY/QoQ 절대 증감액을 계산한다.

    분기 중복은 어느 행이 맞는지 추측할 수 없으므로 실패시킨다. 비교 분기가 없거나
    항목이 결측이면 그 항목의 ``delta_krw``는 ``None``이다.
    """
    _validate_target(fiscal_year, fiscal_quarter)

    current_period = (fiscal_year, fiscal_quarter)
    by_period = _index_quarters(quarters)
    if current_period not in by_period:
        raise ValueError(f"대상 분기 {fiscal_year}.{fiscal_quarter}Q가 없다")
    yoy_period = (fiscal_year - 1, fiscal_quarter)
    qoq_period = qkey(qindex(fiscal_year, fiscal_quarter) - 1)
    current = by_period.get(current_period)

    def comparison(kind: str, base_period: tuple[int, int]) -> PeriodComparison:
        base = by_period.get(base_period)
        current_opm = _amount(current, "opm")
        base_opm = _amount(base, "opm")
        return PeriodComparison(
            kind=kind,
            current_period=current_period,
            base_period=base_period,
            revenue=_change(current, base, "revenue"),
            op=_change(current, base, "op", with_profit_status=True),
            opm_delta_pp=(
                current_opm - base_opm
                if current_opm is not None and base_opm is not None
                else None
            ),
        )

    return NarrativeChanges(
        yoy=comparison("YoY", yoy_period),
        qoq=comparison("QoQ", qoq_period),
    )
