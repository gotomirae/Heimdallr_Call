# PRD Ref: §7.3, §11 · traps.md T19
"""P7 비용 가드 · 분석 검증 테스트. 외부 I/O 없이 돈다."""

from __future__ import annotations

import inspect

import pytest

from src.analysis.analyze import build_user_message, AnalysisInput, validate_payload
from src.analysis.prompts import ANALYSIS_SCHEMA, SYSTEM_PROMPT
from src.config.constants import (
    DAILY_ANALYSIS_LIMIT,
    MONTHLY_COST_CEILING_USD,
    ANALYSIS_MODEL,
    FALLBACK_MODEL,
    LLM_INPUT_TOKEN_BUDGET,
    LLM_MAX_TOKENS,
)
from src.utils import cost_guard
from src.utils.cost_guard import UnknownModelError, compute_cost_usd, get_pricing


# ═══ T19 — 날짜 기준 가격 전환 금지 ═══
def test_pricing_takes_no_date_argument():
    """★ 참고 프로젝트는 `get_pricing(model, as_of)`로 날짜 분기를 했다.

    2026-08-13 Anthropic 공식 pricing 확인: $2/$10이 정가이고
    2026-09-01 인상은 시행되지 않는다. 날짜 인자가 있으면 그 로직이 되살아난다.
    """
    params = inspect.signature(get_pricing).parameters
    assert list(params) == ["model"], f"날짜 인자가 생겼다: {list(params)}"


def test_sonnet_rates_are_flat():
    rates = get_pricing(ANALYSIS_MODEL)
    assert (rates.input, rates.output) == (2.0, 10.0)
    assert (rates.cache_write, rates.cache_read) == (2.50, 0.20)


def test_haiku_rates():
    rates = get_pricing(FALLBACK_MODEL)
    assert (rates.input, rates.output) == (1.0, 5.0)


def test_unknown_model_is_not_guessed():
    """단가를 모르면 추측해서 계산하지 않는다 — 비용이 조용히 틀린다."""
    with pytest.raises(UnknownModelError):
        get_pricing("gpt-4o")


def test_no_date_switch_constant_remains():
    """참고 프로젝트의 SONNET_5_PRICE_SWITCH_DATE가 이식되지 않았는지 확인."""
    assert not hasattr(cost_guard, "SONNET_5_PRICE_SWITCH_DATE")


# ═══ 비용 계산 — PRD §11 검산과 대조 ═══
def test_cost_matches_prd_estimate():
    """PRD §11 검산: 입력 4,500 + 캐시읽기 2,500 + 출력 3,200 ≈ $0.0415."""
    cost = compute_cost_usd(
        ANALYSIS_MODEL,
        input_tokens=4_500,
        cache_read_tokens=2_500,
        output_tokens=3_200,
    )
    assert cost == pytest.approx(0.0415, abs=1e-4)


def test_cache_write_costs_more_than_read():
    write = compute_cost_usd(ANALYSIS_MODEL, input_tokens=0, cache_write_tokens=1000)
    read = compute_cost_usd(ANALYSIS_MODEL, input_tokens=0, cache_read_tokens=1000)
    assert write > read * 10


# ═══ ADR 4 — 시스템 프롬프트는 얼어 있어야 한다 ═══
def test_system_prompt_has_no_interpolation():
    """종목별 내용이 들어가면 Prompt Caching이 통째로 깨진다."""
    assert "{" not in SYSTEM_PROMPT or "}" not in SYSTEM_PROMPT.split("{")[0]
    for marker in ("005930", "삼성전자", "2026", "%s", "{code}", "{name}"):
        assert marker not in SYSTEM_PROMPT, f"시스템 프롬프트에 가변 내용: {marker}"


def test_system_prompt_is_long_enough_to_cache():
    """★ Sonnet 5의 최소 캐시 프리픽스는 **1,024토큰**이다.

    미달하면 에러도 경고도 없이 그냥 캐시되지 않는다(`cache_creation_input_tokens: 0`).
    프롬프트를 줄이다가 조용히 문턱 아래로 내려가는 것을 여기서 막는다.

    실측(2026-08-13, count_tokens API): 1,552자 → **1,497토큰** (한글 ≈ 0.96 토큰/자).
    따라서 1,024토큰 ≈ 1,070자. 여유를 두어 1,300자를 하한으로 잡는다.
    """
    assert len(SYSTEM_PROMPT) >= 1_300, (
        f"{len(SYSTEM_PROMPT)}자 — 1,024토큰 문턱(≈1,070자) 아래로 내려갈 위험"
    )


# ═══ 스키마 (PRD §7.2) ═══
def test_schema_requires_prd_fields():
    required = set(ANALYSIS_SCHEMA["required"])
    assert {"one_line_thesis", "why_now", "growth_engine", "acceleration_quality",
            "triggers", "price_position", "scenarios", "risks",
            "next_data_to_watch", "how_i_could_be_wrong"} <= required


def test_schema_is_strict_compatible():
    """strict: true는 additionalProperties: false를 요구한다."""
    assert ANALYSIS_SCHEMA["additionalProperties"] is False


def test_max_tokens_matches_prd():
    """★ PRD §7.3과 코드가 같아야 한다. 한쪽만 고치면 두 문서가 조용히 어긋난다.

    2026-08-17 개정: 8192 → 12288.
    실측 78건 중 2건(3%)이 상한에 닿아 잘렸고, 잘린 건은 저장 안 되면서
    비용은 발생했다($0.0857씩 · 전체의 6%). 출력 중앙값은 2,928토큰이라
    상한을 올려도 평균 비용은 거의 안 오른다.
    """
    assert LLM_MAX_TOKENS == 12288
    assert LLM_INPUT_TOKEN_BUDGET == 5000


def test_guardrails_match_prd_document():
    """★ PRD 본문의 숫자와 상수를 **직접 대조**한다.

    값만 테스트에 박아 두면 PRD가 낡아도 안 걸린다 — 실제로 실링을 $12로 올렸을 때
    PRD는 8로 남아 있었다.
    """
    from pathlib import Path
    import re

    prd = (Path(__file__).resolve().parents[1] / "docs" / "PRD.md").read_text(encoding="utf-8")
    for name, value in (
        ("MONTHLY_COST_CEILING_USD", MONTHLY_COST_CEILING_USD),
        ("DAILY_ANALYSIS_LIMIT", DAILY_ANALYSIS_LIMIT),
        ("max_tokens", LLM_MAX_TOKENS),
    ):
        # ★★ `search`가 아니라 `findall`이다 — PRD는 같은 상수를 **두 곳**에 적는다
        #   (§7.3 가드레일 · 부록 상수표). 첫 매치만 보면 뒤쪽이 낡아도 통과한다.
        #   실측(2026-08-21): §7.3은 12로 갱신됐는데 부록은 **8인 채로 4일간** 남아
        #   있었고 이 테스트는 초록불이었다. **첫 매치가 나머지를 가린다**(T50과 같은 모양).
        found = re.findall(rf"^{re.escape(name)}\s*=\s*(\d+)", prd, re.M)
        assert found, f"PRD에 {name} 줄이 없다"
        mismatched = [n for n in found if int(n) != value]
        assert not mismatched, (
            f"PRD {name}: {found} 중 {mismatched}가 코드 {value}와 다르다 — "
            f"PRD에 이 상수가 {len(found)}곳 있다. **전부** 고쳐라"
        )


# ═══ 저장 전 검증 (T18) ═══
def _good_payload() -> dict:
    return {
        "one_line_thesis": "t", "why_now": "w",
        # 2026-08-17 추가 — 실적 변화의 원인·결과·전망
        "earnings_change": {"cause": "c", "effect": "e", "outlook": "o",
                            "confidence": "medium"},
        "growth_engine": {"drivers": ["물량 증가"], "structural_or_temporary": "structural",
                          "evidence": "e"},
        "acceleration_quality": {"is_genuine": True, "base_effect_assessment": "b",
                                 "sustainability_quarters": 3},
        "triggers": {"within_3m": [{"event": "e", "verifiable_metric": "m",
                                    "expected_date": "2026-11",
                                    "impact": "high", "kind": "실적"}],
                     "within_6m": [{"event": "e", "verifiable_metric": "m",
                                    "expected_date": "2027-02",
                                    "impact": "medium", "kind": "수주"}]},
        "price_position": {"verdict": "적정", "reason": "r", "priced_in": ["a"],
                           "not_priced_in": ["b"]},
        "scenarios": {"bull": {"probability": 0.25, "condition": "c", "implication": "i"},
                      "base": {"probability": 0.55, "condition": "c", "implication": "i"},
                      "bear": {"probability": 0.20, "condition": "c", "implication": "i"}},
        "risks": [{"risk": "r", "likelihood": "중간", "impact": "큼", "watch_metric": "m"}],
        "next_data_to_watch": ["a", "b", "c"],
        "how_i_could_be_wrong": "h",
    }


def test_valid_payload_has_no_problems():
    assert validate_payload(_good_payload()) == []


def test_missing_top_level_field_detected():
    p = _good_payload()
    del p["how_i_could_be_wrong"]
    assert "missing:how_i_could_be_wrong" in validate_payload(p)


def test_probability_sum_checked():
    """확률 합이 1.0 근처가 아니면 잡는다 (PRD §13 검증 항목)."""
    p = _good_payload()
    p["scenarios"]["bull"]["probability"] = 0.9
    problems = validate_payload(p)
    assert any("probability_sum" in x for x in problems)


def test_empty_triggers_detected():
    """★ 상위 객체만 확인하면 빈 트리거를 통과시킨다 (T18)."""
    p = _good_payload()
    p["triggers"]["within_3m"] = []
    assert "empty:triggers.within_3m" in validate_payload(p)


def test_missing_nested_is_genuine_detected():
    p = _good_payload()
    del p["acceleration_quality"]["is_genuine"]
    assert "missing:acceleration_quality.is_genuine" in validate_payload(p)


# ═══ 입력 조립 — 공시 원문 전체를 넣지 않는다 (ADR 4) ═══
def test_excerpt_is_truncated():
    data = AnalysisInput(code="A", name="N", board="KOSPI", excerpt="x" * 10_000)
    message = build_user_message(data)
    assert "x" * 2_001 not in message


def test_no_consensus_is_stated_explicitly():
    """컨센서스가 없으면 '커버리지 없음'을 명시해 서프라이즈를 논하지 않게 한다."""
    message = build_user_message(AnalysisInput(code="A", name="N", board="KOSDAQ"))
    assert "커버리지 없음" in message
