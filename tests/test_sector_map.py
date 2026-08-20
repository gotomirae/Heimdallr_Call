# PRD Ref: §9 · traps.md T11
"""투자 섹터 분류. 외부 I/O 없이 돈다.

★ 이 분류가 틀려도 **아무것도 실패하지 않는다** — 화면에 잘못된 섹터명이 뜰 뿐이다.
  그래서 실제 DB 값으로 대조한 케이스를 테스트에 박아 둔다.
"""

from __future__ import annotations

import pytest

from src.universe.sector_map import (
    ALL_SECTORS,
    INDUSTRY_ONLY_KEYWORDS,
    SECTOR_EXCLUDES,
    SECTOR_RULES,
    UNKNOWN_SECTOR,
    classify_sector,
)
from tests.sector_labels import LABELED_CASES


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


# ═══════════════════════════════════════════════════════════════════
# 오분류율 — ★ 이 프로젝트에서 섹터에 관해 **유일하게 의미 있는 숫자**
#
# 미분류율(`기타` 비율)은 "못 가린 비율"이지 "틀리게 가린 비율"이 아니다.
# 오분류는 에러를 내지 않아서, 재지 않으면 화면에만 조용히 남는다.
# ═══════════════════════════════════════════════════════════════════
#: 2026-08-20 실측. 규칙 개정 전 70.5%(23/78 오분류) → 개정 후 97.4%(2/78).
#: **내리면 안 된다.** 올릴 수는 있다.
MIN_LABEL_ACCURACY = 0.96

#: 위 정답지 주석에 근거를 적어 둔 **알려진 한계**. 여기 없는 종목이 틀리면 회귀다.
KNOWN_MISSES = {"포스코퓨처엠", "천보"}


def test_labeled_accuracy_does_not_regress():
    wrong = [
        (name, expected, classify_sector(name, industry, products))
        for name, industry, products, expected in LABELED_CASES
        if classify_sector(name, industry, products) != expected
    ]
    accuracy = 1 - len(wrong) / len(LABELED_CASES)
    assert accuracy >= MIN_LABEL_ACCURACY, (
        f"섹터 정확도 {accuracy:.1%} < 기준 {MIN_LABEL_ACCURACY:.0%}\n"
        + "\n".join(f"  {n}: 정답 {e} → 실제 {g}" for n, e, g in wrong)
    )


def test_no_new_misclassification():
    """★ 알려진 한계 **밖에서** 틀리면 회귀다 — 총점만 보면 맞바꿈을 못 본다.

    정확도만 감시하면 '하나 고치고 하나 망가뜨리는' 변경이 통과한다(T54와 같은 결).
    """
    wrong = {
        name
        for name, industry, products, expected in LABELED_CASES
        if classify_sector(name, industry, products) != expected
    }
    assert not (wrong - KNOWN_MISSES), (
        f"새로 틀린 종목: {sorted(wrong - KNOWN_MISSES)}"
    )


def test_position_beats_rule_order():
    """★ 뒤에 곁다리로 붙은 한 단어가 본업을 덮어쓰면 안 된다 (2026-08-20 개정 ①)."""
    # 기아 — '군수차량'이 방산·우주로 끌고 갔다.
    assert classify_sector(None, None, "승용차,중대형버스,트럭,군수차량 제조") == "자동차"
    # 이구산업 — 끝에 붙은 '/부동산 임대'가 본업(동판)을 이겼다.
    assert classify_sector(None, None, "동판.조,황동판.조 제조,임가공/부동산 임대") == "철강·금속"


def test_rule_order_still_breaks_ties():
    """위치가 같으면 규칙 순서가 정한다 — 둘 다 0번째에서 걸리는 경우."""
    assert classify_sector(None, None, "반도체 후공정장비") == "반도체장비"


def test_excludes_kill_substring_collisions():
    """★ 짧은 키워드가 긴 단어 안에 숨는 것을 막는다 (2026-08-20 개정 ②).

    전부 실측으로 잡은 것들이다 — **에러 없이** 엉뚱한 섹터가 나왔다.
    """
    assert classify_sector(None, None, "바이러스백신 프로그램") == "소프트웨어·IT"
    assert classify_sector(None, None, "연료전지") == "신재생에너지"
    assert classify_sector(None, None, "고압 수소 어닐링 장비") == "반도체장비"
    # '스테인리스'의 '리스'가 금융으로 갔다.
    assert classify_sector(None, None, "열연코일,냉연강판,스테인리스 제조") == "철강·금속"


def test_company_name_is_not_matched():
    """★ 이름은 사업의 증거가 아니다 (2026-08-20 개정 ③).

    '주성엔지니어링'의 '엔지니어링'이 건설로 끌고 갔다.
    """
    assert classify_sector("주성엔지니어링", "듣도보도못한 업종", None) == UNKNOWN_SECTOR
    assert classify_sector("아무건설", None, None) == UNKNOWN_SECTOR


def test_industry_only_keywords_ignored_in_products():
    """★ 제품 칸에 업종명을 복사해 넣은 공시가 흔하다 — 그게 본업을 덮으면 안 된다."""
    samsung = "통신 및 방송 장비 제조(무선) 제품, 반도체 제조(메모리) 제품"
    assert classify_sector(None, "통신 및 방송 장비 제조업", samsung) == "반도체"
    # 업종 칸에서는 여전히 근거가 된다.
    assert classify_sector(None, "통신 및 방송 장비 제조업", None) == "통신·네트워크"


def test_excludes_and_industry_only_reference_real_things():
    """★ 오타가 나면 **조용히 아무것도 안 한다** — 검사기부터 검사한다(T54)."""
    declared = {name for name, _ in SECTOR_RULES}
    unknown = set(SECTOR_EXCLUDES) - declared
    assert not unknown, f"실제 섹터에 없는 제외어 키(오타 의심): {sorted(unknown)}"

    every_keyword = {k for _, ks in SECTOR_RULES for k in ks}
    orphan = INDUSTRY_ONLY_KEYWORDS - every_keyword
    assert not orphan, (
        f"어느 규칙에도 없는 업종전용 키워드(오타 의심): {sorted(orphan)}"
    )

    bad_case = [k for k in INDUSTRY_ONLY_KEYWORDS if k != k.lower()] + [
        k for ks in SECTOR_EXCLUDES.values() for k in ks if k != k.lower()
    ]
    assert not bad_case, f"대문자가 섞이면 매칭되지 않는다: {bad_case}"


# ═══════════════════════════════════════════════════════════════════
# 섹터 플레이북 — 대시보드의 섹터별 이벤트·지표
#
# ★ 섹터명이 **글자까지 같아야** 한다. 다르면 매칭이 안 돼 화면에 기본값만 나오는데
#   **에러가 없다** — 오타 하나로 그 섹터의 이벤트·지표가 조용히 사라진다.
# ═══════════════════════════════════════════════════════════════════
def _playbook_keys() -> set[str]:
    import re
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1] / "dashboard" / "lib" / "sectorPlaybook.ts"
    ).read_text(encoding="utf-8")
    body = src[src.index("SECTOR_PLAYBOOK") : src.index("DEFAULT_PLAY")]
    return {
        k.strip('"')
        for k in re.findall(r"^  ([가-힣A-Za-z0-9·]+|\"[^\"]+\"):\s*\{", body, re.M)
    }


def test_playbook_has_no_typo_keys():
    """★ 플레이북에만 있는 섹터명 = 오타다. 그 항목은 영영 안 쓰인다."""
    real = {name for name, _ in SECTOR_RULES} | {UNKNOWN_SECTOR}
    extra = _playbook_keys() - real
    assert not extra, f"실제 섹터에 없는 플레이북 키(오타 의심): {sorted(extra)}"


def test_playbook_covers_every_sector():
    """모든 실제 섹터에 이벤트·지표가 있어야 한다 — 없으면 기본값으로 떨어진다."""
    real = {name for name, _ in SECTOR_RULES}
    missing = real - _playbook_keys()
    assert not missing, f"플레이북에 없는 섹터: {sorted(missing)}"
