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


# ── 2026-11-08 "모든 범위를 포함해서 기록" — 본문에 payload 전 필드가 남는가 ──

_PAYLOAD = {
    "one_line_thesis": "HBM 후공정 장비 수주가 매출로 전환되기 시작",
    "why_now": "3분기 수주 1,200억원이 4분기 매출로 인식",
    "earnings_change": {"cause": "TC 본더 출하 2배", "outlook": "4Q 매출 +40%"},
    "growth_engine": [{"title": "HBM4", "evidence": "고객사 2곳 퀄 통과"}],
    "acceleration_quality": {"is_genuine": True, "structural_or_temporary": "구조적",
                             "sustainability_quarters": 4, "base_effect_assessment": "기저 낮음"},
    "triggers": {"within_3m": [{"event": "4Q 잠정실적", "expected_date": "2027-01",
                                "verifiable_metric": "매출 1,500억원"}],
                 "within_6m": [{"event": "HBM4 양산", "expected_date": "2027-03"}]},
    "price_position": {"verdict": "미반영", "reason": "PER 12배", "priced_in": ["HBM3E"],
                       "not_priced_in": ["HBM4"]},
    "scenarios": {"bull": {"probability": 30, "condition": "점유율 50%", "implication": "+60%"},
                  "bear": {"probability": 20, "condition": "고객 이탈", "implication": "-30%"}},
    "risks": [{"risk": "고객 집중", "likelihood": "중간", "watch_metric": "고객 비중"}],
    "how_i_could_be_wrong": ["경쟁사 장비 채택"],
    "global_chain": {"upstream": "NVIDIA Rubin", "customers": ["SK하이닉스"]},
    "broker_reports": [{"publisher": "KB증권", "published_at": "2026-10-30", "key_point": "목표가 상향"}],
    "next_data_to_watch": ["11월 수출입 통계"],
    "future_field_xyz": "나중에 추가된 필드",
}


def _texts(blocks):
    return "\n".join("".join(r["text"]["content"] for r in b[b["type"]].get("rich_text", []))
                     for b in blocks)


def _leaves(v):
    if isinstance(v, dict):
        for x in v.values():
            yield from _leaves(x)
    elif isinstance(v, list):
        for x in v:
            yield from _leaves(x)
    elif isinstance(v, str) and v:
        yield v


def test_page_body_keeps_every_payload_string():
    from src.notify.notion_export import build_page_body
    blocks = build_page_body(
        code="042700", name="한미반도체", fy=2026, fq=3, payload=_PAYLOAD,
        screen={"grade": "△", "score_final": 61.2, "pri": 0.31, "has_consensus": False,
                "gate_detail": {"g1": "매출 YoY 가속 +12%p"}},
        fund={"revenue": 1.5e11, "revenue_yoy": 85.3, "op": 4.2e10, "op_status_label": None,
              "opm": 28.0, "opm_yoy_delta": 6.1, "fs_div": "CFS"},
        sector="특수 목적용 기계 제조업", link="https://dart/x", dashboard="https://h/stock/042700")
    text = _texts(blocks)
    missing = [s for s in _leaves(_PAYLOAD) if s not in text]
    assert not missing, missing
    assert "등급 △" in text and "컨센서스 있음 아니오" in text and "매출 YoY 가속 +12%p" in text
    assert "매출: 1,500억원" in text and "OPM YoY: +6.1%p" in text
    assert all(len(r["text"]["content"]) <= 2000 for b in blocks
               for r in b[b["type"]].get("rich_text", []))


def test_low_grades_are_exported_with_signal():
    """△·✕도 내보낸다 — 등급은 신호강도·영향 칸으로 구분한다."""
    from src.notify.notion_export import build_row
    allowed = {"영향": {"긍정", "중립", "부정"}, "신호강도": {"1", "2", "3", "4", "5"}, "기업": set()}
    row = build_row(code="000000", name="X", fy=2026, fq=3, payload={}, grade="✕", score=10,
                    fund={}, sector=None, day="2026-11-08", link="L", dashboard="D", allowed=allowed)
    assert row["신호강도"]["select"]["name"] == "1"
    assert row["영향"]["select"]["name"] == "부정"


def test_run_no_longer_filters_by_grade():
    import inspect
    from src.notify import notion_export
    src = inspect.getsource(notion_export.run)
    assert "NOTIFY_GRADES" not in src and "continue" not in src


def test_string_payload_fields_do_not_break_row():
    """옛 행은 earnings_change·price_position이 문자열로 저장돼 있다(실측 11/09 5건 실패)."""
    from src.notify.notion_export import build_row
    allowed = {"영향": {"긍정", "중립", "부정"}, "신호강도": {"1", "2", "3", "4", "5"}, "기업": set()}
    row = build_row(code="053260", name="X", fy=2026, fq=2,
                    payload={"one_line_thesis": "t", "earnings_change": '{"cause":">skip',
                             "price_position": "미반영"},
                    grade="△", score=50, fund={}, sector=None, day="2026-08-20", link="L",
                    dashboard="D", allowed=allowed)
    assert row["제목"]["title"][0]["text"]["content"].startswith("[Heimdallr] X 2026.2Q")
