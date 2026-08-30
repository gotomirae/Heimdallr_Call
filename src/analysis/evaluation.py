# PRD Ref: §7.2, §7.4 · ADR 3, 9 · traps.md T121
"""저장된 LLM 결과를 같은 replay 입력으로 비교하는 순수 offline eval.

외부 API·DB·Provider SDK를 호출하지 않는다. 후보 payload와 실제 usage/cost를 JSON으로
받아 구조, 입력 숫자 근거, 핵심 근거 커버리지, 트리거 시점, 검증 가능성을 결정론적으로
채점한다. 실제 Provider 출력이 없으면 우열을 만들지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from src.analysis.analyze import AnalysisInput, build_user_message
from src.analysis.numeric_grounding import (
    NUMBER_WITH_UNIT_RE,
    strings_in,
    unsupported_factual_numbers,
)
from src.analysis.prompts import ANALYSIS_SCHEMA
from src.analysis.schema_validation import schema_problems
from src.config.constants import (
    LLM_CANARY_MAX_COST_USD,
    LLM_EVAL_CASEBOOK_MIN_CASES,
    LLM_EVAL_CASEBOOK_MIN_INDUSTRIES,
    LLM_EVAL_INVESTMENT_DIMENSIONS,
    LLM_EVAL_MIN_DIMENSION_EVIDENCE_COVERAGE,
    LLM_EVAL_MIN_EVIDENCE_COVERAGE,
    LLM_EVAL_MIN_SCORE,
    LLM_EVAL_WEIGHTS,
)
from src.llm.request_snapshot import (
    REQUEST_SNAPSHOT_VERSION,
    analysis_input_sha256,
    canonical_sha256,
)


_EXPECTED_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
_ACTIONABLE_METRIC = re.compile(
    r"공시|계약|가동|출시|인증|승인|수주|매출|영업이익|OPM|"
    r"가동률|점유율|원가율|수주잔고|양산|고객사"
)
@dataclass(frozen=True)
class EvidenceAnchor:
    """후보가 반드시 다뤄야 할 replay 입력의 핵심 사실."""

    anchor_id: str
    dimension: str
    aliases: tuple[str, ...]
    paths: tuple[str, ...]


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    source: str
    analysis_input: AnalysisInput
    evidence_anchors: tuple[EvidenceAnchor, ...]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "EvalCase":
        anchors = tuple(
            EvidenceAnchor(
                anchor_id=str(item["id"]),
                dimension=str(item.get("dimension") or ""),
                aliases=tuple(str(alias) for alias in item["aliases"]),
                paths=tuple(str(path) for path in item.get("paths") or []),
            )
            for item in raw.get("evidence_anchors", [])
        )
        if not anchors:
            raise ValueError("evidence_anchors가 비어 있다 — 근거 없는 평가는 허용하지 않는다")
        if any(not anchor.aliases for anchor in anchors):
            raise ValueError("evidence anchor aliases가 비어 있다 — 영원히 미검출되는 기준이다")
        invalid_dimensions = [
            anchor.anchor_id
            for anchor in anchors
            if anchor.dimension not in LLM_EVAL_INVESTMENT_DIMENSIONS
        ]
        if invalid_dimensions:
            raise ValueError(
                "evidence anchor dimension이 없거나 유효하지 않다: "
                + ", ".join(invalid_dimensions)
            )
        if any(not anchor.paths for anchor in anchors):
            raise ValueError("evidence anchor paths가 비어 있다 — 엉뚱한 영역의 언급을 셀 수 있다")
        data = AnalysisInput(**raw["input"])
        if not data.as_of:
            raise ValueError("input.as_of가 없다 — 트리거 시점을 평가할 수 없다")
        return cls(
            case_id=str(raw["id"]),
            source=str(raw.get("source") or "unknown"),
            analysis_input=data,
            evidence_anchors=anchors,
        )


@dataclass(frozen=True)
class EvalCandidate:
    candidate_id: str
    provider: str
    model: str
    payload: dict[str, Any]
    cost_usd: float | None = None
    request_snapshot: Any = None
    request_sha256: str | None = None
    input_sha256: str | None = None
    execution_status: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "EvalCandidate":
        cost = raw.get("cost_usd")
        if not isinstance(raw.get("payload"), dict):
            raise ValueError("candidate.payload는 object여야 한다")
        return cls(
            candidate_id=str(raw["id"]),
            provider=str(raw["provider"]),
            model=str(raw["model"]),
            payload=raw["payload"],
            cost_usd=float(cost) if cost is not None else None,
            request_snapshot=raw.get("request_snapshot"),
            request_sha256=raw.get("request_sha256"),
            input_sha256=raw.get("input_sha256"),
            execution_status=raw.get("execution_status"),
        )


@dataclass(frozen=True)
class EvalResult:
    case_id: str
    candidate_id: str
    provider: str
    model: str
    execution_status: str | None
    score: float
    dimension_scores: dict[str, float]
    quality_pass: bool
    cost_pass: bool | None
    canary_eligible: bool | None
    evidence_coverage: float
    evidence_coverage_by_dimension: dict[str, float]
    schema_problems: tuple[str, ...]
    unsupported_factual_numbers: tuple[str, ...]
    trigger_timing_problems: tuple[str, ...]
    unactionable_triggers: tuple[str, ...]
    missing_evidence_anchors: tuple[str, ...]
    cost_usd: float | None
    request_replay_exact: bool
    request_problems: tuple[str, ...]
    comparison_contract_sha256: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _compact(text: str) -> str:
    return re.sub(r"[\s,]", "", text).replace("억원", "억").replace("조원", "조")


def _value_at_path(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def missing_evidence_anchors(case: EvalCase, payload: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    for anchor in case.evidence_anchors:
        scoped_text = _compact("\n".join(
            text
            for path in anchor.paths
            for text in strings_in(_value_at_path(payload, path))
        ))
        if not any(_compact(alias) in scoped_text for alias in anchor.aliases):
            missing.append(anchor.anchor_id)
    return missing


def _coverage_by_dimension(
    case: EvalCase,
    missing: list[str],
) -> dict[str, float]:
    missing_ids = set(missing)
    coverage: dict[str, float] = {}
    for dimension in LLM_EVAL_INVESTMENT_DIMENSIONS:
        anchors = [
            anchor for anchor in case.evidence_anchors if anchor.dimension == dimension
        ]
        coverage[dimension] = round(
            sum(anchor.anchor_id not in missing_ids for anchor in anchors) / len(anchors),
            4,
        ) if anchors else 0.0
    return coverage


def _month_index(value: str) -> int | None:
    match = _EXPECTED_MONTH.fullmatch(value)
    if not match:
        return None
    return int(match.group(1)) * 12 + int(match.group(2)) - 1


def _triggers(payload: dict[str, Any]) -> list[tuple[str, int, dict[str, Any]]]:
    root = payload.get("triggers")
    if not isinstance(root, dict):
        return []
    out: list[tuple[str, int, dict[str, Any]]] = []
    for window, months in (("within_3m", 3), ("within_6m", 6)):
        rows = root.get(window)
        if isinstance(rows, list):
            out.extend((window, months, row) for row in rows if isinstance(row, dict))
    return out


def trigger_timing_problems(case: EvalCase, payload: dict[str, Any]) -> list[str]:
    as_of_month = _month_index(case.analysis_input.as_of[:7])
    if as_of_month is None:
        return [f"input.as_of={case.analysis_input.as_of!r}: YYYY-MM-DD가 아니다"]
    problems: list[str] = []
    for window, limit, trigger in _triggers(payload):
        expected = trigger.get("expected_date")
        month = _month_index(expected) if isinstance(expected, str) else None
        label = f"{window}:{trigger.get('event', '—')}"
        if month is None:
            problems.append(f"{label}: expected_date={expected!r} (YYYY-MM 필요)")
            continue
        delta = month - as_of_month
        if delta < 0:
            problems.append(f"{label}: {expected}는 기준일보다 과거")
        elif delta > limit:
            problems.append(f"{label}: {expected}는 {limit}개월 범위 밖(+{delta}개월)")
    return problems


def unactionable_triggers(payload: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for window, _limit, trigger in _triggers(payload):
        event = str(trigger.get("event") or "").strip()
        metric = str(trigger.get("verifiable_metric") or "").strip()
        label = f"{window}:{event or '—'}"
        if not event or event in {"실적 개선", "실적 개선 기대", "주가 상승 기대"}:
            problems.append(f"{label}: 사건이 아니라 일반 기대")
        elif not metric or not (
            _ACTIONABLE_METRIC.search(metric) or NUMBER_WITH_UNIT_RE.search(metric)
        ):
            problems.append(f"{label}: 검증 가능한 숫자·공시·운영 지표가 없음")
    return problems


def _scenario_probability_problems(payload: dict[str, Any]) -> list[str]:
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, dict):
        return []  # 타입 문제는 schema 검사가 이미 구체적으로 남긴다.
    values: list[float] = []
    problems: list[str] = []
    for name in ("bull", "base", "bear"):
        node = scenarios.get(name)
        probability = node.get("probability") if isinstance(node, dict) else None
        if isinstance(probability, (int, float)) and not isinstance(probability, bool):
            value = float(probability)
            values.append(value)
            if not 0.0 <= value <= 1.0:
                problems.append(f"$.scenarios.{name}.probability={value}: 0~1 범위 밖")
    if len(values) == 3 and not 0.999 <= sum(values) <= 1.001:
        problems.append(f"$.scenarios: probability sum={sum(values):.3f}, expected 1.0")
    return problems


def _saved_request_contract(
    case: EvalCase,
    candidate: EvalCandidate,
) -> tuple[str, dict[str, Any], list[str], str | None]:
    """실제 호출 snapshot을 검증하고 평가에 쓸 message/schema를 반환한다."""
    problems: list[str] = []
    snapshot = candidate.request_snapshot
    if not isinstance(snapshot, dict):
        return (
            build_user_message(case.analysis_input),
            ANALYSIS_SCHEMA,
            ["request snapshot missing — current builder fallback; exact replay unavailable"],
            None,
        )
    if snapshot.get("version") != REQUEST_SNAPSHOT_VERSION:
        problems.append(
            f"request snapshot version={snapshot.get('version')!r}, "
            f"expected {REQUEST_SNAPSHOT_VERSION}"
        )
    request = snapshot.get("request")
    if not isinstance(request, dict):
        return (
            build_user_message(case.analysis_input),
            ANALYSIS_SCHEMA,
            problems + ["request snapshot.request is not an object"],
            None,
        )

    actual_request_sha256 = canonical_sha256(snapshot)
    if candidate.request_sha256 != actual_request_sha256:
        problems.append(
            "request_sha256 mismatch: "
            f"saved={candidate.request_sha256!r}, actual={actual_request_sha256}"
        )
    actual_input_sha256 = analysis_input_sha256(case.analysis_input)
    if candidate.input_sha256 != actual_input_sha256:
        problems.append(
            "input_sha256 mismatch: "
            f"saved={candidate.input_sha256!r}, actual={actual_input_sha256}"
        )
    if request.get("model") != candidate.model:
        problems.append(
            f"request model={request.get('model')!r} != candidate model={candidate.model!r}"
        )

    user_message = request.get("user_message")
    schema = request.get("schema")
    if not isinstance(user_message, str):
        problems.append("request user_message is not a string")
        user_message = build_user_message(case.analysis_input)
    if not isinstance(schema, dict):
        problems.append("request schema is not an object")
        schema = ANALYSIS_SCHEMA

    comparable_request = dict(request)
    comparable_request.pop("model", None)
    comparison_hash = canonical_sha256({
        "version": snapshot.get("version"),
        "request": comparable_request,
    })
    return user_message, schema, problems, comparison_hash


def evaluate_candidate(case: EvalCase, candidate: EvalCandidate) -> EvalResult:
    user_message, saved_schema, request_problems, comparison_hash = (
        _saved_request_contract(case, candidate)
    )
    schema = schema_problems(
        candidate.payload,
        schema=saved_schema,
        root=saved_schema,
    ) + _scenario_probability_problems(candidate.payload)
    unsupported = unsupported_factual_numbers(
        case.analysis_input,
        candidate.payload,
        user_message=user_message,
    )
    timing = trigger_timing_problems(case, candidate.payload)
    unactionable = unactionable_triggers(candidate.payload)
    missing = missing_evidence_anchors(case, candidate.payload)
    dimension_coverage = _coverage_by_dimension(case, missing)

    anchor_total = len(case.evidence_anchors)
    coverage = (anchor_total - len(missing)) / anchor_total
    trigger_total = len(_triggers(candidate.payload))
    timing_valid = max(trigger_total - len(timing), 0)
    actionable = max(trigger_total - len(unactionable), 0)

    dimensions = {
        "schema": max(0.0, LLM_EVAL_WEIGHTS["schema"] - 5.0 * len(schema)),
        "factual_grounding": max(
            0.0, LLM_EVAL_WEIGHTS["factual_grounding"] - 5.0 * len(unsupported)
        ),
        "evidence_coverage": LLM_EVAL_WEIGHTS["evidence_coverage"] * coverage,
        "trigger_timing": (
            LLM_EVAL_WEIGHTS["trigger_timing"] * timing_valid / trigger_total
            if trigger_total else 0.0
        ),
        "actionability": (
            LLM_EVAL_WEIGHTS["actionability"] * actionable / trigger_total
            if trigger_total else 0.0
        ),
    }
    dimensions = {key: round(value, 2) for key, value in dimensions.items()}
    score = round(sum(dimensions.values()), 2)
    quality_pass = (
        score >= LLM_EVAL_MIN_SCORE
        and not schema
        and not unsupported
        and not timing
        and coverage >= LLM_EVAL_MIN_EVIDENCE_COVERAGE
        and all(
            value >= LLM_EVAL_MIN_DIMENSION_EVIDENCE_COVERAGE
            for value in dimension_coverage.values()
        )
    )
    cost_pass = (
        None
        if candidate.cost_usd is None
        else candidate.cost_usd <= LLM_CANARY_MAX_COST_USD
    )
    request_replay_exact = not request_problems
    canary_eligible = (
        None
        if cost_pass is None
        else (
            quality_pass
            and cost_pass
            and request_replay_exact
            and candidate.execution_status in {None, "completed"}
        )
    )
    return EvalResult(
        case_id=case.case_id,
        candidate_id=candidate.candidate_id,
        provider=candidate.provider,
        model=candidate.model,
        execution_status=candidate.execution_status,
        score=score,
        dimension_scores=dimensions,
        quality_pass=quality_pass,
        cost_pass=cost_pass,
        canary_eligible=canary_eligible,
        evidence_coverage=round(coverage, 4),
        evidence_coverage_by_dimension=dimension_coverage,
        schema_problems=tuple(schema),
        unsupported_factual_numbers=tuple(unsupported),
        trigger_timing_problems=tuple(timing),
        unactionable_triggers=tuple(unactionable),
        missing_evidence_anchors=tuple(missing),
        cost_usd=candidate.cost_usd,
        request_replay_exact=request_replay_exact,
        request_problems=tuple(request_problems),
        comparison_contract_sha256=comparison_hash,
    )


def casebook_coverage(raw: dict[str, Any]) -> dict[str, Any]:
    """실제 투자판단 사례집이 목표 횡단면을 대표하는지 결정론적으로 점검한다."""
    cases = [EvalCase.from_dict(item) for item in raw.get("cases", [])]
    grades: set[str] = set()
    consensus_states: set[bool] = set()
    turnaround_states: set[bool] = set()
    industries: set[str] = set()
    cells: set[str] = set()
    invalid_cases: list[str] = []
    cases_missing_dimensions: dict[str, list[str]] = {}

    for case in cases:
        score = case.analysis_input.score
        gate = case.analysis_input.gate
        grade = score.get("grade") if isinstance(score, dict) else None
        has_consensus = score.get("has_consensus") if isinstance(score, dict) else None
        turnaround = gate.get("turnaround") if isinstance(gate, dict) else None
        gate_passed = gate.get("passed") if isinstance(gate, dict) else None
        industry = str(case.analysis_input.industry or "").strip()

        if grade in {"★", "○"}:
            grades.add(grade)
        if isinstance(has_consensus, bool):
            consensus_states.add(has_consensus)
        if isinstance(turnaround, bool):
            turnaround_states.add(turnaround)
        if industry:
            industries.add(industry)
        if grade in {"★", "○"} and isinstance(has_consensus, bool):
            cells.add(f"{grade}/{str(has_consensus).lower()}")
        if (
            grade not in {"★", "○"}
            or not isinstance(has_consensus, bool)
            or not isinstance(turnaround, bool)
            or gate_passed is not True
            or not industry
        ):
            invalid_cases.append(case.case_id)

        present_dimensions = {anchor.dimension for anchor in case.evidence_anchors}
        missing_dimensions = [
            dimension
            for dimension in LLM_EVAL_INVESTMENT_DIMENSIONS
            if dimension not in present_dimensions
        ]
        if missing_dimensions:
            cases_missing_dimensions[case.case_id] = missing_dimensions

    required_cells = {
        f"{grade}/{str(has_consensus).lower()}"
        for grade in ("★", "○")
        for has_consensus in (True, False)
    }
    missing_dimensions = sorted({
        dimension
        for values in cases_missing_dimensions.values()
        for dimension in values
    })
    ready = (
        not bool(raw.get("synthetic", False))
        and len(cases) >= LLM_EVAL_CASEBOOK_MIN_CASES
        and len(industries) >= LLM_EVAL_CASEBOOK_MIN_INDUSTRIES
        and cells == required_cells
        and turnaround_states == {True, False}
        and not invalid_cases
        and not cases_missing_dimensions
    )
    return {
        "ready": ready,
        "case_count": len(cases),
        "minimum_case_count": LLM_EVAL_CASEBOOK_MIN_CASES,
        "industry_count": len(industries),
        "minimum_industry_count": LLM_EVAL_CASEBOOK_MIN_INDUSTRIES,
        "industries": sorted(industries),
        "grades": sorted(grades),
        "consensus_states": sorted(consensus_states),
        "turnaround_states": sorted(turnaround_states),
        "grade_consensus_cells": sorted(cells),
        "missing_grade_consensus_cells": sorted(required_cells - cells),
        "missing_turnaround_states": sorted({True, False} - turnaround_states),
        "missing_investment_dimensions": missing_dimensions,
        "cases_missing_investment_dimensions": cases_missing_dimensions,
        "invalid_cases": invalid_cases,
    }


def evaluate_suite(raw: dict[str, Any]) -> dict[str, Any]:
    """JSON suite를 평가한다. synthetic suite는 Provider 우열을 절대 선언하지 않는다."""
    synthetic = bool(raw.get("synthetic", False))
    case_outputs: list[dict[str, Any]] = []
    provider_scores: dict[str, list[float]] = {}
    comparison_ready = not synthetic and bool(raw.get("cases"))
    expected_providers: set[str] | None = None

    for raw_case in raw.get("cases", []):
        case = EvalCase.from_dict(raw_case)
        candidates = [EvalCandidate.from_dict(item) for item in raw_case.get("candidates", [])]
        ids = [candidate.candidate_id for candidate in candidates]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{case.case_id}: candidate id가 중복됐다")
        provider_names = [candidate.provider for candidate in candidates]
        providers = set(provider_names)
        # Provider마다 사례당 정확히 한 결과가 있어야 평균을 비교할 수 있다. 한 Provider만
        # 쉬운 사례가 빠지면 평균이 높아져도 오류 없이 그럴듯한 우승자가 생긴다.
        if len(providers) != len(provider_names) or len(providers) < 2:
            comparison_ready = False
        if expected_providers is None:
            expected_providers = providers
        elif providers != expected_providers:
            comparison_ready = False
        results = [evaluate_candidate(case, candidate) for candidate in candidates]
        if any(
            result.execution_status not in {None, "completed"}
            for result in results
        ):
            comparison_ready = False
        if not all(result.request_replay_exact for result in results):
            comparison_ready = False
        comparison_hashes = {
            result.comparison_contract_sha256
            for result in results
            if result.comparison_contract_sha256 is not None
        }
        if len(comparison_hashes) != 1:
            comparison_ready = False
        for result in results:
            provider_scores.setdefault(result.provider, []).append(result.score)
        case_outputs.append(
            {
                "case_id": case.case_id,
                "source": case.source,
                "candidate_count": len(results),
                "results": [result.as_dict() for result in results],
            }
        )

    summary = {
        provider: round(sum(scores) / len(scores), 2)
        for provider, scores in sorted(provider_scores.items())
    }
    winner: str | None = None
    if comparison_ready and summary:
        top = max(summary.values())
        leaders = [provider for provider, score in summary.items() if score == top]
        winner = leaders[0] if len(leaders) == 1 else None
    return {
        "suite": str(raw.get("suite") or "unnamed"),
        "synthetic": synthetic,
        "comparison_ready": comparison_ready,
        "provider_average_scores": summary,
        "winner": winner,
        "criteria": {
            "weights": LLM_EVAL_WEIGHTS,
            "min_score": LLM_EVAL_MIN_SCORE,
            "min_evidence_coverage": LLM_EVAL_MIN_EVIDENCE_COVERAGE,
            "min_dimension_evidence_coverage": (
                LLM_EVAL_MIN_DIMENSION_EVIDENCE_COVERAGE
            ),
            "canary_max_cost_usd": LLM_CANARY_MAX_COST_USD,
        },
        "casebook_coverage": casebook_coverage(raw),
        "cases": case_outputs,
    }
