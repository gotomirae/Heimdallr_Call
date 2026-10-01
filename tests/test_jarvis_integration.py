# PRD Ref: §8.8, §9 · JARVIS INTEGRATION_TASKS B-9·B-10·B-11·B-13·B-14
"""JARVIS 연계 계약 중 entry_checks 밖의 것들 — 전부 순수 함수만 시험한다."""

from __future__ import annotations

import pytest

from src.analysis.clean_stored_run import clean_payload
from src.analysis.numeric_grounding import (
    LEGACY_REDACTION_MARKER,
    redact_unsupported_factual_numbers,
    remove_spans_as_sentences,
    unwrap_leftover_fact_markers,
)
from src.analysis.schema_validation import prune_placeholder_items, schema_problems
from src.db.check_anon import JARVIS_TABLES, classify
from src.universe.industry_l1 import STATIC_SECTOR_L1, resolve_l1, unknown_codes
from src.universe.sector_map import ALL_SECTORS, classify_sector


# ═══ B-10 투자 섹터 → 노션 L1 ═════════════════════════════════════
def test_every_investment_sector_has_a_static_l1():
    """새 섹터를 만들고 매핑을 빼먹으면 JARVIS에서 조용히 ETC가 된다."""
    assert set(ALL_SECTORS) <= set(STATIC_SECTOR_L1)


def test_l1_resolution_order_override_static_synonym_default():
    taxonomy = {
        "l1": [{"code": "2d", "name": "소비재", "l2": ["음식료"], "synonyms": ["유통"]}],
        "overrides": [{"project": "*", "label": "화학·소재", "l1": ["ETC"]},
                      {"project": "hermescall", "label": "자동차", "l1": ["2b"]}],
        "unmatched_default": "ETC",
    }
    assert resolve_l1("화학·소재", taxonomy) == (("ETC",), "jarvis_override")
    assert resolve_l1("자동차", taxonomy) == (("1l",), "static")  # 다른 프로젝트 override 무시
    assert resolve_l1("반도체 장비", None) == (("1b",), "static")
    assert resolve_l1("식음료", taxonomy) == (("2d",), "static")  # 별칭 → 음식료
    assert resolve_l1("유통", taxonomy) == (("2d",), "jarvis_synonym")
    assert resolve_l1("새 섹터", taxonomy) == (("ETC",), "default")


def test_unknown_static_codes_are_reported():
    taxonomy = {"l1": [{"code": "1a"}], "special_labels": [{"code": "ETC"}]}
    assert "1b" in unknown_codes(taxonomy)
    assert unknown_codes(None) == []


# ═══ B-13 유통·소비재 오분류 ══════════════════════════════════════
@pytest.mark.parametrize(("industry", "products", "expected"), [
    ("기초 화학물질 제조업", "에폭시수지, 폴리올 제조, 도매", "화학·소재"),
    ("1차 철강 제조업", "강관 제조 및 도매", "철강·금속"),
    ("석유 정제품 제조업", "윤활유 제조,도매", "화학·소재"),
    ("비료, 농약 및 살균, 살충제 제조업", "비료 도매", "화학·소재"),
    ("전기 통신업", "이동통신, 유선통신, 단말기 도매", "통신·네트워크"),
    ("텔레비전 방송업", "홈쇼핑, 방송, 영화", "엔터·미디어"),
    ("의약품 제조업", "양약(부루펜,액티피드,포리부틴) 제조,도매", "바이오·제약"),
])
def test_distribution_word_in_products_yields_to_ksic_industry(industry, products, expected):
    assert classify_sector(None, industry, products) == expected


def test_fertilizer_word_in_products_does_not_move_lime_maker():
    """'석회비료'의 비료는 업종 칸에서만 본다 — 생석회 제조사는 건자재로 남는다(실측 태경비케이)."""
    assert classify_sector(
        None, "시멘트, 석회, 플라스터 및 그 제품 제조업", "생석회,소석회,석회비료 제조,판매"
    ) == "건자재"


@pytest.mark.parametrize(("industry", "products"), [
    ("음·식료품 및 담배 도매업", "식자재 유통"),
    ("백화점", "의류 소매"),
    ("봉제의복 제조업", "의류 도매"),
    ("자동차 신품 판매업", "수입차 도매"),
    (None, "생활용품 도매"),
    # 실측 2026-10-02 — 지주사의 KSIC `기타 금융업`은 본업이 아니다.
    ("기타 금융업", "스포츠의류(등산복,운동복,스키복) 도소매,수출,섬유봉제"),
    ("기타 금융업", "백화점,여행알선,숙박,음식점/부동산 임대"),
])
def test_real_distributors_stay_consumer(industry, products):
    assert classify_sector(None, industry, products) == "유통·소비재"


# ═══ B-14 분석 출력 정리 ══════════════════════════════════════════
def test_leftover_fact_markers_become_values_or_disappear():
    text = "영업이익 [[F 218.8억]]으로 늘었고 주가는 [[F announcement_return_pct -11.375]] 하락했다."
    assert unwrap_leftover_fact_markers(text) == "영업이익 218.8억으로 늘었고 주가는 하락했다."
    nested = {"risks": [{"risk": "[[F 3.2%]] 하락", "watch_metric": "OPM"}]}
    assert unwrap_leftover_fact_markers(nested)["risks"][0]["risk"] == "3.2% 하락"


def test_unsupported_numbers_leave_no_visible_trace():
    from src.analysis.analyze import AnalysisInput

    data = AnalysisInput(code="097230", name="HJ중공업", board="KOSPI")
    two_sentences = {"why_now": "매출은 100억원이다. 근거 없는 목표가는 17,000원이다."}
    cleaned, removed = redact_unsupported_factual_numbers(data, two_sentences, user_message="매출은 100억원이다.")
    assert cleaned["why_now"] == "매출은 100억원이다."
    assert removed == ["17000원"]
    assert LEGACY_REDACTION_MARKER not in str(cleaned)


def test_single_sentence_drops_only_the_token():
    assert remove_spans_as_sentences("매출(17,000원)은 늘었다", [(3, 10)]) == "매출은 늘었다"


def test_placeholder_risk_items_are_pruned_but_real_ones_kept():
    payload = {"risks": [
        {"risk": "...", "likelihood": "중", "impact": "중", "watch_metric": "..."},
        {"risk": "수주 지연", "likelihood": "중", "impact": "상", "watch_metric": "수주잔고"},
    ]}
    pruned = prune_placeholder_items(payload)
    assert [item["risk"] for item in pruned["risks"]] == ["수주 지연"]
    assert schema_problems("…", {"type": "string"}) == ["placeholder:$"]


def test_stored_payload_cleanup_keeps_meta():
    payload = {
        "one_line_thesis": f"이익이 {LEGACY_REDACTION_MARKER} 늘었다. 주가는 [[F 12.5%]] 낮다.",
        "risks": [{"risk": "...", "watch_metric": "..."}],
        "_heimdallr": {"removed_factual_numbers": ["1억"]},
    }
    cleaned = clean_payload(payload)
    assert cleaned["one_line_thesis"] == "주가는 12.5% 낮다."
    assert cleaned["risks"] == []
    assert cleaned["_heimdallr"] == {"removed_factual_numbers": ["1억"]}


# ═══ B-11 anon SELECT 점검 ════════════════════════════════════════
def test_anon_check_distinguishes_missing_table_policy_and_empty():
    assert len(JARVIS_TABLES) == 10 and "entry_checks" in JARVIS_TABLES
    assert classify(None, None, "{'code': 'PGRST205'}").startswith("테이블 없음")
    assert classify(0, 1, None).startswith("정책 누락")
    assert classify(0, 0, None) == "읽기 가능(현재 0행)"
    assert classify(1, 1, None) == "읽기 가능"


def test_distribution_override_matches_typescript():
    """B-13 규칙은 sector_map.py와 dashboard/lib/sector.ts 두 곳에 있다 — 같은 답이어야 한다."""
    import shutil

    from tests.test_sector_map_parity import DASHBOARD, _run_typescript

    if shutil.which("node") is None or not (DASHBOARD / "node_modules" / "jiti").exists():
        pytest.skip("node·jiti 없음 — 대시보드 의존성이 있는 환경에서 대조한다")
    cases = [
        ("기초 화학물질 제조업", "에폭시수지, 폴리올 제조, 도매"),
        ("전기 통신업", "이동통신, 유선통신, 단말기 도매"),
        ("텔레비전 방송업", "홈쇼핑, 방송, 영화"),
        ("백화점", "의류 소매"),
        ("자동차 신품 판매업", "수입차 도매"),
        ("기타 금융업", "백화점,여행알선,숙박,음식점/부동산 임대"),
    ]
    typescript = [row["sector"] for row in _run_typescript(cases)]
    assert typescript == [classify_sector(None, industry, products) for industry, products in cases]


def test_orphan_particle_after_removed_token_is_dropped():
    """실측 000660 — 토큰만 빼면 'OPM 라는 호황'처럼 조사가 고아로 남았다."""
    from src.analysis.numeric_grounding import strip_legacy_redaction_markers

    assert strip_legacy_redaction_markers(f"OPM {LEGACY_REDACTION_MARKER}라는 호황이다") == "OPM 호황이다"
    assert unwrap_leftover_fact_markers("매출 405억(YoY +21.4%, [[F 333→405억]])") == "매출 405억(YoY +21.4%)"


def test_emptied_required_reports_empty_arrays():
    from src.analysis.clean_stored_run import emptied_required

    assert any("risks" in problem for problem in emptied_required({"risks": []}))


def test_scalar_placeholders_are_blanked_and_reported():
    from src.analysis.clean_stored_run import scalar_placeholders

    payload = {"earnings_change": {"cause": "...", "effect": "실제 효과"}, "_heimdallr": {}}
    assert scalar_placeholders(payload) == ["$.earnings_change.cause"]
    assert clean_payload(payload)["earnings_change"] == {"cause": "", "effect": "실제 효과"}
