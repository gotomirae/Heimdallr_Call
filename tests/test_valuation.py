# PRD Ref: §8 · §9.1 — 밸류에이션 배수
"""PER 계산 — **손계산 대조**. 순수 함수라 외부 I/O가 없다.

★ 이 규칙은 `dashboard/lib/valuation.ts`와 같아야 한다. 한쪽만 고치면
  같은 종목에서 화면과 LLM 분석이 **다른 배수**를 말한다.
"""

from __future__ import annotations

import pytest

from src.finance.valuation import (
    forward_per_annual,
    trailing_4q_per,
    ttm_net_income,
)

# 억원 단위를 원으로.
E8 = 100_000_000


def _funds(*rows: tuple[int, int, float | None]) -> list[dict]:
    return [
        {"fiscal_year": y, "fiscal_quarter": q, "np": None if np is None else np * E8}
        for y, q, np in rows
    ]


# ═══ TTM 순이익 ═══
def test_ttm_sums_exactly_four_quarters():
    """손계산: 157 + 157 + 78 + 85 = 477억 (고영 2026.2Q 실측값)."""
    funds = _funds(
        (2025, 2, -47.0), (2025, 3, 84.5), (2025, 4, 78.0),
        (2026, 1, 156.8), (2026, 2, 157.2),
    )
    ttm = ttm_net_income(funds, 2026, 2)
    assert ttm == pytest.approx((157.2 + 156.8 + 78.0 + 84.5) * E8)


def test_ttm_is_none_when_a_quarter_is_missing():
    """★ 3분기치를 연율화(×4/3)하지 않는다 — 계절성이 강해 조용히 틀린다."""
    funds = _funds((2025, 4, 78.0), (2026, 1, 156.8), (2026, 2, 157.2))
    assert ttm_net_income(funds, 2026, 2) is None


def test_ttm_is_none_when_np_column_absent():
    """★★ `np`를 안 실어 오면 **전 종목이 조용히 계산 불가**가 된다.

    실측(2026-08-23): `analysis/run.py`의 FUND_COLUMNS에 `np`가 빠져 있어
    LLM 입력의 최근 4분기 PER이 전부 '계산 불가'였다. 데이터는 멀쩡히 있었다.
    """
    funds = _funds((2025, 3, None), (2025, 4, None), (2026, 1, None), (2026, 2, None))
    assert ttm_net_income(funds, 2026, 2) is None


# ═══ 최근 4분기 PER ═══
def test_trailing_per_hand_check():
    """손계산: 시총 1.9302조 ÷ 477억 = 40.46배 (고영 실측)."""
    assert trailing_4q_per(1_930_200_000_000, 477 * E8) == pytest.approx(40.46, abs=0.02)


@pytest.mark.parametrize("ttm", [0, -100 * E8])
def test_trailing_per_is_none_when_loss(ttm):
    """이익이 0 이하면 배수가 의미를 잃는다 — 음수 PER을 만들지 않는다."""
    assert trailing_4q_per(1_000_000_000_000, ttm) is None


def test_trailing_per_needs_market_cap():
    assert trailing_4q_per(None, 100 * E8) is None


# ═══ 선행 PER (연간 컨센서스) ═══
def test_forward_per_hand_check_two_quarters_reported():
    """손계산 — 한미반도체 2026.2Q 실측 재현.

    연간 컨센 3,457억 · 이미 발표된 2026.1Q 190.3억 + 2026.2Q(순이익 미수집)
    → 발표분은 1개 분기(190.3억)뿐이므로 남은 분기 3개.
      남은 추정 = 3,457 − 190.3 = 3,266.7억 · 분기당 1,088.9억
      향후 4분기 = 3,266.7 + 1,088.9 × 1 = 4,355.6억
      PER = 20.3492조 ÷ 4,355.6억 = 46.7배
    """
    funds = _funds((2026, 1, 190.3), (2026, 2, None))
    per, basis = forward_per_annual(3457 * E8, 2026, funds, 20_349_200_000_000)
    assert per == pytest.approx(46.7, abs=0.1)
    assert "2026년 컨센" in basis


def test_forward_per_when_year_fully_reported():
    """네 분기가 다 발표됐으면 연간 추정 자체가 '다음 4분기'다."""
    funds = _funds((2026, 1, 100.0), (2026, 2, 100.0), (2026, 3, 100.0), (2026, 4, 100.0))
    per, basis = forward_per_annual(500 * E8, 2026, funds, 1_000_000_000_000)
    assert per == pytest.approx(1_000_000_000_000 / (500 * E8))
    assert basis == "2026년 컨센 기준"


def test_forward_per_is_none_without_consensus():
    """★ 컨센서스가 없으면 **만들어내지 않는다**(ADR 1 — 코스닥 60%가 커버리지 0건)."""
    assert forward_per_annual(None, 2026, _funds((2026, 1, 100.0)), 1e12) == (None, None)


def test_forward_per_is_none_when_estimate_is_loss():
    assert forward_per_annual(-10 * E8, 2026, [], 1e12) == (None, None)


# ═══ 후행 PER을 쓰지 않는다는 규칙 ═══
def test_trailing_annual_per_would_be_badly_wrong_in_acceleration():
    """★★ **이 테스트가 이 모듈의 존재 이유다.**

    `price_snapshots.per`는 직전 사업연도 EPS 기준이라 실적이 급가속하면
    2~3배 과대평가된다. 실측(2026-08-23 · 삼성전자):
        스냅샷 42.89 ≈ 2025 연간 순이익 기준 36.4  ·  실제 TTM 기준 10.9
    이 시스템은 정확히 가속 종목만 고르므로 그 왜곡이 항상 최악으로 걸린다.
    """
    cap = 1_645_727_400_000_000
    ttm = 1_507_173 * E8       # 최근 4분기(2025.3Q~2026.2Q)
    last_year = 452_068 * E8   # 2025 연간

    real = trailing_4q_per(cap, ttm)
    stale = trailing_4q_per(cap, last_year)

    assert real == pytest.approx(10.9, abs=0.1)
    assert stale == pytest.approx(36.4, abs=0.1)
    # 후행 기준이 3배 이상 비싸 보인다 — "이미 비싸다"는 정반대 결론이 나온다.
    assert stale > real * 3
