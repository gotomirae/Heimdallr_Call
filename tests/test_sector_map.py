# PRD Ref: §9 · traps.md T11
"""투자 섹터 분류. 외부 I/O 없이 돈다.

★ 이 분류가 틀려도 **아무것도 실패하지 않는다** — 화면에 잘못된 섹터명이 뜰 뿐이다.
  그래서 실제 DB 값으로 대조한 케이스를 테스트에 박아 둔다.
"""

from __future__ import annotations

import pytest

from src.universe.sector_map import (
    ALL_SECTORS,
    SECTOR_RULES,
    UNKNOWN_SECTOR,
    classify_sector,
)


#: (회사명, 업종, 제품, 기대 섹터) — **전부 실제 DB 값 그대로**(2026-08-17).
REAL_CASES = [
    ("한미반도체", "특수 목적용 기계 제조업",
     "반도체 후공정장비,반도체금형 제조/부동산 매매,임대", "반도체장비"),
    ("두산에너빌리티", "일반 목적용 기계 제조업",
     "기관,터어빈,선박용엔진,주단조품,제강제품 제조/종합건설", "전력인프라"),
    ("셀트리온", "기초 의약물질 제조업", "램시마, 트룩시마, 허쥬마", "바이오·제약"),
    ("SK하이닉스", "반도체 제조업", "반도체,컴퓨터,통신기기 제조,도매", "반도체"),
    ("삼성중공업", "선박 및 보트 건조업",
     "선박(벌크선,원유운반선),철구조물,에너지플랜트 생산,판매/토목건축업", "조선·해운"),
    ("한국전력공사", "전기업", "전력자원개발,발전,송전,전력용기자재확보", "전력인프라"),
    ("한화시스템", "전자부품 제조업",
     "정밀기기(육해공군관련전자제어시스템,열영상감시장비,탐지추적장치,전투지휘체계시스템) 제조",
     "방산·우주"),
    ("이수페타시스", "전자부품 제조업", "P.C.B(인쇄회로기판),M.L.B 제조", "전자부품"),
    ("동성화인텍", "기초 화학물질 제조업", "초저온 보냉재", "조선·해운"),
    ("현대건설", "토목 건설업", "공사수입,주택분양,건설산업부문 설계,감리 등 엔지니어링서비스", "건설"),
    ("SK아이이테크놀로지", "일차전지 및 이차전지 제조업",
     "2차전지용 습식 분리막 및 폴더블 커버 윈도우", "2차전지"),
]


@pytest.mark.parametrize("name,industry,products,expected", REAL_CASES)
def test_real_universe_rows(name, industry, products, expected):
    assert classify_sector(name, industry, products) == expected


def test_products_beat_industry():
    """★ 제품이 업종을 이긴다.

    '특수 목적용 기계 제조업' 93종목 안에 반도체장비·조선기자재가 섞여 있어
    업종만 보면 전부 같은 섹터가 된다.
    """
    machine = "특수 목적용 기계 제조업"
    assert classify_sector("A", machine, "반도체 후공정장비") == "반도체장비"
    assert classify_sector("B", machine, "TFT-LCD검사장비") == "디스플레이"
    assert classify_sector("C", machine, None) == "기계·로봇"


def test_unknown_when_nothing_matches():
    """★ 억지로 끼워 맞추지 않는다. 틀린 섹터는 없는 섹터보다 나쁘다."""
    assert classify_sector("무명", "듣도보도못한 업종", "알 수 없는 무엇") == UNKNOWN_SECTOR
    assert classify_sector(None, None, None) == UNKNOWN_SECTOR


def test_rule_order_puts_narrow_first():
    """좁은 규칙이 넓은 규칙보다 앞에 있어야 한다."""
    order = [name for name, _ in SECTOR_RULES]
    assert order.index("원전") < order.index("전력인프라")
    assert order.index("반도체장비") < order.index("반도체")
    assert order.index("반도체장비") < order.index("기계·로봇")
    assert order.index("전력인프라") < order.index("조선·해운"), (
        "두산에너빌리티의 '터어빈'이 '선박용엔진'보다 먼저 걸려야 한다"
    )


def test_all_sectors_includes_unknown_and_is_unique():
    assert UNKNOWN_SECTOR in ALL_SECTORS
    assert len(ALL_SECTORS) == len(set(ALL_SECTORS)), "섹터명이 중복됐다"


def test_every_result_is_a_declared_sector():
    """분류 결과가 `ALL_SECTORS` 밖으로 새면 화면 필터에서 사라진다."""
    for name, industry, products, _ in REAL_CASES:
        assert classify_sector(name, industry, products) in ALL_SECTORS


def test_keywords_are_lowercase():
    """`_haystack`이 소문자로 비교하므로 대문자 키워드는 **영원히 안 걸린다.**"""
    bad = [(s, k) for s, ks in SECTOR_RULES for k in ks if k != k.lower()]
    assert not bad, f"대문자가 섞인 키워드는 매칭되지 않는다: {bad}"
