# PRD Ref: §5.1(L1, L2') · traps.md T11, T27, T28
"""P4 공시 감지·잠정실적 파서 테스트. 전부 외부 I/O 없이 돈다."""

from __future__ import annotations

import pytest

from src.collectors.dart_disclosure import (
    DOC_PERIODIC,
    DOC_PL_CHANGE,
    DOC_PROVISIONAL,
    classify,
    is_correction,
)
from src.collectors.provisional_parser import (
    check_period_plausible,
    parse_provisional,
    parse_unit,
)


# ═══════════════════════════════════════════════════════════════════
# 분류 — 오탐이 이 단계의 전부다
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "name,expected",
    [
        ("연결재무제표기준영업(잠정)실적(공정공시)", DOC_PROVISIONAL),
        ("영업(잠정)실적(공정공시)", DOC_PROVISIONAL),
        ("[기재정정]연결재무제표기준영업(잠정)실적(공정공시)", DOC_PROVISIONAL),
        ("매출액또는손익구조30%(대규모법인은15%)이상변경", DOC_PL_CHANGE),
        ("반기보고서 (2026.06)", DOC_PERIODIC),
        ("분기보고서 (2026.03)", DOC_PERIODIC),
        ("[기재정정]사업보고서 (2025.12)", DOC_PERIODIC),
    ],
)
def test_classify_matches(name, expected):
    assert classify(name)[0] == expected


@pytest.mark.parametrize(
    "name",
    [
        "증권발행실적보고서",  # 실측 436건 — '실적'으로 매칭하면 통째로 딸려 온다
        "소액공모실적보고서",
        "결산실적공시예고(안내공시)",  # 실적 발표 '예고'지 실적이 아니다
        "기업설명회(IR)개최",
        "현금ㆍ현물배당결정",
    ],
)
def test_classify_rejects_false_positives(name):
    assert classify(name)[0] is None


def test_subsidiary_results_are_dropped():
    """자회사 실적을 모회사 실적으로 둔갑시키면 안 된다 (실측 24건)."""
    doc_type, reason = classify(
        "연결재무제표기준영업(잠정)실적(공정공시)(자회사의 주요경영사항)"
    )
    assert doc_type is None
    assert reason == "subsidiary"


def test_forecast_is_dropped():
    """'전망'은 확정치가 아니다."""
    doc_type, reason = classify("연결재무제표기준영업실적등에대한전망(공정공시)")
    assert doc_type is None
    assert reason == "forecast"


def test_is_correction():
    assert is_correction("[기재정정]반기보고서 (2026.06)") is True
    assert is_correction("[첨부정정]사업보고서 (2025.12)") is True
    assert is_correction("반기보고서 (2026.06)") is False


# ═══════════════════════════════════════════════════════════════════
# 단위 (T11)
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "text,unit,mult",
    [
        ("구분(단위 : 백만원, %)", "백만원", 1_000_000),
        ("구분(단위 : 억원, %)", "억원", 100_000_000),
        ("구분(단위 : 원, %)", "원", 1),
        ("구분(단위 : 천원, %)", "천원", 1_000),
    ],
)
def test_parse_unit(text, unit, mult):
    assert parse_unit(text) == (unit, mult)


def test_unknown_unit_is_not_guessed():
    """모르는 표기는 배수를 추측하지 않는다 (T11)."""
    unit, mult = parse_unit("구분(단위 : 만원, %)")
    assert unit == "만원"
    assert mult is None


def test_no_unit_at_all():
    assert parse_unit("구분") == (None, None)


# ═══════════════════════════════════════════════════════════════════
# 실적기간 (T28)
# ═══════════════════════════════════════════════════════════════════
def _html(period_rows: str, unit: str = "백만원", body: str | None = None) -> str:
    default_body = """
      <tr><td>매출액</td><td>당해실적</td><td>86,805</td><td>78,348</td></tr>
      <tr><td>영업이익</td><td>당해실적</td><td>11,617</td><td>5,795</td></tr>
      <tr><td>당기순이익</td><td>당해실적</td><td>9,000</td><td>4,000</td></tr>
    """
    return f"""<html><body>
      <table><tr><td>실적기간</td></tr>{period_rows}</table>
      <table>
        <tr><td>1. 연결실적내용</td></tr>
        <tr><td>구분(단위 : {unit}, %)</td><td>당기실적</td><td>전기실적</td></tr>
        {body or default_body}
      </table>
    </body></html>"""


QUARTERLY_ROWS = """
  <tr><td>당기실적</td><td>2026-04-01</td><td>~</td><td>2026-06-30</td></tr>
  <tr><td>전기실적</td><td>2026-01-01</td><td>~</td><td>2026-03-31</td></tr>
  <tr><td>전년동기실적</td><td>2025-04-01</td><td>~</td><td>2025-06-30</td></tr>
  <tr><td>당기누계실적</td><td>2026-01-01</td><td>~</td><td>2026-06-30</td></tr>
  <tr><td>전년동기누적실적</td><td>2025-01-01</td><td>~</td><td>2025-06-30</td></tr>
"""

MONTHLY_ROWS = """
  <tr><td>당기실적</td><td>2026-07-01</td><td>~</td><td>2026-07-31</td></tr>
  <tr><td>전기실적</td><td>2026-06-01</td><td>~</td><td>2026-06-30</td></tr>
  <tr><td>전년동기실적</td><td>2025-07-01</td><td>~</td><td>2025-07-31</td></tr>
  <tr><td>당기누계실적</td><td>2026-01-01</td><td>~</td><td>2026-07-31</td></tr>
  <tr><td>전년동기누적실적</td><td>2025-01-01</td><td>~</td><td>2025-07-31</td></tr>
"""


def test_quarter_comes_from_current_period_row_not_last_date():
    """★ 실제로 있었던 버그.

    표 전체에서 날짜를 긁어 마지막을 쓰면 '전년동기누적실적'의 종료일을 집어
    **연도가 1년 어긋난다**. 숫자는 멀쩡해 파싱은 '성공'으로 보고된다.
    """
    r = parse_provisional(_html(QUARTERLY_ROWS), "X", disclosed_at="20260813")
    assert (r.fiscal_year, r.fiscal_quarter) == (2026, 2)  # 2025.2Q가 아니다
    assert r.period_days == 91
    assert r.ok is True
    assert r.period_warning is None


def test_monthly_disclosure_is_rejected():
    """★ 같은 공시명으로 월별 실적을 내는 회사가 있다 (T28, 실측 이마트).

    분기 칸에 넣으면 매출이 1/3로 들어가 '가짜 급감'이 된다.
    """
    r = parse_provisional(_html(MONTHLY_ROWS), "X", disclosed_at="20260813")
    assert r.period_days == 31
    assert r.ok is False
    assert r.period_warning.startswith("not_quarterly")


def test_values_are_scaled_by_unit():
    r = parse_provisional(_html(QUARTERLY_ROWS, unit="백만원"), "X")
    assert r.revenue == 86_805 * 1_000_000
    assert r.op == 11_617 * 1_000_000
    assert r.np == 9_000 * 1_000_000


def test_unknown_unit_skips_every_item():
    """단위를 못 읽으면 추측해서 곱하지 않고 전부 건너뛴다 (T11)."""
    r = parse_provisional(_html(QUARTERLY_ROWS, unit="만원"), "X")
    assert r.ok is False
    assert r.failure == "unknown_unit"
    assert set(r.skipped) == {"revenue", "op", "np"}
    assert r.revenue is None and r.op is None and r.np is None


def test_consolidated_flag():
    r = parse_provisional(_html(QUARTERLY_ROWS), "X")
    assert r.fs_div == "CFS"


def test_negative_values_parse():
    body = """
      <tr><td>매출액</td><td>당해실적</td><td>6,915,000</td></tr>
      <tr><td>영업이익</td><td>당해실적</td><td>-43,000</td></tr>
    """
    r = parse_provisional(_html(QUARTERLY_ROWS, body=body), "X")
    assert r.op == -43_000 * 1_000_000


def test_no_account_matched():
    body = "<tr><td>기타항목</td><td>당해실적</td><td>100</td></tr>"
    r = parse_provisional(_html(QUARTERLY_ROWS, body=body), "X")
    assert r.ok is False
    assert r.failure == "no_account_matched"


# ═══════════════════════════════════════════════════════════════════
# 공시일 대조
# ═══════════════════════════════════════════════════════════════════
def test_period_plausible_normal():
    assert check_period_plausible(2026, 2, "20260813") is None  # 6월말 → 8월 공시


def test_period_plausible_flags_stale():
    """1년 어긋난 경우를 잡는다."""
    assert check_period_plausible(2025, 2, "20260813").startswith("stale_period")


def test_period_plausible_flags_future():
    assert check_period_plausible(2026, 4, "20260813").startswith("future_period")


def test_period_plausible_skips_when_unknown():
    assert check_period_plausible(None, None, "20260813") is None
    assert check_period_plausible(2026, 2, None) is None
