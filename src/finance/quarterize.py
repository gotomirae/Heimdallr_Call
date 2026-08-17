# PRD Ref: §5.3, §12 T1 · traps.md T1
"""DART 정기보고서 누적치 → 분기 단독값 분해. **이 프로젝트의 급소.**

★ 외부 I/O 금지. 순수 함수만 둔다.

─────────────────────────────────────────────────────────────────────
실측으로 확정한 규칙 (2026-08-13, `fnlttMultiAcnt.json`,
삼성전자(CFS) · 리노공업(OFS) · 에스티아이(CFS) 3사 교차 확인)

| 보고서 | reprt_code | `thstrm_amount` | `thstrm_add_amount` |
|---|---|---|---|
| 1분기  | 11013 | 3개월 단독 | 3개월 누적 (= 같은 값) |
| 반기   | 11012 | **3개월 단독(Q2)** | **6개월 누적** |
| 3분기  | 11014 | 3개월 단독(Q3) | 9개월 누적 |
| 사업   | 11011 | **12개월 연간** | **None (없음)** |

⚠️ PRD §12 T1과 traps.md T1은 "반기보고서의 `thstrm_amount` = 6개월 누적"이라고
   적고 있으나, 이 엔드포인트에서는 그렇지 않다. 실측이 우선이다.
   다만 회사·계정에 따라 다를 수 있으므로 **이 모듈은 `thstrm_amount`를
   신뢰의 근거로 삼지 않는다.**

따라서 분해는 항상 **누적(add_amount)의 차분**으로 한다:

    Q1 = 누적(1Q)
    Q2 = 누적(반기) − 누적(1Q)
    Q3 = 누적(3Q)  − 누적(반기)
    Q4 = 연간      − 누적(3Q)

`thstrm_amount`는 **교차검증에만** 쓴다. 차분과 어긋나면 `standalone_mismatch`에
남겨 화면에 드러낸다 — 조용히 한쪽을 고르지 않는다.

필요한 누적이 하나라도 없으면 **`None`**을 돌려준다. 0으로 채우면
그 분기 매출이 통째로 부풀거나 사라지는데 에러는 나지 않는다.
─────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

REPRT_1Q = "11013"
REPRT_H1 = "11012"
REPRT_3Q = "11014"
REPRT_FY = "11011"

#: 분기 번호 → 그 분기의 누적을 담고 있는 보고서
_REPORT_FOR_QUARTER: dict[int, str] = {
    1: REPRT_1Q,
    2: REPRT_H1,
    3: REPRT_3Q,
    4: REPRT_FY,
}


@dataclass(frozen=True)
class ReportFigure:
    """한 보고서에서 읽은 한 계정의 값.

    amount     : `thstrm_amount`     (당기)
    add_amount : `thstrm_add_amount` (당기누적) — 사업보고서에는 없다
    """

    amount: int | None = None
    add_amount: int | None = None


@dataclass(frozen=True)
class QuarterValue:
    """분기 단독값 1건. 값이 없으면 반드시 `reason`이 있다."""

    value: int | None
    source: str | None = None  # 'direct'|'cumulative_diff'|'annual_minus_3q'
    reason: str | None = None  # 'missing_report'|'missing_prior_cumulative'|...
    standalone_mismatch: int | None = None  # 회사 신고 단독값 − 차분값

    @property
    def is_measured(self) -> bool:
        """값이 있는가. 0과 None을 구분하기 위해 별도 프로퍼티로 둔다."""
        return self.value is not None


def _cumulative(fig: ReportFigure | None, reprt_code: str) -> tuple[int | None, str | None]:
    """해당 보고서가 담고 있는 '누적값'을 꺼낸다. (값, 실패사유)"""
    if fig is None:
        return None, "missing_report"

    if reprt_code == REPRT_FY:
        # 사업보고서는 add_amount가 없고 thstrm_amount가 연간 누적이다(실측).
        # 드물게 add_amount가 채워져 오면 그쪽을 우선한다.
        value = fig.add_amount if fig.add_amount is not None else fig.amount
        return (value, None) if value is not None else (None, "missing_amount")

    if fig.add_amount is not None:
        return fig.add_amount, None

    if reprt_code == REPRT_1Q and fig.amount is not None:
        # 1분기는 3개월 단독 == 3개월 누적이라 amount로 대체해도 안전하다.
        return fig.amount, None

    if fig.amount is not None:
        # 반기/3분기에 누적이 없으면 amount가 3개월인지 누적인지 알 수 없다.
        # 추측하면 Q2가 2배로 잡힌다. 판정 불가로 둔다.
        return None, "no_cumulative_in_interim_report"

    return None, "missing_amount"


def quarterize(reports: Mapping[str, ReportFigure]) -> dict[int, QuarterValue]:
    """한 회사·한 계정·한 회계연도의 보고서들을 분기 단독값으로 분해한다.

    `reports`의 키는 reprt_code('11013'|'11012'|'11014'|'11011').
    반환값은 항상 1~4 전 분기를 담는다(측정 못 한 분기는 value=None).
    """
    cumulative: dict[int, int | None] = {}
    failure: dict[int, str | None] = {}
    for quarter, code in _REPORT_FOR_QUARTER.items():
        cumulative[quarter], failure[quarter] = _cumulative(reports.get(code), code)

    result: dict[int, QuarterValue] = {}
    for quarter in (1, 2, 3, 4):
        current = cumulative[quarter]
        if current is None:
            result[quarter] = QuarterValue(None, reason=failure[quarter])
            continue

        if quarter == 1:
            value, source = current, "direct"
        else:
            prior = cumulative[quarter - 1]
            if prior is None:
                # ★ 앞 분기 누적이 없으면 이번 분기를 계산할 수 없다. 0으로 채우지 않는다.
                result[quarter] = QuarterValue(None, reason="missing_prior_cumulative")
                continue
            value = current - prior
            source = "annual_minus_3q" if quarter == 4 else "cumulative_diff"

        # 교차검증: 회사가 신고한 단독값과 차분이 어긋나는지 본다(사업보고서는 제외 —
        # thstrm_amount가 연간이라 비교 대상이 아니다).
        mismatch: int | None = None
        if quarter != 4:
            standalone = reports[_REPORT_FOR_QUARTER[quarter]].amount
            if standalone is not None:
                mismatch = standalone - value

        result[quarter] = QuarterValue(
            value=value, source=source, standalone_mismatch=mismatch
        )

    return result
