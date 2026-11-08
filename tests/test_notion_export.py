# PRD Ref: §8 · JARVIS NEXUS NXD-7
"""노션 내보내기 — 순수 함수만(외부 I/O 없음)."""

from src.notify import notion_export as ne
from src.notify import notion_sink as ns

ALLOWED = {
    "기업": {"코세스", "LS ELECTRIC"}, "산업": {"반도체", "AI", "전력인프라"},
    "영향": {"긍정", "부정", "중립"}, "신호강도": {"1", "2", "3", "4", "5"},
    "논지 영향": {"강화", "약화", "중립"}, "출처유형": {"IR·실적"}, "등급": {"T1 1차 출처"},
    "검증 상태": {"미검증"}, "수집 경로": {"예약 작업"}, "PDF 본문": {"미확인"},
}


def test_growth_text_uses_status_label_on_sign_flip():
    # 손계산: 부호 전환 구간은 % 계산 금지(T12) — 글자만
    assert ne.growth_text("영업이익 YoY", None, "흑전") == "영업이익 YoY 흑전"
    assert ne.growth_text("매출 YoY", 25.06) == "매출 YoY +25.1%"
    assert ne.growth_text("매출 YoY", None) is None


def test_notion_industries_maps_l1_codes_only_to_existing_names():
    assert ne.notion_industries("반도체 장비") == ["반도체"]
    assert ne.notion_industries("전력인프라") == ["전력인프라"]
    # 자동차(1l)·기타(ETC)는 2_5에 맞는 칸이 없어 비운다
    assert ne.notion_industries("자동차") == []
    assert ne.notion_industries("기타") == []


def _row(name: str, grade: str):
    return ne.build_row(
        code="089890", name=name, fy=2026, fq=3,
        payload={"one_line_thesis": "HBM 후공정 장비 수주가 매출로 전환", "why_now": "3Q 매출 +60%",
                 "earnings_change": {"cause": "TC본더 출하"},
                 "price_position": {"verdict": "적정", "reason": "F.PER 18배"}},
        grade=grade, score=78.4,
        fund={"revenue_yoy": 60.2, "op_yoy": None, "op_status_label": "흑전", "opm": 12.3, "opm_yoy_delta": 9.1},
        sector="반도체 장비", day="2026-11-05T09:00:00+09:00", link="https://dart/x",
        dashboard="https://h/stock/089890", allowed=ALLOWED)


def test_watchlist_company_is_tagged_and_thesis_strengthened():
    row = _row("코세스", "★")
    assert row["기업"] == {"multi_select": [{"name": "코세스"}]}
    assert row["논지 영향"]["select"]["name"] == "강화"
    assert row["신호강도"]["select"]["name"] == "5"
    assert row["날짜"]["date"]["start"] == "2026-11-05"
    nums = row["핵심 수치"]["rich_text"][0]["text"]["content"]
    assert "영업이익 YoY 흑전" in nums and "OPM 12.3%(+9.1%p)" in nums and "점수 78" in nums


def test_non_watchlist_company_never_creates_option():
    row = _row("어떤회사", "○")
    assert "기업" not in row            # 선택지를 새로 만들지 않는다
    assert "논지 영향" not in row       # 관심종목이 아니면 논지 영향도 비운다
    assert row["영향"]["select"]["name"] == "긍정"


def test_signal_scale():
    assert ns.signal_from_strength(9) == "4"
    assert ns.signal_from_strength(10) == "5"
    assert ns.signal_from_strength(1) == "1"
    assert ns.signal_from_strength(None) is None
