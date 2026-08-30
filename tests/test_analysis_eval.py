# PRD Ref: §7.4 · ADR 3, 9
"""Provider replay 결과를 외부 호출 없이 같은 기준으로 평가한다."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.analysis.eval_run import suite_with_canary_result
from src.analysis.evaluation import (
    EvalCandidate,
    EvalCase,
    casebook_coverage,
    evaluate_candidate,
    evaluate_suite,
    schema_problems,
)
from src.analysis.analyze import build_llm_request
from src.llm.request_snapshot import (
    analysis_input_sha256,
    canonical_sha256,
    snapshot_llm_request,
)
from src.config.constants import (
    LLM_CANARY_MAX_COST_USD,
    LLM_CANARY_MAX_OUTPUT_TOKENS,
    LLM_EVAL_MIN_EVIDENCE_COVERAGE,
    LLM_EVAL_MIN_DIMENSION_EVIDENCE_COVERAGE,
    LLM_EVAL_MIN_SCORE,
    LLM_EVAL_WEIGHTS,
)


FIXTURE = Path(__file__).parent / "fixtures" / "llm_eval" / "representative_turnaround.json"


def _raw() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _case() -> EvalCase:
    return EvalCase.from_dict(_raw()["cases"][0])


def _payload() -> dict:
    return {
        "one_line_thesis": "매출 1,500억과 흑전이 확인됐지만 주가는 아직 회복 초기다.",
        "why_now": "2026.2Q 매출 1,500억, OPM 8%로 전환됐다. 수주잔고 3,000억이 후속 매출의 근거다.",
        "earnings_change": {
            "cause": "매출 1,500억과 OPM 8%가 확인됐고 흑전했다.",
            "effect": "적자 구조에서 흑자 구조로 바뀌었다.",
            "outlook": "신규 설비가 가동되면 다음 분기 물량 지속 여부를 확인해야 한다.",
            "confidence": "medium",
        },
        "growth_engine": {
            "drivers": ["CAPA 확대", "물량 증가"],
            "structural_or_temporary": "structural",
            "evidence": "수주잔고 3,000억원과 2026-10 상업 가동 계획이 있다.",
        },
        "acceleration_quality": {
            "is_genuine": True,
            "base_effect_assessment": "전년 동기 OPM -5%의 낮은 기저가 있으므로 후속 확인이 필요하다.",
            "sustainability_quarters": 2,
        },
        "triggers": {
            "within_3m": [{
                "event": "신규 설비 상업 가동",
                "verifiable_metric": "가동 개시 공시와 가동률",
                "expected_date": "2026-10",
                "impact": "high",
                "kind": "증설",
            }],
            "within_6m": [{
                "event": "수주잔고의 매출 전환",
                "verifiable_metric": "다음 정기보고서 수주잔고와 매출",
                "expected_date": "2027-01",
                "impact": "medium",
                "kind": "수주",
            }],
        },
        "price_position": {
            "verdict": "매력적",
            "reason": "최근 4개 분기 PER 12배이며 2026.2Q 9,000원에서 현재 9,500원으로 +5.6% 회복했다.",
            "price_history": "2026.1Q 10,000원에서 2026.2Q 9,000원으로 -10% 하락한 뒤 9,500원으로 +5.6% 반등했다.",
            "priced_in": ["흑전 기대의 일부는 +5.6% 반등에 반영됐다."],
            "not_priced_in": ["수주잔고 3,000억원의 설비 가동 후 매출 전환은 미반영이다."],
        },
        "scenarios": {
            "bull": {"probability": 0.25, "condition": "OPM 10% 이상", "implication": "재평가 가능"},
            "base": {"probability": 0.55, "condition": "OPM 8% 유지", "implication": "완만한 재평가"},
            "bear": {"probability": 0.20, "condition": "OPM 4% 미만", "implication": "턴어라운드 훼손"},
        },
        "risks": [{"risk": "가동 지연", "likelihood": "중간", "impact": "큼", "watch_metric": "가동 개시 공시"}],
        "next_data_to_watch": ["가동률", "수주잔고", "OPM"],
        "how_i_could_be_wrong": "낮은 기저와 가동 지연으로 흑전이 이어지지 않을 수 있다.",
    }


def _candidate(**overrides) -> EvalCandidate:
    values = dict(
        candidate_id="reference",
        provider="fixture-reference",
        model="offline",
        payload=_payload(),
        cost_usd=0.12,
    )
    values.update(overrides)
    return EvalCandidate(**values)


def _snapshot_fields(case: EvalCase | None = None, *, model: str = "offline") -> dict:
    case = case or _case()
    snapshot = snapshot_llm_request(build_llm_request(
        case.analysis_input,
        model=model,
        web_search=False,
    ))
    return {
        "request_snapshot": snapshot,
        "request_sha256": canonical_sha256(snapshot),
        "input_sha256": analysis_input_sha256(case.analysis_input),
    }


def test_hand_checked_replay_passes_all_five_dimensions():
    result = evaluate_candidate(_case(), _candidate())

    assert result.score == 100.0
    assert result.dimension_scores == {
        "schema": 25,
        "factual_grounding": 25,
        "evidence_coverage": 20,
        "trigger_timing": 15,
        "actionability": 15,
    }
    assert result.quality_pass is True
    assert result.cost_pass is True
    assert result.request_replay_exact is False
    assert result.canary_eligible is False


def test_recursive_schema_validation_catches_nested_type_breakage():
    broken = _payload()
    broken["earnings_change"] = '{"cause":">skip'

    problems = schema_problems(broken)

    assert any("$.earnings_change: expected object" in problem for problem in problems)


def test_required_nested_collections_cannot_be_empty():
    broken = _payload()
    broken["risks"] = []
    broken["price_position"]["priced_in"] = []

    result = evaluate_candidate(_case(), _candidate(payload=broken))

    assert "$.risks: empty" in result.schema_problems
    assert "$.price_position.priced_in: empty" in result.schema_problems
    assert result.quality_pass is False


def test_scenario_probabilities_must_each_be_valid_and_sum_to_one():
    broken = _payload()
    broken["scenarios"]["bull"]["probability"] = -0.2
    broken["scenarios"]["base"]["probability"] = 0.4
    broken["scenarios"]["bear"]["probability"] = 0.2

    result = evaluate_candidate(_case(), _candidate(payload=broken))

    assert any("0~1 범위 밖" in problem for problem in result.schema_problems)
    assert any("probability sum" in problem for problem in result.schema_problems)
    assert result.quality_pass is False


def test_factual_number_not_in_input_is_a_hard_failure():
    broken = _payload()
    broken["why_now"] = "매출 4,500억원으로 급증했다."

    result = evaluate_candidate(_case(), _candidate(payload=broken))

    assert result.unsupported_factual_numbers == ("4500억",)
    assert result.quality_pass is False


def test_evidence_anchor_requires_investment_dimension_and_output_paths():
    raw = _raw()["cases"][0]
    del raw["evidence_anchors"][0]["dimension"]

    with pytest.raises(ValueError, match="dimension"):
        EvalCase.from_dict(raw)

    raw = _raw()["cases"][0]
    del raw["evidence_anchors"][0]["paths"]

    with pytest.raises(ValueError, match="paths"):
        EvalCase.from_dict(raw)


def test_evidence_is_counted_only_in_its_investment_judgment_area():
    payload = _payload()
    payload["earnings_change"]["cause"] = "흑전과 OPM 8%가 실적 개선의 핵심이다."
    payload["growth_engine"]["evidence"] = "수주잔고 근거는 아직 확인이 필요하다."
    payload["risks"][0]["risk"] += " 수주잔고 3,000억원은 충분하다."

    result = evaluate_candidate(_case(), _candidate(payload=payload))

    assert "order_backlog" in result.missing_evidence_anchors
    assert result.evidence_coverage_by_dimension["sustainability"] == 0.0


def test_missing_one_investment_dimension_is_hard_failure_even_if_total_is_high():
    payload = _payload()
    payload["risks"][0]["risk"] = "원가 변동"
    payload["how_i_could_be_wrong"] = "낮은 기저로 흑전이 이어지지 않을 수 있다."

    result = evaluate_candidate(_case(), _candidate(payload=payload))

    assert result.evidence_coverage >= LLM_EVAL_MIN_EVIDENCE_COVERAGE
    assert result.evidence_coverage_by_dimension["risk"] == 0.0
    assert result.quality_pass is False


def test_casebook_coverage_refuses_single_real_case():
    raw = _raw()
    raw["synthetic"] = False

    coverage = casebook_coverage(raw)

    assert coverage["ready"] is False
    assert coverage["case_count"] == 1
    assert coverage["grade_consensus_cells"] == ["★/false"]
    assert "○/true" in coverage["missing_grade_consensus_cells"]
    assert coverage["missing_turnaround_states"] == [False]
    assert coverage["missing_investment_dimensions"] == []


def test_casebook_coverage_requires_real_cross_section_not_case_count_only():
    raw = _raw()
    raw["synthetic"] = False
    base = raw["cases"][0]
    cases = []
    variants = [
        ("star-covered", "★", True, True, "반도체"),
        ("star-uncovered", "★", False, False, "조선"),
        ("circle-covered", "○", True, False, "소프트웨어"),
        ("circle-uncovered", "○", False, True, "조선"),
    ]
    for case_id, grade, has_consensus, turnaround, industry in variants:
        item = json.loads(json.dumps(base))
        item["id"] = case_id
        item["input"]["score"]["grade"] = grade
        item["input"]["score"]["has_consensus"] = has_consensus
        item["input"]["gate"]["turnaround"] = turnaround
        item["input"]["industry"] = industry
        cases.append(item)
    raw["cases"] = cases

    coverage = casebook_coverage(raw)

    assert coverage["ready"] is True
    assert coverage["case_count"] == 4
    assert coverage["industry_count"] == 3
    assert coverage["missing_grade_consensus_cells"] == []
    assert coverage["missing_turnaround_states"] == []
    assert coverage["missing_investment_dimensions"] == []


def test_json_price_field_units_are_grounded_semantically():
    grounded = _payload()
    grounded["why_now"] += " 3개월 지수 대비 상대수익률 -8%p로 주가 반영도도 낮다."
    assert evaluate_candidate(
        _case(), _candidate(payload=grounded)
    ).unsupported_factual_numbers == ()

    fabricated = _payload()
    fabricated["why_now"] += " 3개월 지수 대비 상대수익률 -18%p다."
    assert evaluate_candidate(
        _case(), _candidate(payload=fabricated)
    ).unsupported_factual_numbers == ("-18%p",)


def test_source_numbers_allow_the_same_display_rounding_used_in_analysis():
    raw = _raw()["cases"][0]
    raw["input"]["quarters"][-1]["op"] = 64_853_000_000
    raw["input"]["quarters"][-1]["revenue_yoy"] = 43.745778166399816
    raw["input"]["price"]["relative_return_3m"] = -10.155950980262308
    case = EvalCase.from_dict(raw)
    grounded = _payload()
    grounded["why_now"] += (
        " 영업이익 649억원, 매출 YoY 43.7%, 3개월 상대수익률 -10.2%p다."
    )

    assert evaluate_candidate(
        case, _candidate(payload=grounded)
    ).unsupported_factual_numbers == ()


def test_compound_korean_money_units_are_not_split_into_false_claims():
    raw = _raw()["cases"][0]
    raw["input"]["quarters"][-1]["ttm_revenue"] = 1_851_400_000_000
    raw["input"]["price"]["current_price"] = 17_160
    case = EvalCase.from_dict(raw)
    grounded = _payload()
    grounded["why_now"] += " TTM 매출 1조8,514억원, 현재가 1만7,160원이다."

    assert evaluate_candidate(
        case, _candidate(payload=grounded)
    ).unsupported_factual_numbers == ()


def test_unsigned_percent_followed_by_decline_word_keeps_negative_direction():
    grounded = _payload()
    grounded["why_now"] += " 2026.1Q 10,000원에서 9,000원으로 10% 하락했다."

    assert evaluate_candidate(
        _case(), _candidate(payload=grounded)
    ).unsupported_factual_numbers == ()


def test_pipe_table_declared_units_ground_bare_numeric_cells():
    raw = _raw()["cases"][0]
    raw["input"]["excerpt"] += """\
\n
### 주요 제품
(단위: 억원) 사업부문 | 제품 | 매출액 | 비율
조선 | 신조선 | 4,928 | 38.77%
### 원재료
(단위: 백만원) 품목 | 매입액 | 비율(%)
강판 | 51,758 | 85.5
"""
    case = EvalCase.from_dict(raw)
    grounded = _payload()
    grounded["why_now"] += " 신조선 4,928억원, 강판 비중 85.5%다."

    assert evaluate_candidate(
        case, _candidate(payload=grounded)
    ).unsupported_factual_numbers == ()


def test_past_or_out_of_window_trigger_is_a_hard_failure():
    broken = _payload()
    broken["triggers"]["within_3m"][0]["expected_date"] = "2026-07"
    broken["triggers"]["within_6m"][0]["expected_date"] = "2027-06"

    result = evaluate_candidate(_case(), _candidate(payload=broken))

    assert len(result.trigger_timing_problems) == 2
    assert "기준일보다 과거" in result.trigger_timing_problems[0]
    assert "범위 밖" in result.trigger_timing_problems[1]
    assert result.quality_pass is False


def test_unknown_cost_is_none_not_false():
    result = evaluate_candidate(_case(), _candidate(cost_usd=None))

    assert result.quality_pass is True
    assert result.cost_pass is None
    assert result.canary_eligible is None


def test_saved_request_snapshot_not_current_builder_controls_factual_grounding(
    monkeypatch,
):
    from src.analysis import evaluation

    broken = _payload()
    broken["why_now"] = "매출 4,500억원으로 급증했다."
    monkeypatch.setattr(
        evaluation,
        "build_user_message",
        lambda _data: "최신 builder에는 매출 4,500억원이 추가됐다.",
    )

    result = evaluate_candidate(
        _case(),
        _candidate(payload=broken, **_snapshot_fields()),
    )

    assert result.request_replay_exact is True
    assert result.unsupported_factual_numbers == ("4500억",)


def test_tampered_request_snapshot_blocks_canary_eligibility():
    fields = _snapshot_fields()
    fields["request_snapshot"]["request"]["user_message"] += "\n변조"

    result = evaluate_candidate(_case(), _candidate(**fields))

    assert result.request_replay_exact is False
    assert any("request_sha256 mismatch" in item for item in result.request_problems)
    assert result.canary_eligible is False


def test_saved_schema_not_current_schema_controls_validation():
    fields = _snapshot_fields()
    schema = fields["request_snapshot"]["request"]["schema"]
    schema["required"].append("snapshot_only_required_field")
    fields["request_sha256"] = canonical_sha256(fields["request_snapshot"])

    result = evaluate_candidate(_case(), _candidate(**fields))

    assert result.request_replay_exact is True
    assert "$.snapshot_only_required_field: missing" in result.schema_problems


def test_different_saved_prompt_contracts_cannot_be_compared():
    raw = _raw()
    raw["synthetic"] = False
    anthropic = _snapshot_fields(model="a")
    openai = _snapshot_fields(model="o")
    openai["request_snapshot"]["request"]["user_message"] += "\n다른 시험지"
    openai["request_sha256"] = canonical_sha256(openai["request_snapshot"])
    raw["cases"][0]["candidates"] = [
        {"id": "a", "provider": "anthropic", "model": "a", "cost_usd": 0.12,
         "payload": _payload(), **anthropic},
        {"id": "o", "provider": "openai", "model": "o", "cost_usd": 0.12,
         "payload": _payload(), **openai},
    ]

    report = evaluate_suite(raw)

    assert all(
        result["request_replay_exact"]
        for result in report["cases"][0]["results"]
    )
    assert report["comparison_ready"] is False
    assert report["winner"] is None


def test_synthetic_or_single_provider_suite_never_declares_a_winner():
    raw = _raw()

    report = evaluate_suite(raw)

    assert report["synthetic"] is True
    assert report["comparison_ready"] is False
    assert report["winner"] is None
    assert report["cases"][0]["results"][0]["score"] == 100.0
    assert report["cases"][0]["results"][0]["cost_pass"] is None


def test_real_suite_requires_two_providers_before_comparing():
    raw = _raw()
    raw["synthetic"] = False
    raw["cases"][0]["candidates"] = [
        {"id": "a", "provider": "anthropic", "model": "a", "cost_usd": 0.12,
         "payload": _payload(), **_snapshot_fields(model="a")},
        {"id": "o", "provider": "openai", "model": "o", "cost_usd": 0.12,
         "payload": _payload(), **_snapshot_fields(model="o")},
    ]

    report = evaluate_suite(raw)

    assert report["comparison_ready"] is True
    assert report["provider_average_scores"] == {"anthropic": 100.0, "openai": 100.0}
    assert report["winner"] is None  # 동점인데 임의로 하나를 고르면 안 된다.


def test_completed_canary_result_is_injected_only_into_exact_replay():
    raw = _raw()
    raw["synthetic"] = False
    result = {
        "status": "completed",
        "input": raw["cases"][0]["input"],
        "candidate": {
            "provider": "openai",
            "model": "gpt-5.6-terra",
            "cost_usd": 0.09,
            "payload": _payload(),
            **_snapshot_fields(model="gpt-5.6-terra"),
        },
    }

    injected = suite_with_canary_result(raw, result, candidate_id="attempt-3")

    assert injected["cases"][0]["candidates"][0]["id"] == "attempt-3"
    assert injected["cases"][0]["candidates"][0]["cost_usd"] == 0.09
    assert raw["cases"][0]["candidates"][0]["id"] != "attempt-3"


def test_multiple_provider_results_for_same_case_are_not_overwritten():
    raw = _raw()
    raw["synthetic"] = False
    base = {
        "status": "completed",
        "input": raw["cases"][0]["input"],
        "candidate": {
            "provider": "openai",
            "model": "gpt-5.6-terra",
            "cost_usd": 0.09,
            "payload": _payload(),
            **_snapshot_fields(model="gpt-5.6-terra"),
        },
    }
    first = suite_with_canary_result(raw, base, candidate_id="openai")
    second_result = json.loads(json.dumps(base))
    second_result["candidate"].update(
        {
            "provider": "anthropic",
            "model": "claude-sonnet-5",
            **_snapshot_fields(model="claude-sonnet-5"),
        }
    )

    injected = suite_with_canary_result(
        first,
        second_result,
        candidate_id="anthropic",
    )

    candidates = injected["cases"][0]["candidates"]
    assert [item["id"] for item in candidates] == ["openai", "anthropic"]
    assert [item["provider"] for item in candidates] == ["openai", "anthropic"]


def test_paid_grounding_failure_can_be_replayed_but_is_not_canary_eligible():
    raw = _raw()
    raw["synthetic"] = False
    result = {
        "status": "failed",
        "input": raw["cases"][0]["input"],
        "candidate": {
            "provider": "openai",
            "model": "gpt-5.6-terra",
            "cost_usd": 0.09,
            "payload": _payload(),
            **_snapshot_fields(model="gpt-5.6-terra"),
        },
    }

    injected = suite_with_canary_result(raw, result, candidate_id="paid-failure")
    report = evaluate_suite(injected)
    evaluated = report["cases"][0]["results"][0]

    assert evaluated["execution_status"] == "failed"
    assert evaluated["quality_pass"] is True
    assert evaluated["canary_eligible"] is False


def test_canary_result_allows_equivalent_json_number_representation():
    raw = _raw()
    result_input = json.loads(json.dumps(raw["cases"][0]["input"]))
    result_input["price"]["current_price"] = float(
        result_input["price"]["current_price"]
    )
    result = {
        "status": "completed",
        "input": result_input,
        "candidate": {
            "provider": "openai",
            "model": "gpt-5.6-terra",
            "payload": _payload(),
        },
    }

    injected = suite_with_canary_result(raw, result, candidate_id="attempt-3")

    assert isinstance(injected["cases"][0]["input"]["price"]["current_price"], float)


def test_canary_result_with_different_replay_is_rejected():
    raw = _raw()
    result = {
        "status": "completed",
        "input": {**raw["cases"][0]["input"], "as_of": "2026-08-28"},
        "candidate": {
            "provider": "openai",
            "model": "gpt-5.6-terra",
            "payload": _payload(),
        },
    }

    with pytest.raises(ValueError, match="replay 입력이 다르다"):
        suite_with_canary_result(raw, result, candidate_id="attempt-3")


def test_provider_case_sets_must_match_before_averaging():
    raw = _raw()
    raw["synthetic"] = False
    second = json.loads(json.dumps(raw["cases"][0]))
    second["id"] = "second-case"
    raw["cases"] = [raw["cases"][0], second]
    raw["cases"][0]["candidates"] = [
        {"id": "a1", "provider": "anthropic", "model": "a", "payload": _payload()},
        {"id": "o1", "provider": "openai", "model": "o", "payload": _payload()},
    ]
    raw["cases"][1]["candidates"] = [
        {"id": "a2", "provider": "anthropic", "model": "a", "payload": _payload()},
        {"id": "g2", "provider": "gemini", "model": "g", "payload": _payload()},
    ]

    report = evaluate_suite(raw)

    assert report["comparison_ready"] is False
    assert report["winner"] is None


def test_eval_weights_sum_to_one_hundred():
    assert sum(LLM_EVAL_WEIGHTS.values()) == 100


def test_eval_thresholds_match_prd():
    prd = (Path(__file__).resolve().parents[1] / "docs" / "PRD.md").read_text(encoding="utf-8")
    for name, value in (
        ("LLM_EVAL_MIN_SCORE", LLM_EVAL_MIN_SCORE),
        ("LLM_EVAL_MIN_EVIDENCE_COVERAGE", LLM_EVAL_MIN_EVIDENCE_COVERAGE),
        (
            "LLM_EVAL_MIN_DIMENSION_EVIDENCE_COVERAGE",
            LLM_EVAL_MIN_DIMENSION_EVIDENCE_COVERAGE,
        ),
        ("LLM_CANARY_MAX_COST_USD", LLM_CANARY_MAX_COST_USD),
        ("LLM_CANARY_MAX_OUTPUT_TOKENS", LLM_CANARY_MAX_OUTPUT_TOKENS),
    ):
        found = re.findall(rf"^{name}\s*=\s*([0-9.]+)", prd, re.M)
        assert found, f"PRD에 {name}가 없다"
        assert all(float(item) == float(value) for item in found)
