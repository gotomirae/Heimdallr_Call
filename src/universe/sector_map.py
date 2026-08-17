# PRD Ref: §9 (발굴 목록 섹터 열) · traps.md T11
"""투자자가 쓰는 섹터명으로 분류 — **순수 함수. 외부 I/O 금지.**

왜 필요한가:
  KRX/통계청 업종명은 **투자 판단에 쓰는 말이 아니다.**
  한미반도체·HPSP가 '특수 목적용 기계 제조업'(93종목)에 들어가 있고,
  두산에너빌리티는 '일반 목적용 기계 제조업'이다. 이 이름으로는
  "지금 반도체가 좋다 / 원전이 좋다"를 볼 수 없다.

분류 원칙:
  1. **제품(`products`)을 먼저 본다.** 업종보다 훨씬 구체적이다
     ('특수 목적용 기계' 안에 반도체장비·디스플레이장비·조선기자재가 다 있다).
  2. 제품으로 못 가리면 업종으로 떨어진다.
  3. **둘 다 못 가리면 `기타`다.** 억지로 끼워 맞추지 않는다 —
     틀린 섹터는 없는 섹터보다 나쁘다(화면에서 잘못된 묶음으로 읽힌다).

★ 규칙 순서가 곧 우선순위다. 위에 있을수록 좁고 확실한 규칙이다.
  '반도체 장비'는 '기계'보다, '원전'은 '전력인프라'보다 먼저 걸려야 한다.
"""

from __future__ import annotations

import re

#: (섹터명, 제품/업종에서 찾을 키워드들). **순서가 우선순위다.**
#: 키워드는 소문자로 비교한다(영문 혼용 대비).
SECTOR_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    # ── 좁고 확실한 것부터 ──────────────────────────────────────
    ("원전", ("원전", "원자력", "원자로", "smr", "핵연료", "방사성")),
    ("방산·우주", ("방산", "방위산업", "군수", "유도무기", "우주선", "위성", "항공기",
                  "탄약", "함정", "전투", "육해공군", "레이더", "열영상", "탐지추적",
                  "감시장비", "국방")),
    ("2차전지", ("2차전지", "이차전지", "리튬", "양극재", "음극재", "분리막", "전해질",
                 "전해액", "배터리", "전지")),
    ("반도체장비", ("반도체장비", "반도체 장비", "후공정장비", "전공정", "식각", "증착",
                    "노광", "cmp", "웨이퍼 가공", "테스트핸들러", "프로브카드",
                    "본더", "다이서", "반도체 검사", "반도체금형", "드라이스트립",
                    "레이저 마커", "레이저마커", "세정장비", "이온주입")),
    ("반도체", ("반도체", "웨이퍼", "메모리", "dram", "낸드", "시스템반도체", "파운드리",
                "집적회로", "패키징", "hbm")),
    # ★ PCB·전자부품은 별도 섹터다. 반도체로 묶으면 밸류체인이 뭉개지고,
    #   '기타'로 두면 39종목(미분류 최다)이 통째로 사라진다.
    ("전자부품", ("인쇄회로", "pcb", "fpcb", "mlb", "전자부품", "커넥터", "적층세라믹",
                  "mlcc", "카메라모듈", "컨덴서", "콘덴서", "저항기", "인덕터",
                  "리드프레임", "기판")),
    ("디스플레이", ("디스플레이", "oled", "lcd", "tft", "패널", "편광", "led",
                    "광학기기", "사진장비", "영상 및 음향", "음향기기")),
    # ★ '터어빈'(원문 표기)·'발전설비'가 '선박용엔진'보다 먼저 걸려야 한다 —
    #   두산에너빌리티의 products는 '기관,터어빈,선박용엔진,주단조품…'이라
    #   순서를 안 맞추면 조선·해운으로 분류된다(실측).
    ("전력인프라", ("변압기", "전선", "케이블", "송전", "배전", "변전", "전력기기",
                   "개폐기", "차단기", "전력설비", "발전기", "전력 변환", "에너지저장",
                   "ess", "스마트그리드", "전기 변환", "터빈", "터어빈", "발전설비",
                   "전력자원", "전기업", "가스 공급", "열병합", "냉·온수")),
    ("신재생에너지", ("태양광", "풍력", "수소", "연료전지", "바이오매스", "폴리실리콘")),
    ("조선·해운", ("조선", "선박", "보트", "해운", "선박용", "조선기자재", "해양플랜트",
                  "lng선", "보냉재")),
    ("자동차", ("자동차", "차량", "완성차", "타이어", "전장부품", "자동차부품", "차부품")),
    ("바이오·제약", ("의약", "제약", "바이오", "신약", "백신", "항체", "세포치료",
                    "cmo", "cdmo", "건강기능식품", "진단시약", "톡신", "필러",
                    "바이오시밀러", "램시마", "치료제", "임상")),
    ("의료기기", ("의료기기", "의료용 기기", "임플란트", "초음파", "진단기기", "치과",
                  "미용기기", "의료용품")),
    ("엔터·미디어", ("엔터테인먼트", "연예", "음반", "음원", "공연", "아티스트", "드라마",
                    "영화", "방송", "콘텐츠", "웹툰", "매니지먼트", "오디오물", "녹음",
                    "출판", "ent.")),
    ("게임", ("게임", "모바일게임", "온라인게임", "게임소프트웨어")),
    ("인터넷·플랫폼", ("포털", "플랫폼", "전자상거래", "이커머스", "인터넷 정보매개",
                      "광고대행", "커머스")),
    ("소프트웨어·IT", ("소프트웨어", "시스템 통합", "solution", "솔루션", "보안",
                      "클라우드", "erp", "인증서", "데이터베이스", "인공지능",
                      "정보 서비스", "컴퓨터", "주변장치", "프로그래밍")),
    ("통신·네트워크", ("통신장비", "기지국", "안테나", "광케이블", "광섬유", "라우터",
                      "전기 통신", "네트워크장비", "트랜시버")),
    ("건설", ("건설", "토목", "건축", "시공", "플랜트", "주택분양", "엔지니어링")),
    ("건자재", ("시멘트", "레미콘", "철근", "골재", "단열재", "창호", "석고보드",
                "내화물", "도료", "페인트", "유리", "타일", "위생도기", "탱크",
                "구조용 금속", "증기발생기")),
    ("철강·금속", ("철강", "제철", "비철금속", "알루미늄", "구리", "아연", "니켈",
                  "금속 가공", "주조", "단조", "도금")),
    ("화학·소재", ("화학", "석유화학", "합성수지", "플라스틱", "고무", "섬유", "필름",
                  "접착", "촉매", "가스", "펄프", "종이", "판지", "골판지", "포장재")),
    ("기계·로봇", ("로봇", "공작기계", "산업기계", "감속기", "베어링", "펌프", "밸브",
                  "공구", "자동화", "건설기계", "중장비", "equipment", "지게차",
                  "컴프레서", "일반 목적용 기계", "특수 목적용 기계")),
    ("식음료", ("식품", "음료", "주류", "제과", "유가공", "축산", "사료", "알코올",
                "급식", "외식", "담배", "홍삼", "낙농", "유지")),
    ("유통·소비재", ("유통", "도매", "소매", "백화점", "편의점", "홈쇼핑", "화장품",
                    "생활용품", "의류", "패션", "신발", "가죽", "가방", "가구", "침대",
                    "잡화", "완구")),
    ("운송·물류", ("물류", "택배", "운송", "항공운송", "터미널", "창고", "해상운송")),
    ("금융", ("은행", "증권", "보험", "카드", "캐피탈", "저축은행", "자산운용",
              "신탁", "금융", "리스")),
    ("부동산·리츠", ("리츠", "부동산 임대", "부동산임대", "부동산 공급", "임대업")),
    ("지주·기타서비스", ("지주", "경영 컨설팅", "회사 본부", "연구개발업", "교육", "여행",
                        "레저", "호텔", "카지노", "숙박", "학원", "광고", "경비",
                        "사업지원", "전문, 과학")),
)

#: 분류하지 못한 종목. **억지로 끼워 맞추지 않는다.**
UNKNOWN_SECTOR = "기타"

#: 화면 필터에 쓸 전체 목록(규칙 순서 + 기타).
ALL_SECTORS: tuple[str, ...] = tuple(name for name, _ in SECTOR_RULES) + (UNKNOWN_SECTOR,)


def _haystack(*parts: str | None) -> str:
    """비교용 문자열. 소문자 + 공백 정규화."""
    joined = " ".join(p for p in parts if p)
    return re.sub(r"\s+", " ", joined).lower()


def classify_sector(
    name: str | None = None,
    industry: str | None = None,
    products: str | None = None,
) -> str:
    """투자 섹터명을 돌려준다. 못 가리면 `기타`.

    ★ **제품을 업종보다 먼저** 본다. 업종만 보면 '특수 목적용 기계 제조업' 93종목이
      전부 같은 섹터가 되는데, 그 안에 반도체장비·디스플레이장비·조선기자재가 섞여 있다.

    실측 대조 (2026-08-17, 실제 DB 값 그대로):
      한미반도체   / 특수 목적용 기계  / '반도체 후공정장비,반도체금형…'  → 반도체장비
      두산에너빌리티 / 일반 목적용 기계  / '기관,터어빈,선박용엔진,주단조품…' → 전력인프라
      셀트리온     / 기초 의약물질    / '램시마, 트룩시마, 허쥬마'        → 바이오·제약
      동성화인텍   / 기초 화학물질    / '초저온 보냉재'                 → 조선·해운

    ★ **분류는 DB에 적힌 것만 본다.** 두산에너빌리티의 products에는 '원자력'이
      한 글자도 없어서 원전으로 분류되지 않는다 — 투자자 인식과는 다를 수 있다.
      개별 종목을 손으로 박아 넣지 않는 이유: 1,322종목을 그렇게 관리할 수 없고,
      박아 넣은 값은 원자료가 바뀌어도 안 따라가 조용히 낡는다.
    """
    # 1차: 제품으로만 판정한다. 가장 구체적인 신호다.
    product_text = _haystack(products)
    for sector, keywords in SECTOR_RULES:
        if any(k in product_text for k in keywords):
            return sector

    # 2차: 업종(+회사명)으로 떨어진다.
    fallback_text = _haystack(industry, name)
    for sector, keywords in SECTOR_RULES:
        if any(k in fallback_text for k in keywords):
            return sector

    return UNKNOWN_SECTOR


# ═══════════════════════════════════════════════════════════════════
# DB 반영 — `python -m src.universe.sector_map --save`
#
# ★ 여기서만 I/O를 한다. 위 `classify_sector`는 순수 함수로 남긴다.
# ★ 유니버스를 다시 크롤링하지 않는다 — 이미 DB에 있는 industry/products로
#   충분하고, KRX를 또 때릴 이유가 없다.
# ═══════════════════════════════════════════════════════════════════
def _main() -> int:
    import argparse
    import collections

    from src.db.supabase_client import (
        get_client,
        select_all,
        upsert_tolerating_missing_columns,
    )
    from src.utils.console import enable_utf8_stdout

    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="투자 섹터 분류 → krx_universe.sector")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--show", type=int, default=0, help="섹터별 표본 N개 출력")
    args = parser.parse_args()

    rows = select_all("krx_universe", "code,symbol,name,board,industry,products")
    tagged = [
        (r, classify_sector(r.get("name"), r.get("industry"), r.get("products")))
        for r in rows
    ]
    counts = collections.Counter(sector for _, sector in tagged)

    line = "═" * 66
    print(line)
    print(f"투자 섹터 분류 — {len(rows)}종목 → {len(counts)}섹터")
    print(line)
    for sector, n in counts.most_common():
        bar = "█" * max(1, round(n / max(counts.values()) * 28))
        print(f"  {sector:<14}{n:>5}  {bar}")

    unknown = counts.get(UNKNOWN_SECTOR, 0)
    print(f"\n  미분류 {unknown}종목 ({unknown / max(len(rows), 1) * 100:.1f}%)")
    print("  ★ 미분류는 억지로 끼워 맞추지 않은 결과다 — 틀린 섹터보다 낫다.")

    if args.show:
        print("\n섹터별 표본")
        by_sector: dict[str, list[str]] = collections.defaultdict(list)
        for row, sector in tagged:
            by_sector[sector].append(str(row.get("name")))
        for sector, _ in counts.most_common():
            print(f"  {sector:<14}{', '.join(by_sector[sector][: args.show])}")

    if not args.save:
        print("\n(--save 미지정 — DB에 기록하지 않았다)")
        return 0

    # ★ upsert는 NOT NULL 컬럼을 전부 요구한다(symbol·name·board). 빼면 23502로 죽는다.
    payload = [
        {
            "code": r["code"], "symbol": r["symbol"], "name": r["name"],
            "board": r["board"], "sector": sector,
        }
        for r, sector in tagged
    ]
    saved, dropped = upsert_tolerating_missing_columns(
        get_client(), "krx_universe", payload, on_conflict="code"
    )
    print(f"\n✓ krx_universe {saved}행 갱신")
    if dropped:
        print(f"  ⚠ DB에 없는 컬럼을 빼고 저장했다: {', '.join(dropped)}")
        print("    → schema.sql의 `ADD COLUMN sector`를 SQL Editor에 적용하라 (T18).")
        print("    분류는 됐지만 **저장되지 않았다.**")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
