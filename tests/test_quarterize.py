# PRD Ref: §5.3, §12 T1 · traps.md T1
"""★ 이 프로젝트에서 가장 중요한 테스트.

누적치 분해를 틀리면 Q2/Q4의 YoY가 통째로 왜곡되는데 **에러는 나지 않는다.**
테스트를 먼저 쓰고 구현을 맞춘다.

손계산 대조는 전부 DART 원문 실측값이다(2026-08-13 조회).
"""

from __future__ import annotations

import pytest

from src.finance.quarterize import (
    REPRT_1Q,
    REPRT_3Q,
    REPRT_FY,
    REPRT_H1,
    ReportFigure,
    quarterize,
)


# ═══════════════════════════════════════════════════════════════════
# 실측 손계산 — 리노공업(058470) 2025년, OFS, 매출액 (원)
#   1Q 보고서 : thstrm=78,410,243,553   add=78,410,243,553
#   반기보고서 : thstrm=112,522,064,123  add=190,932,307,676
#   3Q 보고서 : thstrm=96,841,827,642   add=287,774,135,318
#   사업보고서 : (2025년은 아직 없음 — 아래 FY 케이스는 2024년 값을 쓴다)
#
#   Q1 = 78,410,243,553
#   Q2 = 190,932,307,676 − 78,410,243,553 = 112,522,064,123
#   Q3 = 287,774,135,318 − 190,932,307,676 =  96,841,827,642
# ═══════════════════════════════════════════════════════════════════
RINO_2025 = {
    REPRT_1Q: ReportFigure(amount=78_410_243_553, add_amount=78_410_243_553),
    REPRT_H1: ReportFigure(amount=112_522_064_123, add_amount=190_932_307_676),
    REPRT_3Q: ReportFigure(amount=96_841_827_642, add_amount=287_774_135_318),
}


def test_1q_is_taken_directly():
    q = quarterize({REPRT_1Q: RINO_2025[REPRT_1Q]})
    assert q[1].value == 78_410_243_553
    assert q[2].value is None and q[3].value is None and q[4].value is None


def test_h1_report_yields_q2_by_cumulative_difference():
    """★ 급소. Q2 = 반기누적 − 1Q누적."""
    q = quarterize({k: RINO_2025[k] for k in (REPRT_1Q, REPRT_H1)})
    assert q[1].value == 78_410_243_553
    assert q[2].value == 112_522_064_123  # 190,932,307,676 − 78,410,243,553
    assert q[2].source == "cumulative_diff"


def test_3q_report_yields_q3():
    q = quarterize(RINO_2025)
    assert q[3].value == 96_841_827_642  # 287,774,135,318 − 190,932,307,676


def test_annual_report_yields_q4_by_subtracting_3q_cumulative():
    """★ 급소. Q4 = 연간 − 3Q누적. 사업보고서는 add_amount가 없다(실측)."""
    figures = dict(RINO_2025)
    # 가상의 연간값: 3Q누적 + 100,000,000,000
    figures[REPRT_FY] = ReportFigure(amount=387_774_135_318, add_amount=None)
    q = quarterize(figures)
    assert q[4].value == 100_000_000_000
    assert q[4].source == "annual_minus_3q"


def test_all_four_quarters_sum_to_annual():
    """분해가 맞다면 4개 분기 합 == 연간이어야 한다."""
    figures = dict(RINO_2025)
    figures[REPRT_FY] = ReportFigure(amount=387_774_135_318, add_amount=None)
    q = quarterize(figures)
    assert sum(q[i].value for i in (1, 2, 3, 4)) == 387_774_135_318


# ═══════════════════════════════════════════════════════════════════
# 결측 — 0으로 채우지 않는다. None과 0을 반드시 구분한다.
# ═══════════════════════════════════════════════════════════════════
def test_q2_is_none_when_q1_missing():
    """★ Q1이 없으면 Q2를 계산할 수 없다. 0으로 채우면 매출이 2배로 부풀려진다."""
    q = quarterize({REPRT_H1: RINO_2025[REPRT_H1]})
    assert q[2].value is None
    assert q[2].reason == "missing_prior_cumulative"
    assert q[1].value is None


def test_q4_is_none_when_3q_missing():
    figures = {
        REPRT_1Q: RINO_2025[REPRT_1Q],
        REPRT_H1: RINO_2025[REPRT_H1],
        REPRT_FY: ReportFigure(amount=387_774_135_318),
    }
    q = quarterize(figures)
    assert q[4].value is None
    assert q[4].reason == "missing_prior_cumulative"


def test_empty_input_yields_all_none():
    q = quarterize({})
    assert all(q[i].value is None for i in (1, 2, 3, 4))
    assert all(q[i].reason == "missing_report" for i in (1, 2, 3, 4))


def test_interim_report_without_cumulative_is_undecidable():
    """반기보고서에 누적이 없으면 amount가 3개월인지 6개월인지 알 수 없다.

    추측해서 쓰지 말고 판정 불가로 둔다 — 틀리면 Q2가 2배로 잡힌다.
    """
    q = quarterize(
        {
            REPRT_1Q: RINO_2025[REPRT_1Q],
            REPRT_H1: ReportFigure(amount=112_522_064_123, add_amount=None),
        }
    )
    assert q[2].value is None
    assert q[2].reason == "no_cumulative_in_interim_report"


def test_zero_is_not_missing():
    """0원과 결측을 구분한다. 0을 결측으로 처리하면 적자 기업이 사라진다."""
    q = quarterize(
        {
            REPRT_1Q: ReportFigure(amount=0, add_amount=0),
            REPRT_H1: ReportFigure(amount=0, add_amount=0),
        }
    )
    assert q[1].value == 0
    assert q[2].value == 0
    assert q[2].reason is None


def test_negative_values_pass_through():
    """적자(음수 영업이익)도 그대로 통과해야 한다."""
    q = quarterize(
        {
            REPRT_1Q: ReportFigure(amount=-5_000, add_amount=-5_000),
            REPRT_H1: ReportFigure(amount=-3_000, add_amount=-8_000),
        }
    )
    assert q[1].value == -5_000
    assert q[2].value == -3_000


# ═══════════════════════════════════════════════════════════════════
# 교차검증 — thstrm_amount(단독)와 누적 차분이 어긋나면 조용히 넘어가지 않는다
# ═══════════════════════════════════════════════════════════════════
def test_standalone_mismatch_is_recorded():
    q = quarterize(
        {
            REPRT_1Q: ReportFigure(amount=100, add_amount=100),
            # 누적 차분은 150인데 회사가 신고한 단독값은 140
            REPRT_H1: ReportFigure(amount=140, add_amount=250),
        }
    )
    assert q[2].value == 150  # 누적 차분을 신뢰한다
    # 부호 있는 차이(신고 − 차분)를 남긴다. 어느 쪽이 큰지가 진단에 필요하다.
    assert q[2].standalone_mismatch == -10


def test_no_mismatch_when_consistent():
    q = quarterize(RINO_2025)
    for i in (1, 2, 3):
        assert q[i].standalone_mismatch in (None, 0), f"Q{i}"


# ═══════════════════════════════════════════════════════════════════
# 실측 대조 — 삼성전자(00126380) 2025 매출액 CFS (원, 2026-08-13 DART 조회)
#   1Q  thstrm= 79,140,503,000,000  add= 79,140,503,000,000
#   반기 thstrm= 74,566,317,000,000  add=153,706,820,000,000
#   3Q  thstrm= 86,061,747,000,000  add=239,768,567,000,000
#
#   손계산:
#     Q2 = 153,706,820,000,000 − 79,140,503,000,000 = 74,566,317,000,000
#     Q3 = 239,768,567,000,000 − 153,706,820,000,000 = 86,061,747,000,000
#   → 둘 다 회사가 신고한 thstrm_amount와 **정확히** 일치한다(차이 0).
#     이 일치가 누적 차분 방식이 옳다는 실측 근거다.
# ═══════════════════════════════════════════════════════════════════
def test_samsung_2025_revenue_hand_check():
    q = quarterize(
        {
            REPRT_1Q: ReportFigure(
                amount=79_140_503_000_000, add_amount=79_140_503_000_000
            ),
            REPRT_H1: ReportFigure(
                amount=74_566_317_000_000, add_amount=153_706_820_000_000
            ),
            REPRT_3Q: ReportFigure(
                amount=86_061_747_000_000, add_amount=239_768_567_000_000
            ),
        }
    )
    assert q[2].value == 74_566_317_000_000
    assert q[3].value == 86_061_747_000_000
    # 신고 단독값과 차분이 일치 → 불일치 0
    assert q[2].standalone_mismatch == 0
    assert q[3].standalone_mismatch == 0


@pytest.mark.parametrize("quarter", [1, 2, 3, 4])
def test_result_always_has_all_four_quarters(quarter):
    q = quarterize({})
    assert quarter in q


# ═══ T39 — 단일회사 전체 재무제표(폴백) 응답 형태 ═══
def test_single_all_shape_decomposes_correctly():
    """★ 폴백 API 응답을 그대로 분해했을 때 DART 원문과 맞아야 한다.

    실측: 한국경제TV(039340) 2025년 '영업수익' (원)
      1분기 11013 : 당기 17,488,073,800 · 누적 17,488,073,800
      반기   11012 : 당기 19,800,525,411 · 누적 37,288,599,211
      3분기 11014 : 당기 18,393,672,433 · 누적 55,682,271,644
      사업   11011 : 당기 75,910,005,501 · 누적 **빈값**  ← 여기가 급소다

    손계산:
      Q1 = 17,488,073,800
      Q2 = 37,288,599,211 − 17,488,073,800 = 19,800,525,411
      Q3 = 55,682,271,644 − 37,288,599,211 = 18,393,672,433
      Q4 = 75,910,005,501 − 55,682,271,644 = 20,227,733,857
      합 = 75,910,005,501  (연간과 정확히 일치)
    """
    q = quarterize({
        REPRT_1Q: ReportFigure(amount=17_488_073_800, add_amount=17_488_073_800),
        REPRT_H1: ReportFigure(amount=19_800_525_411, add_amount=37_288_599_211),
        REPRT_3Q: ReportFigure(amount=18_393_672_433, add_amount=55_682_271_644),
        # 사업보고서는 add_amount가 비어 온다 — amount가 연간 누적이다.
        REPRT_FY: ReportFigure(amount=75_910_005_501, add_amount=None),
    })
    assert q[1].value == 17_488_073_800
    assert q[2].value == 19_800_525_411
    assert q[3].value == 18_393_672_433
    assert q[4].value == 20_227_733_857
    assert sum(q[i].value for i in (1, 2, 3, 4)) == 75_910_005_501
