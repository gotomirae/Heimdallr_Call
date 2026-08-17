# PRD Ref: §3, 부록 B · traps.md T5, T6
"""P1 유니버스 회귀 테스트.

순수 함수 테스트는 항상 돈다. KIND 실호출 테스트는 `needs_network` 마커를 단다
(collector는 모킹하지 않는다 — CLAUDE.md).
"""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pytest

from src.universe.sector_filter import classify, quarters_since


# ═══════════════════════════════════════════════════════════════════
# T5 회귀 — 파서가 lxml로 바뀌면 코스닥이 30% 사라진다
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.needs_network
def test_kosdaq_listing_has_at_least_1700_rows():
    """실측 2026-08-13: KOSDAQ 원문 <tr> 1,841 · 유효 1,818행.

    lxml로 되돌리면 1,283행으로 떨어지지만 **예외도 경고도 나지 않는다.**
    하한을 1,700으로 두어 그 회귀를 잡는다.
    """
    from src.universe.kind_listing import fetch_kind_listing

    rows, report = fetch_kind_listing()
    kosdaq = [r for r in rows if r.board == "KOSDAQ"]
    assert len(kosdaq) >= 1_700, f"코스닥 {len(kosdaq)}행 — 파서가 lxml로 바뀌지 않았는지 확인"
    # 원문 대조도 함께 강제한다
    assert report.parsed_row_counts["KOSDAQ"] >= report.raw_tr_counts["KOSDAQ"] * 0.99


@pytest.mark.needs_network
def test_listing_codes_are_unique_and_6_chars():
    """T6 — 중복 제거가 실제로 되는지. PK 제약(23505)에 걸리면 저장이 통째로 실패한다."""
    from src.universe.kind_listing import fetch_kind_listing

    rows, _ = fetch_kind_listing()
    codes = [r.code for r in rows]
    assert len(codes) == len(set(codes))
    assert all(len(c) == 6 and c.isalnum() for c in codes)


@pytest.mark.needs_network
def test_alphanumeric_codes_are_kept():
    """T6 갱신 — '0126Z0' 같은 영숫자 코드를 버리면 실체 기업이 사라진다."""
    from src.universe.kind_listing import fetch_kind_listing

    rows, _ = fetch_kind_listing()
    alnum = [r for r in rows if not r.code.isdigit()]
    assert alnum, "영숫자 종목코드가 하나도 없다 — 제외 규칙이 되돌아갔는지 확인"


# ═══════════════════════════════════════════════════════════════════
# corp_code — <list> 블록 경계를 넘는 매칭 금지
# ═══════════════════════════════════════════════════════════════════
def _corpcode_zip(xml: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CORPCODE.xml", xml)
    return buf.getvalue()


def test_corp_code_does_not_cross_record_boundary(tmp_path, monkeypatch):
    """★ 실제로 있었던 버그(2026-08-13).

    stock_code가 비어 있는 레코드에서 정규식이 다음 레코드로 넘어가
    **A사의 corp_code에 B사의 stock_code를 붙였다.** 예외도 경고도 없고
    매칭률만 높게 나온다. 여기서는 비상장 레코드를 사이에 끼워 그 회귀를 잡는다.
    """
    from src.universe import corp_code as mod

    xml = (
        "<result>"
        "<list><corp_code>11111111</corp_code><corp_name>비상장A</corp_name>"
        "<stock_code> </stock_code><modify_date>20260101</modify_date></list>"
        "<list><corp_code>22222222</corp_code><corp_name>상장B</corp_name>"
        "<stock_code>005930</stock_code><modify_date>20260101</modify_date></list>"
        "<list><corp_code>33333333</corp_code><corp_name>비상장C</corp_name>"
        "<stock_code> </stock_code><modify_date>20260101</modify_date></list>"
        "<list><corp_code>44444444</corp_code><corp_name>상장D</corp_name>"
        "<stock_code>0126Z0</stock_code><modify_date>20260101</modify_date></list>"
        "</result>"
    )
    cache = tmp_path / "corpcode.zip"
    cache.write_bytes(_corpcode_zip(xml))
    monkeypatch.setattr(mod, "CACHE_PATH", cache)

    mapping = mod.fetch_corp_code_map()
    assert mapping == {"005930": "22222222", "0126Z0": "44444444"}


# ═══════════════════════════════════════════════════════════════════
# 업종 제외 판정 (부록 B) — 순수 함수
# ═══════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "industry,reason",
    [
        ("은행 및 저축기관", "bank"),
        ("보험업", "insurance"),
        ("재 보험업", "insurance"),
        ("금융 지원 서비스업", "securities"),
        ("기타 금융업", "holding_or_other_finance"),
        ("신탁업 및 집합투자업", "reit_fund"),
        ("부동산 임대 및 공급업", "real_estate"),
    ],
)
def test_excluded_industries(industry, reason):
    v = classify(industry=industry)
    assert v.is_excluded is True
    assert v.exclude_reason == reason


def test_normal_industry_is_not_excluded():
    v = classify(industry="반도체 제조업", products="메모리 반도체")
    assert v.is_excluded is False
    assert v.exclude_reason is None
    assert v.sector_caveat is False


def test_exclusion_priority_is_stable():
    """사유가 흔들리면 분포를 세도 의미가 없다. 스팩이 항상 먼저다."""
    v = classify(industry="은행 및 저축기관", is_spac=True, is_admin_issue=True)
    assert v.exclude_reason == "spac"
    v = classify(industry="은행 및 저축기관", is_admin_issue=True)
    assert v.exclude_reason == "admin_issue"


def test_caveat_industries():
    assert classify(industry="종합 건설업").caveat_reason == "construction"
    assert classify(industry="선박 및 보트 건조업").caveat_reason == "shipbuilding"
    assert classify(industry="의약품 제조업").caveat_reason == "bio_pharma"
    # 게임은 업종이 '소프트웨어 개발 및 공급업'이라 주요제품으로 잡는다
    v = classify(industry="소프트웨어 개발 및 공급업", products="모바일 게임 개발")
    assert v.caveat_reason == "game"
    assert v.is_excluded is False  # 주의일 뿐 제외가 아니다


def test_caveat_recorded_even_when_excluded():
    v = classify(industry="의약품 제조업", is_admin_issue=True)
    assert v.is_excluded is True and v.sector_caveat is True


def test_young_listing_needs_known_listing_date():
    """상장일을 모르면 '히스토리 부족' 판정을 하지 않는다 — None과 False를 구분한다."""
    assert classify(industry="반도체 제조업", quarters_since_listing=None).is_excluded is False
    assert classify(industry="반도체 제조업", quarters_since_listing=2).exclude_reason == "young_listing"
    assert classify(industry="반도체 제조업", quarters_since_listing=5).is_excluded is False


def test_quarters_since():
    assert quarters_since(None, date(2026, 8, 13)) is None
    assert quarters_since(date(2026, 8, 13), date(2026, 8, 13)) == 0
    assert quarters_since(date(2025, 8, 13), date(2026, 8, 13)) == 4
    assert quarters_since(date(2020, 1, 1), date(2026, 8, 13)) == 26
