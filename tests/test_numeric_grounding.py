# PRD Ref: §7.2, §7.4 · traps.md T110, T114, T120, T123
"""LLM이 사실 서술에 새 재무 숫자를 만들면 저장 전에 차단한다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.analysis.analyze import (
    AnalysisError,
    AnalysisInput,
    analysis_result_from_response,
    build_llm_request,
)
from src.analysis.numeric_grounding import unsupported_factual_numbers
from src.analysis.numeric_grounding import (
    annotate_factual_numbers,
    resolve_factual_references,
)
from src.llm.provider import LLMResponse, NormalizedUsage


ROOT = Path(__file__).resolve().parents[1]
ATTEMPT_3 = (
    ROOT / "docs/evals/results/hj-097230-2026q2-openai-terra-attempt-3.json"
)


def _response(payload: dict) -> LLMResponse:
    return LLMResponse(
        provider="fake",
        model="offline",
        payload=payload,
        usage=NormalizedUsage(input_tokens=10, output_tokens=10),
        stop_reason="completed",
        response_id="resp_grounding",
    )


def test_attempt_3_reproduces_only_the_llm_unit_conversion():
    raw = json.loads(ATTEMPT_3.read_text(encoding="utf-8"))
    candidate = raw["candidate"]

    unsupported = unsupported_factual_numbers(
        AnalysisInput(**raw["input"]),
        candidate["payload"],
        user_message=candidate["request_snapshot"]["request"]["user_message"],
    )

    assert unsupported == ["267억"]


def test_grounded_fact_is_allowed_but_new_fact_is_rejected():
    data = AnalysisInput(
        code="097230",
        name="HJ중공업",
        board="KOSPI",
        quarters=[{
            "fiscal_year": 2026,
            "fiscal_quarter": 2,
            "revenue": 10_000_000_000,
        }],
    )

    assert unsupported_factual_numbers(
        data,
        {"why_now": "매출 100억원이 확인됐다."},
        user_message="2026.2Q 매출은 100억원이다.",
    ) == []
    assert unsupported_factual_numbers(
        data,
        {"why_now": "매출 267억원이 확인됐다."},
        user_message="2026.2Q 매출은 100억원이다.",
    ) == ["267억"]


def test_same_disclosure_unit_is_allowed_without_llm_conversion():
    data = AnalysisInput(code="097230", name="HJ중공업", board="KOSPI")

    assert unsupported_factual_numbers(
        data,
        {"why_now": "공시상 수리선 매출은 26,737백만원이다."},
        user_message="(단위: 백만원) 수리선 | 합계 | 26,737",
    ) == []


def test_production_table_unit_header_allows_spaces_around_colon():
    data = AnalysisInput(code="004000", name="롯데정밀화학", board="KOSPI")

    assert unsupported_factual_numbers(
        data,
        {"why_now": "원재료 매입액은 238,679백만원이다."},
        user_message="(단위 : 백만원)\n원재료 | 매입액 | 비율(%)\n프로필렌 | 238,679 | 88.0",
    ) == []


def test_json_percentage_allows_two_decimal_display_rounding():
    data = AnalysisInput(
        code="004000",
        name="롯데정밀화학",
        board="KOSPI",
        price={"rel_ret_3m": 8.639552506992088},
    )

    assert unsupported_factual_numbers(
        data,
        {"price_position": {"reason": "3개월 상대수익률은 +8.64%다."}},
        user_message="시세 JSON에 rel_ret_3m 원자료가 있다.",
    ) == []


def test_same_unit_one_decimal_allows_normal_whole_number_rounding():
    data = AnalysisInput(code="097230", name="HJ중공업", board="KOSPI")

    assert unsupported_factual_numbers(
        data,
        {"why_now": "영업이익 YoY는 +1115%, 증가액은 +595억원이다."},
        user_message="영업이익 YoY +1114.7%, 증가액 +595.1억원",
    ) == []


def test_pipe_table_percentage_allows_normal_whole_number_rounding():
    data = AnalysisInput(code="097230", name="HJ중공업", board="KOSPI")

    assert unsupported_factual_numbers(
        data,
        {"why_now": "영업이익 YoY는 +1115%다."},
        user_message=(
            "분기 | 매출 | YoY(%) | 영업이익 | YoY(%)\n"
            "2026.2Q | 7,299 | +43.7 | 649 | +1114.7"
        ),
    ) == []


def test_same_unit_half_value_cannot_be_truncated_instead_of_rounded():
    data = AnalysisInput(code="004000", name="롯데정밀화학", board="KOSPI")

    assert unsupported_factual_numbers(
        data,
        {"why_now": "영업이익 YoY는 +610%다."},
        user_message="영업이익 YoY +610.5%",
    ) == ["610%"]


def test_future_scenario_threshold_is_not_misclassified_as_historical_fact():
    data = AnalysisInput(code="097230", name="HJ중공업", board="KOSPI")
    payload = {
        "why_now": "입력 수치만으로 지속성 확인이 필요하다.",
        "scenarios": {
            "bull": {
                "condition": "다음 분기 매출 267억원 이상",
                "implication": "성장 지속",
            }
        },
    }

    assert unsupported_factual_numbers(
        data,
        payload,
        user_message="현재 사실 숫자는 제공되지 않았다.",
    ) == []


def test_analysis_result_blocks_unsupported_fact_before_it_can_be_saved():
    data = AnalysisInput(code="097230", name="HJ중공업", board="KOSPI")

    with pytest.raises(AnalysisError, match=r"입력에 없는 사실 숫자.*267억"):
        analysis_result_from_response(
            data,
            _response({"why_now": "수리선 매출은 267억원이다."}),
            cost_usd=0.01,
            max_output_tokens=1_000,
            request_user_message="수리선 매출은 26,737백만원이다.",
        )


def test_input_numbers_are_annotated_inline_without_duplicating_the_message():
    message = (
        "분기 | 매출(억) | YoY% | 영업이익(억)\n"
        "2026.2Q | 7,299 | +43.7 | 649\n"
        "증감 +595.1억원 · 현재가 17,160원"
    )

    annotated = annotate_factual_numbers(message)

    assert "[[F001:7,299억]]" in annotated
    assert "[[F002:+43.7%]]" in annotated
    assert "[[F003:649억]]" in annotated
    assert "[[F004:+595.1억원]]" in annotated
    assert "[[F005:17,160원]]" in annotated
    assert annotated.count("+595.1억원") == 1
    assert annotated.count("17,160원") == 1
    assert annotate_factual_numbers(annotated) == annotated


def test_reference_is_expanded_to_the_exact_input_number():
    request = annotate_factual_numbers("매출 증가액 +595.1억원")
    payload = {"why_now": "매출 증가액은 [[F001]]으로 확대됐다."}

    resolved = resolve_factual_references(payload, user_message=request)

    assert resolved["why_now"] == "매출 증가액은 +595.1억원으로 확대됐다."


def test_operating_request_keeps_unproven_reference_contract_disabled():
    operating = build_llm_request(
        AnalysisInput(code="097230", name="HJ중공업", board="KOSPI"),
        model="offline",
        web_search=False,
        user_message="매출 증가액 +595.1억원",
    )
    experimental = build_llm_request(
        AnalysisInput(code="097230", name="HJ중공업", board="KOSPI"),
        model="offline",
        web_search=False,
        user_message="매출 증가액 +595.1억원",
        factual_references=True,
    )

    assert operating.user_message == "매출 증가액 +595.1억원"
    assert "[[F001]]" not in operating.system_prompt
    assert experimental.user_message == "매출 증가액 [[F001:+595.1억원]]"
    assert "[[F001]]" in experimental.system_prompt


def test_exact_direct_factual_number_is_left_for_existing_grounding_gate():
    request = annotate_factual_numbers("매출 증가액 +595.1억원")

    resolved = resolve_factual_references(
        {"why_now": "매출 증가액은 +595.1억원이다."},
        user_message=request,
    )

    assert resolved["why_now"] == "매출 증가액은 +595.1억원이다."


def test_exact_source_annotation_echo_is_resolved_safely():
    request = annotate_factual_numbers("매출 증가액 +595.1억원")

    resolved = resolve_factual_references(
        {"why_now": "매출 증가액은 [[F001:+595.1억원]]이다."},
        user_message=request,
    )

    assert resolved["why_now"] == "매출 증가액은 +595.1억원이다."


def test_tampered_source_annotation_is_rejected():
    request = annotate_factual_numbers("매출 증가액 +595.1억원")

    with pytest.raises(ValueError, match="숫자 참조 원문 불일치.*F001"):
        resolve_factual_references(
            {"why_now": "매출 증가액은 [[F001:+999억원]]이다."},
            user_message=request,
        )


def test_unknown_reference_is_rejected_instead_of_leaking_to_storage():
    request = annotate_factual_numbers("매출 증가액 +595.1억원")

    with pytest.raises(ValueError, match="입력에 없는 숫자 참조.*F999"):
        resolve_factual_references(
            {"why_now": "매출 증가액은 [[F999]]이다."},
            user_message=request,
        )


def test_future_threshold_does_not_require_a_factual_reference():
    request = annotate_factual_numbers("현재 매출 100억원")
    payload = {
        "why_now": "현재 매출은 [[F001]]이다.",
        "scenarios": {
            "bull": {
                "condition": "다음 분기 매출 267억원 이상",
                "implication": "성장 지속",
            }
        },
    }

    resolved = resolve_factual_references(payload, user_message=request)

    assert resolved["why_now"] == "현재 매출은 100억원이다."
    assert resolved["scenarios"] == payload["scenarios"]


def test_analysis_result_resolves_reference_before_existing_grounding_gate():
    data = AnalysisInput(code="097230", name="HJ중공업", board="KOSPI")
    request = annotate_factual_numbers("수리선 매출은 26,737백만원이다.")

    result = analysis_result_from_response(
        data,
        _response({"why_now": "수리선 매출은 [[F001]]이다."}),
        cost_usd=0.01,
        max_output_tokens=1_000,
        request_user_message=request,
    )

    assert result.payload["why_now"] == "수리선 매출은 26,737백만원이다."
