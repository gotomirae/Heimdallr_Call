# PRD Ref: §7.1 · traps.md T93, T99, T101
"""LLM 입력에 **써야 한다고 시킨 것의 재료가 실제로 실리는가.** 외부 I/O 없이 돈다.

이 프로젝트에서 세 번 반복된 실패가 있다.

  T93  — `excerpt`가 항상 None인데 프롬프트는 "증설·수주를 써라"고 시켰다
  T99  — 발췌를 실었는데 **어느 분기 것인지** 안 실었다
  T101 — `price_history`를 쓰라면서 **주가 궤적**을 안 줬고,
         트리거 `expected_date`를 잡으라면서 **공시일과 오늘 날짜**를 안 줬다

전부 같은 모양이다: **출력을 프롬프트로 밀면서 입력에 그 재료가 있는지 확인하지 않았다.**
숫자만 주고 사건을 쓰라면 모델은 지어내거나 비운다 — 그리고 둘 다 에러가 아니다.

그래서 여기서는 "스키마가 요구하는 필드마다 그 근거가 입력에 있는가"를 검사한다.
"""

from __future__ import annotations

from src.analysis.analyze import AnalysisInput, build_user_message
from src.analysis.prompts import SYSTEM_PROMPT


def _input(**kw) -> AnalysisInput:
    base = dict(code="097230", name="HJ중공업", board="KOSPI")
    base.update(kw)
    return AnalysisInput(**base)


# ── 분기말 주가 시계열 ───────────────────────────────────────────────

_PRICES = [
    {"fiscal_year": 2025, "fiscal_quarter": 4, "close": 21050.0, "trade_date": "2025-12-30"},
    {"fiscal_year": 2026, "fiscal_quarter": 1, "close": 21750.0, "trade_date": "2026-03-31"},
    {"fiscal_year": 2026, "fiscal_quarter": 2, "close": 20150.0, "trade_date": "2026-06-30"},
    {"fiscal_year": 2026, "fiscal_quarter": 3, "close": 16810.0, "trade_date": "2026-08-24"},
]


def test_quarter_prices_reach_the_model():
    """★★ `price_position.price_history`를 쓰라고 시켰으면 궤적을 줘야 한다(T101)."""
    message = build_user_message(_input(quarter_prices=_PRICES))
    assert "21,050" in message
    assert "16,810" in message


def test_quarter_prices_are_ordered_oldest_first():
    """시간 순서로 서술하라고 시켰으니 시간 순서로 준다. 뒤섞여 오면 정렬한다."""
    message = build_user_message(_input(quarter_prices=list(reversed(_PRICES))))
    assert message.index("21,050") < message.index("16,810")


def test_quarter_price_moves_are_precomputed():
    """★ 등락률은 **우리가 계산해서 준다.**

    모델에게 산수를 시키면 틀린 값이 본문에 인용되고, 화면은 그것을 그대로 보여준다.
    손계산: 20,150 → 16,810 = −16.6%
    """
    message = build_user_message(_input(quarter_prices=_PRICES))
    assert "-16.6%" in message


def test_missing_quarter_prices_say_so_rather_than_vanish():
    message = build_user_message(_input(quarter_prices=[]))
    assert "분기말 주가: (없음)" in message


def test_price_snapshot_is_the_only_current_price_in_llm_history():
    """같은 날 KIS/Naver 값이 달라도 모델에는 canonical 현재가 하나만 준다(T115)."""
    message = build_user_message(_input(
        price={"code": "097230", "snap_date": "2026-08-27", "close": 17_160.0},
        quarter_prices=_PRICES[:-1] + [{
            "fiscal_year": 2026,
            "fiscal_quarter": 3,
            "close": 17_120.0,
            "trade_date": "2026-08-27",
        }],
    ))

    assert '"close": 17160.0' in message
    assert message.count("17,160원") == 1
    assert "17,120원" not in message
    assert "시세 스냅샷 기준 현재가" in message


# ── 최근 공시 목록 ───────────────────────────────────────────────────

_DISC = [
    {"report_nm": "반기보고서 (2026.06)", "disclosed_at": "2026-08-12T00:00:00+00:00"},
    {"report_nm": "연결재무제표기준영업(잠정)실적(공정공시)",
     "disclosed_at": "2026-07-29T00:00:00+00:00"},
]


def test_disclosure_list_reaches_the_model():
    """발췌가 '내용'이면 이건 '무엇이 언제 나왔는가'다 — 트리거 시점의 근거다."""
    message = build_user_message(_input(disclosures=_DISC))
    assert "2026-08-12" in message
    assert "반기보고서" in message


def test_disclosures_are_newest_first():
    message = build_user_message(_input(disclosures=list(reversed(_DISC))))
    assert message.index("2026-08-12") < message.index("2026-07-29")


def test_disclosure_list_is_capped_and_says_what_it_hid():
    """★ 조용히 자르지 않는다 — 몇 건을 감췄는지 밝힌다(T100의 교훈)."""
    many = [
        {"report_nm": f"공시{i}", "disclosed_at": f"2026-0{1 + i % 8}-01T00:00:00+00:00"}
        for i in range(30)
    ]
    message = build_user_message(_input(disclosures=many))
    assert "외 18건" in message


def test_missing_disclosures_say_so():
    message = build_user_message(_input(disclosures=[]))
    assert "수집된 공시 없음" in message


# ── 기준일 ───────────────────────────────────────────────────────────


def test_as_of_date_reaches_the_model():
    """★★ 모델은 지금이 언제인지 모른다.

    기준일이 없으면 다음 분기 전망과 `expected_date`를 **학습 시점 기준**으로 잡는다.
    """
    message = build_user_message(_input(as_of="2026-08-24"))
    assert "2026-08-24" in message
    assert "데이터 기준일" in message


def test_as_of_tells_the_model_what_it_cannot_know():
    """기준일만 주면 모델은 그 뒤 사건을 **추측해서** 채운다. 경계를 명시한다."""
    message = build_user_message(_input(as_of="2026-08-24"))
    assert "이 날짜 이후의 사건은 입력에 없다" in message


def test_trigger_month_limits_are_precomputed_across_year_boundary():
    """트리거 범위의 달력 계산도 LLM에게 맡기지 않는다(T109)."""
    message = build_user_message(_input(as_of="2026-11-30"))
    assert "within_3m expected_date는 2027-02 이하" in message
    assert "within_6m expected_date는 2027-05 이하" in message


def test_missing_as_of_makes_trigger_limits_explicitly_unavailable():
    message = build_user_message(_input(as_of=None))
    assert "트리거 월 상한: 계산 불가" in message


def test_prompt_forbids_new_arithmetic_and_requires_latest_disclosure_citation():
    assert "차액·증가액·변화율을 새로 계산하지 마라" in SYSTEM_PROMPT
    assert "결정론적 절대 증감" in SYSTEM_PROMPT
    assert "최신 공시명과 접수일" in SYSTEM_PROMPT
    assert "트리거 월 상한" in SYSTEM_PROMPT
    assert "[[F001]]" not in SYSTEM_PROMPT


# ── 회귀 방어: 스키마가 요구하는 것 ↔ 입력이 주는 것 ──────────────────


def test_every_narrative_field_has_its_evidence_in_the_input():
    """★★ 프롬프트가 요구하는 서술마다 **근거 블록이 메시지에 있는지** 본다.

    T93·T99·T101이 전부 여기서 걸렸어야 했다. 스키마만 늘리고 입력을 안 늘리면
    모델은 빈칸을 지어내고, 그것은 **에러 없이** 화면에 나간다.
    """
    message = build_user_message(_input(
        quarters=[{"fiscal_year": 2026, "fiscal_quarter": 2}],
        quarter_prices=_PRICES,
        disclosures=_DISC,
        excerpt="[출처: 2026년 2분기 정기보고서]\n\n### 매출 및 수주상황\n수주잔고",
        as_of="2026-08-24",
    ))
    required_blocks = {
        "earnings_change.cause → 분기 실적표": "## 2. 분기 실적",
        "earnings_change 절대금액 → Python 증감액": "## 2-1. 결정론적 절대 증감",
        "price_position.reason → 주가·밸류에이션": "## 5. 주가",
        "price_position.price_history → 분기말 주가 궤적": "분기말 종가 추이",
        "triggers → 공시 원문 발췌": "## 6. 공시 발췌",
        "triggers.expected_date → 최근 공시일": "## 6-1. 최근 공시",
        "outlook → 데이터 기준일": "데이터 기준일",
    }
    for field, marker in required_blocks.items():
        assert marker in message, f"{field}: 근거 블록 '{marker}'가 입력에 없다"


# ── 재분석 판정: `created_at`은 '마지막으로 분석한 시각'이다 (T102) ─────────


def test_save_stamps_the_time_it_actually_ran(monkeypatch):
    """★★ upsert는 DB 기본값을 다시 걸지 않는다 — 직접 넣지 않으면 **처음 날짜에 머문다.**

    `--refresh-before`가 이 칸으로 "낡았는가"를 판정하므로, 값이 안 움직이면
    **방금 다시 돌린 종목이 계속 다시 대상이 된다** — 배치가 끊겼다 재개될
    때마다 상위 종목만 반복 결제한다. 예산이 빠듯할수록 치명적이다.
    """
    from datetime import datetime, timezone

    from src.analysis import analyze as mod

    captured: list[dict] = []

    class _Table:
        def upsert(self, payload, **_kw):
            captured.append(payload)
            return self

        def execute(self):
            return None

    monkeypatch.setattr(
        mod, "get_client",
        lambda: type("D", (), {"table": lambda s, n: _Table()})(),
        raising=False,
    )
    import src.db.supabase_client as sc
    monkeypatch.setattr(
        sc, "get_client",
        lambda: type("D", (), {"table": lambda s, n: _Table()})(),
    )

    mod.save(mod.AnalysisResult(
        code="005930", fiscal_year=2026, fiscal_quarter=2, payload={"x": 1},
        model="claude-sonnet-5", cost_usd=0.05,
        input_tokens=1, cache_read_tokens=0, cache_write_tokens=0, output_tokens=1,
    ))

    stamped = captured[0]["created_at"]
    assert stamped, "created_at을 안 넣었다 — 재분석 판정이 영영 낡은 값을 본다"
    # 방금 찍힌 시각이어야 한다 (몇 초 이내)
    delta = datetime.now(timezone.utc) - datetime.fromisoformat(stamped)
    assert abs(delta.total_seconds()) < 60
