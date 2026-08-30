# PRD Ref: §7.4 · ADR 9 · traps.md T84, T106
"""외부 저장 없이 승인된 Provider 단건 canary를 실행하는 경계.

DB 비용 로그를 쓰는 운영 `analyze()`와 의도적으로 분리한다. 호출 전 공식 token-count와
최악비용을 검사하고, 한 번 생성한 뒤 실제 usage 비용만 로컬 결과로 반환한다.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace

from src.analysis.analyze import (
    AnalysisError,
    AnalysisInput,
    AnalysisResult,
    analysis_result_from_response,
    build_llm_request,
    validate_payload,
)
from src.config.constants import (
    LLM_CANARY_MAX_COST_USD,
    LLM_CANARY_MAX_OUTPUT_TOKENS,
    LLM_INPUT_TOKEN_BUDGET,
)
from src.llm.provider import LLMRequest, NormalizedUsage, StructuredLLMProvider
from src.llm.request_snapshot import (
    analysis_input_sha256,
    canonical_sha256,
    snapshot_llm_request,
)
from src.utils.cost_guard import (
    compute_cost_usd,
    estimate_worst_case_cost_usd,
    get_pricing,
)


class CanaryPreflightError(AnalysisError):
    """유료 생성 전에 입력·가격·최대비용 조건이 맞지 않아 차단됨."""


CANARY_PLAN_VERSION = 2


def _provider_name_of(model: str) -> str:
    if model.startswith("claude-"):
        return "anthropic"
    if model.startswith("gpt-"):
        return "openai"
    return "unknown"


@dataclass(frozen=True)
class CanaryPlan:
    """외부 호출 없이 만든 승인 계약. payload의 hash가 실행 허가 단위다."""

    request: LLMRequest
    payload: dict
    plan_sha256: str


def build_canary_plan(
    data: AnalysisInput,
    *,
    model: str,
    token_budget: int = LLM_INPUT_TOKEN_BUDGET,
    max_output_tokens: int = LLM_CANARY_MAX_OUTPUT_TOKENS,
    max_cost_usd: float = LLM_CANARY_MAX_COST_USD,
    effort: str | None = None,
) -> CanaryPlan:
    """요청·가격·하드캡을 하나의 offline 승인 hash로 묶는다.

    정확한 입력 토큰 수는 Provider token-count 결과만 신뢰하므로 여기서는 ``None``이다.
    대신 입력 예산 전체가 가장 비싼 분류여도 넘지 않는 계획만 만든다.
    """
    rates = get_pricing(model)
    request = build_llm_request(
        data,
        model=model,
        web_search=False,
        max_output_tokens=max_output_tokens,
        # 실제 3회 품질 검증을 운영 요청과 격리한다. 성공 근거 전에는 analyze() 기본값을
        # 바꾸지 않는다.
        factual_references=True,
    )
    if effort is not None:
        request = replace(request, effort=effort)
    request_snapshot = snapshot_llm_request(request)
    request_sha256 = canonical_sha256(request_snapshot)
    input_sha256 = analysis_input_sha256(data)
    budget_worst = estimate_worst_case_cost_usd(
        model,
        input_tokens=token_budget,
        max_output_tokens=max_output_tokens,
    )
    if budget_worst > max_cost_usd:
        raise CanaryPreflightError(
            f"{data.code}: 계획 최악비용 ${budget_worst:.6f}가 "
            f"하드캡 ${max_cost_usd:.6f}를 넘었다; 외부 호출 0회"
        )
    payload = {
        "version": CANARY_PLAN_VERSION,
        "provider": _provider_name_of(model),
        "code": data.code,
        "fiscal_year": data.fiscal_year,
        "fiscal_quarter": data.fiscal_quarter,
        "model": model,
        "request_snapshot": request_snapshot,
        "request_sha256": request_sha256,
        "input_sha256": input_sha256,
        "pricing_per_mtok": asdict(rates),
        "limits": {
            "input_token_budget": token_budget,
            "max_output_tokens": max_output_tokens,
            "max_cost_usd": max_cost_usd,
            "budget_worst_case_cost_usd": budget_worst,
        },
        "measurements": {
            "user_message_chars": len(request.user_message),
            "counted_input_tokens": None,
            "note": "exact token count requires the provider token-count endpoint",
        },
        "planned_external_calls": {
            "input_token_count": 1,
            "paid_generation": 1,
            "sdk_retries": 0,
        },
        "external_calls_executed": 0,
    }
    return CanaryPlan(
        request=request,
        payload=payload,
        plan_sha256=canonical_sha256(payload),
    )


class CanaryProviderError(AnalysisError):
    """Provider HTTP 오류. 이미 끝낸 preflight 수치를 보존한다."""

    def __init__(
        self,
        *,
        code: str,
        model: str,
        counted_input_tokens: int,
        worst_case_cost_usd: float,
        request_snapshot: dict,
        request_sha256: str,
        input_sha256: str,
        plan_sha256: str,
        error: Exception,
    ):
        message = str(error)
        # 예외 문자열이 요청 설정을 포함하더라도 키를 결과 파일에 남기지 않는다.
        message = re.sub(r"sk-[A-Za-z0-9_-]{20,}", "[REDACTED_OPENAI_KEY]", message)
        message = re.sub(r"sb_secret_[A-Za-z0-9_-]{10,}", "[REDACTED_SUPABASE_KEY]", message)
        self.model = model
        self.counted_input_tokens = counted_input_tokens
        self.worst_case_cost_usd = worst_case_cost_usd
        self.request_snapshot = request_snapshot
        self.request_sha256 = request_sha256
        self.input_sha256 = input_sha256
        self.plan_sha256 = plan_sha256
        self.provider_error_type = type(error).__name__
        self.provider_error_message = message
        super().__init__(
            f"{code}: Provider 생성 실패({self.provider_error_type}): {message}"
        )


@dataclass(frozen=True)
class CanaryFailure:
    error: str
    response_model: str
    response_id: str | None
    actual_cost_usd: float
    counted_input_tokens: int
    worst_case_cost_usd: float
    usage: NormalizedUsage
    payload: dict | None
    request_snapshot: dict
    request_sha256: str
    input_sha256: str
    plan_sha256: str


class CanaryExecutionError(AnalysisError):
    """유료 생성 뒤 실패. 비용·usage·원 payload를 잃지 않는다."""

    def __init__(self, failure: CanaryFailure):
        super().__init__(failure.error)
        self.failure = failure


@dataclass(frozen=True)
class CanaryResult:
    analysis: AnalysisResult
    counted_input_tokens: int
    worst_case_cost_usd: float
    response_id: str | None
    request_snapshot: dict
    request_sha256: str
    input_sha256: str
    plan_sha256: str


def run_canary(
    data: AnalysisInput,
    *,
    provider: StructuredLLMProvider,
    model: str,
    token_budget: int = LLM_INPUT_TOKEN_BUDGET,
    max_output_tokens: int = LLM_CANARY_MAX_OUTPUT_TOKENS,
    max_cost_usd: float = LLM_CANARY_MAX_COST_USD,
    approved_plan_sha256: str,
    effort: str | None = None,
) -> CanaryResult:
    """token-count 1회 + 생성 1회. DB·텔레그램·검색·자동 폴백은 사용하지 않는다."""
    plan = build_canary_plan(
        data,
        model=model,
        token_budget=token_budget,
        max_output_tokens=max_output_tokens,
        max_cost_usd=max_cost_usd,
        effort=effort,
    )
    if approved_plan_sha256 != plan.plan_sha256:
        raise CanaryPreflightError(
            f"{data.code}: 승인 plan_sha256 불일치; 외부 호출 0회 "
            f"(approved={approved_plan_sha256}, current={plan.plan_sha256})"
        )
    planned_provider = plan.payload["provider"]
    if provider.name != planned_provider:
        raise CanaryPreflightError(
            f"{data.code}: 계획 Provider {planned_provider}와 실행 Provider "
            f"{provider.name} 불일치; 외부 호출 0회"
        )
    request = plan.request
    request_snapshot = plan.payload["request_snapshot"]
    request_sha256 = plan.payload["request_sha256"]
    input_sha256 = plan.payload["input_sha256"]
    counted = provider.count_input_tokens(request)
    if counted > token_budget:
        raise CanaryPreflightError(
            f"{data.code}: 입력 {counted:,}토큰이 상한 {token_budget:,}을 넘었다; 생성 0회"
        )

    worst = estimate_worst_case_cost_usd(
        model,
        input_tokens=counted,
        max_output_tokens=max_output_tokens,
    )
    if worst > max_cost_usd:
        raise CanaryPreflightError(
            f"{data.code}: 최악비용 ${worst:.6f}가 하드캡 ${max_cost_usd:.6f}를 넘었다; "
            "생성 0회"
        )

    try:
        response = provider.generate_structured(request)
    except Exception as exc:
        raise CanaryProviderError(
            code=data.code,
            model=model,
            counted_input_tokens=counted,
            worst_case_cost_usd=worst,
            request_snapshot=request_snapshot,
            request_sha256=request_sha256,
            input_sha256=input_sha256,
            plan_sha256=plan.plan_sha256,
            error=exc,
        ) from exc
    usage = response.usage
    actual_cost = compute_cost_usd(
        model,
        input_tokens=usage.input_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        output_tokens=usage.output_tokens,
    )
    def fail(message: str) -> CanaryExecutionError:
        return CanaryExecutionError(CanaryFailure(
            error=message,
            response_model=response.model,
            response_id=response.response_id,
            actual_cost_usd=actual_cost,
            counted_input_tokens=counted,
            worst_case_cost_usd=worst,
            usage=usage,
            payload=response.payload,
            request_snapshot=request_snapshot,
            request_sha256=request_sha256,
            input_sha256=input_sha256,
            plan_sha256=plan.plan_sha256,
        ))

    try:
        result = analysis_result_from_response(
            data,
            response,
            cost_usd=actual_cost,
            max_output_tokens=max_output_tokens,
            request_user_message=request.user_message,
        )
    except AnalysisError as exc:
        raise fail(str(exc)) from exc
    problems = validate_payload(result.payload)
    if problems:
        raise fail(f"{data.code}: canary payload 검증 실패: {', '.join(problems)}")
    if actual_cost > max_cost_usd:
        raise fail(
            f"{data.code}: 실측비용 ${actual_cost:.6f}가 하드캡 ${max_cost_usd:.6f}를 넘었다"
        )
    return CanaryResult(
        analysis=result,
        counted_input_tokens=counted,
        worst_case_cost_usd=worst,
        response_id=response.response_id,
        request_snapshot=request_snapshot,
        request_sha256=request_sha256,
        input_sha256=input_sha256,
        plan_sha256=plan.plan_sha256,
    )
