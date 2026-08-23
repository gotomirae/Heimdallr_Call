# PRD Ref: §8 · §9.1 — 밸류에이션 배수
"""PER 두 종류를 계산한다. **순수 함수 — 외부 I/O 금지.**

★★ **후행 PER(`price_snapshots.per`)을 쓰지 마라.**
   그 값은 **직전 사업연도 EPS 기준**이라 실적이 급가속하면 크게 과대평가된다.
   실측(2026-08-23):

       고영        스냅샷 131.63  ≈ 2025 연간 기준 130.8   실제 TTM  40.5
       삼화콘덴서   스냅샷  75.12  ≈ 2025 연간 기준  74.7   실제 TTM  48.8
       삼성전자     스냅샷  42.89  ≈ 2025 연간 기준  36.4   실제 TTM  10.9

   이 시스템은 **실적이 급가속하는 종목만** 고르므로 그 왜곡이 항상 최악으로 걸린다.
   나란히 두면 큰 쪽에 눈이 가서 "이미 비싸다"는 정반대 결론이 나온다.

★ 이 모듈은 `dashboard/lib/valuation.ts`와 **같은 규칙**이어야 한다.
  한쪽만 고치면 같은 종목에서 화면과 LLM 분석이 다른 배수를 말한다.
  `tests/test_valuation.py`가 손계산으로 대조한다.
"""

from __future__ import annotations


def _qi(year: int, quarter: int) -> int:
    return year * 4 + (quarter - 1)


def ttm_net_income(funds: list[dict], year: int, quarter: int) -> float | None:
    """그 분기까지의 4분기 누적 순이익. **최근 4분기 PER의 분모다.**

    ★ 4개 분기가 다 모이지 않으면 **연율화하지 않고 None**을 준다.
      3분기치를 ×4/3 하면 계절성이 강한 한국 기업에서 조용히 틀린다.
    """
    index = _qi(year, quarter)
    by_index = {_qi(f["fiscal_year"], f["fiscal_quarter"]): f for f in funds}
    values = [(by_index.get(index - o) or {}).get("np") for o in range(4)]
    if any(v is None for v in values):
        return None
    return sum(float(v) for v in values)


def trailing_4q_per(market_cap: float | None, ttm_np: float | None) -> float | None:
    """시가총액 ÷ 최근 4분기 순이익. 이익이 0 이하면 배수가 의미를 잃으므로 None."""
    if not market_cap or ttm_np is None or ttm_np <= 0:
        return None
    return float(market_cap) / ttm_np


def forward_per_annual(
    annual_np_est: float | None,
    annual_fiscal_year: int | None,
    funds: list[dict],
    market_cap: float | None,
) -> tuple[float | None, str | None]:
    """향후 4개 분기 추정 순이익 기준 선행 PER. `(per, basis)`를 준다.

    재료는 **연간 컨센서스**(`fiscal_quarter = 0`)다. 분기 컨센은 한 분기뿐이라
    '향후 4분기'를 만들 수 없다.

    계산:
      1) 그 회계연도에서 **이미 발표된 분기 순이익**을 연간 추정에서 뺀다 → 남은 분기 추정
      2) 남은 분기가 4개에 모자라면 **연간 추정의 분기 평균**으로 이어 붙인다
         (다음 해 추정치를 수집하지 않기 때문 — 추정 위의 추정이라 basis에 밝힌다)

    ★ 컨센서스가 없으면 **만들어내지 않는다.** `(None, None)`이다.
    """
    if annual_np_est is None or annual_np_est <= 0 or not market_cap or annual_fiscal_year is None:
        return None, None

    by_index = {_qi(f["fiscal_year"], f["fiscal_quarter"]): f for f in funds}
    reported = [
        (by_index.get(_qi(annual_fiscal_year, q)) or {}).get("np") for q in (1, 2, 3, 4)
    ]
    done = [float(v) for v in reported if v is not None]
    remaining = 4 - len(done)
    basis = f"{annual_fiscal_year}년 컨센 {round(annual_np_est / 1e8):,}억 기준"

    if remaining <= 0:
        # 그 해가 다 발표됐으면 연간 추정 자체가 '다음 4분기'다.
        return float(market_cap) / annual_np_est, f"{annual_fiscal_year}년 컨센 기준"

    remaining_np = annual_np_est - sum(done)
    per_quarter = remaining_np / remaining
    next4 = remaining_np + per_quarter * (4 - remaining)
    return (float(market_cap) / next4 if next4 > 0 else None), basis
