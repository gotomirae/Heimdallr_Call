# PRD Ref: §5.1(L2), §5.3 · traps.md T2, T3, T24
"""DART 수집기의 순수 로직 테스트 (외부 I/O 없음)."""

from __future__ import annotations

from src.collectors.dart_financials import (
    _to_int,
    choose_fs_div,
    detect_restatement,
    extract_figures,
)


def _row(**kw) -> dict:
    base = {
        "sj_div": "IS",
        "fs_div": "CFS",
        "account_nm": "매출액",
        "thstrm_amount": "100",
        "thstrm_add_amount": "100",
    }
    base.update(kw)
    return base


# ═══ 숫자 파싱 — 결측과 0을 구분한다 ═══
def test_to_int_parses_comma_separated():
    assert _to_int("112,522,064,123") == 112_522_064_123


def test_to_int_treats_blank_and_dash_as_missing():
    assert _to_int(None) is None
    assert _to_int("") is None
    assert _to_int(" ") is None
    assert _to_int("-") is None


def test_to_int_keeps_zero_and_negative():
    """0은 결측이 아니다. 음수(적자)도 그대로 통과해야 한다."""
    assert _to_int("0") == 0
    assert _to_int("-1,234") == -1234


# ═══ T2 — fs_div는 CFS 우선, 종목별 고정 ═══
def test_choose_fs_div_prefers_cfs():
    rows = [_row(fs_div="OFS"), _row(fs_div="CFS")]
    assert choose_fs_div(rows) == "CFS"


def test_choose_fs_div_falls_back_to_ofs():
    assert choose_fs_div([_row(fs_div="OFS")]) == "OFS"


def test_choose_fs_div_returns_none_when_empty():
    assert choose_fs_div([]) is None


# ═══ 계정 추출 ═══
def test_extract_figures_reads_selected_fs_div_only():
    rows = [
        _row(fs_div="CFS", account_nm="매출액", thstrm_amount="10", thstrm_add_amount="10"),
        _row(fs_div="OFS", account_nm="매출액", thstrm_amount="99", thstrm_add_amount="99"),
    ]
    figures = extract_figures(rows, "CFS")
    assert figures["revenue"].amount == 10


def test_extract_figures_accepts_account_aliases():
    rows = [_row(account_nm="수익(매출액)", thstrm_amount="7", thstrm_add_amount="7")]
    assert extract_figures(rows, "CFS")["revenue"].amount == 7


def test_extract_figures_falls_back_to_cis():
    """손익계산서를 CIS(포괄손익)로만 내는 회사가 있다."""
    rows = [_row(sj_div="CIS", account_nm="영업이익", thstrm_amount="5", thstrm_add_amount="5")]
    assert extract_figures(rows, "CFS")["op"].amount == 5


def test_extract_figures_skips_balance_sheet_rows():
    rows = [_row(sj_div="BS", account_nm="매출액", thstrm_amount="123")]
    assert "revenue" not in extract_figures(rows, "CFS")


# ═══ T3 — 재작성 감지 ═══
def test_restatement_detected_when_prior_year_changed():
    assert detect_restatement(1_100, 1_000) is True


def test_no_restatement_within_tolerance():
    """반올림 수준의 차이는 재작성이 아니다."""
    assert detect_restatement(1_000, 1_000) is False
    assert detect_restatement(1_000_500, 1_000_000) is False  # 0.05%


def test_restatement_not_judged_when_either_side_missing():
    assert detect_restatement(None, 1_000) is False
    assert detect_restatement(1_000, None) is False


def test_restatement_from_zero_base():
    assert detect_restatement(10, 0) is True
    assert detect_restatement(0, 0) is False


# ═══ T39 — 주요계정 API가 매출을 통째로 안 주는 회사 ═══
def test_extract_figures_reads_operating_revenue_alias():
    """서비스·바이오 기업은 '영업수익'으로 낸다.

    실측: 한국경제TV·슈어소프트테크 등 27종목이 이 표기였다.
    """
    rows = [_row(account_nm="영업수익", sj_div="CIS", thstrm_amount="759")]
    assert extract_figures(rows, "CFS")["revenue"].amount == 759


def test_missing_revenue_is_detectable_when_op_present():
    """★ 매출만 없고 영업이익은 있는 상태가 폴백 트리거 조건이다.

    주요계정 API는 자산·부채·영업이익·순이익만 주고 매출 줄을 통째로 빠뜨릴 수 있다.
    에러가 아니라 그냥 없다 — 수집이 성공한 것처럼 보이고 매출만 None이 되어
    게이트가 조용히 판정 불가로 빠진다(실측 29종목 166행).
    """
    rows = [
        _row(account_nm="영업이익", thstrm_amount="12"),
        _row(account_nm="당기순이익", thstrm_amount="9"),
    ]
    figures = extract_figures(rows, "CFS")
    assert "revenue" not in figures
    assert "op" in figures  # 이 조합이 '이 API가 안 준다'는 신호다


def test_single_all_rows_need_fs_div_injected():
    """★ 단일회사 전체 재무제표 응답에는 `fs_div` 필드가 없다.

    요청 파라미터로 이미 정해졌기 때문이다. 그대로 넘기면 fs_div 필터가
    전 행을 걸러내 빈손이 된다 — "폴백했는데 못 찾았다"로 보이고 에러는 없다.
    실측: 이 처리를 빼먹었을 때 2종목 20행이 전부 매출 None으로 남았다.
    """
    row_without_fs_div = {
        "sj_div": "CIS", "account_nm": "영업수익",
        "thstrm_amount": "75910005501", "thstrm_add_amount": "",
    }
    assert extract_figures([row_without_fs_div], "CFS") == {}

    row_without_fs_div.setdefault("fs_div", "CFS")
    assert extract_figures([row_without_fs_div], "CFS")["revenue"].amount == 75910005501
