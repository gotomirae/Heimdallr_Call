# PRD Ref: §7 전체 · ADR 3, 4 · traps.md T9, T61, T84, T91, T103
"""Provider 중립 LLM 경계의 회귀 테스트. 외부 API와 DB를 호출하지 않는다."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.analysis.prompts import ANALYSIS_SCHEMA, ANALYSIS_TOOL_NAME
from src.config.constants import ANALYSIS_MODEL
from src.llm.provider import LLMRequest, LLMResponse, NormalizedUsage
from src.llm.providers.anthropic import AnthropicProvider
from src.llm.providers.openai import OpenAIProvider
from src.llm.registry import resolve_provider


ROOT = Path(__file__).resolve().parents[1]


def _request(*, web_search: bool = False) -> LLMRequest:
    return LLMRequest(
        model="test-model",
        system_prompt="고정 시스템 프롬프트",
        user_message="검증된 구조화 데이터",
        schema_name=ANALYSIS_TOOL_NAME,
        schema=ANALYSIS_SCHEMA,
        max_output_tokens=1234,
        effort="low",
        web_search=web_search,
        web_search_allowed_domains=("dart.fss.or.kr",),
        web_search_max_uses=2,
        prompt_cache_key="heimdallr-analysis-v1",
    )


class _AnthropicMessages:
    def __init__(self):
        self.count_kwargs = None
        self.create_kwargs = None

    def count_tokens(self, **kwargs):
        self.count_kwargs = kwargs
        return SimpleNamespace(input_tokens=321)

    def create(self, **kwargs):
        self.create_kwargs = kwargs
        block = SimpleNamespace(type="tool_use", name=ANALYSIS_TOOL_NAME,
                                input={"one_line_thesis": "근거 있는 해석"})
        usage = SimpleNamespace(
            input_tokens=100,
            cache_creation_input_tokens=20,
            cache_read_input_tokens=30,
            output_tokens=40,
        )
        return SimpleNamespace(
            id="msg_1", model="claude-test", stop_reason="end_turn",
            content=[block], usage=usage,
        )


def test_anthropic_adapter_preserves_existing_request_and_usage_contract():
    messages = _AnthropicMessages()
    provider = AnthropicProvider(client=SimpleNamespace(messages=messages))
    request = _request()

    assert provider.count_input_tokens(request) == 321
    response = provider.generate_structured(request)

    assert messages.count_kwargs["tools"][0]["input_schema"] is ANALYSIS_SCHEMA
    assert messages.create_kwargs["tool_choice"] == {
        "type": "tool", "name": ANALYSIS_TOOL_NAME,
    }
    assert response.payload == {"one_line_thesis": "근거 있는 해석"}
    assert response.usage == NormalizedUsage(
        input_tokens=100,
        cache_write_tokens=20,
        cache_read_tokens=30,
        output_tokens=40,
        reasoning_tokens=0,
    )


class _OpenAIInputTokens:
    def __init__(self):
        self.kwargs = None

    def count(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(input_tokens=654)


class _OpenAIResponses:
    def __init__(self):
        self.input_tokens = _OpenAIInputTokens()
        self.create_kwargs = None

    def create(self, **kwargs):
        self.create_kwargs = kwargs
        details = SimpleNamespace(cached_tokens=25, cache_write_tokens=5)
        output_details = SimpleNamespace(reasoning_tokens=7)
        usage = SimpleNamespace(
            input_tokens=100,
            input_tokens_details=details,
            output_tokens=50,
            output_tokens_details=output_details,
        )
        return SimpleNamespace(
            id="resp_1", model="gpt-test", status="completed", error=None,
            incomplete_details=None,
            output_text=json.dumps({"one_line_thesis": "근거 있는 해석"}),
            output=[], usage=usage,
        )


def test_openai_adapter_uses_responses_structured_outputs_and_exact_token_count():
    responses = _OpenAIResponses()
    provider = OpenAIProvider(client=SimpleNamespace(responses=responses))
    request = _request()

    assert provider.count_input_tokens(request) == 654
    response = provider.generate_structured(request)

    assert responses.input_tokens.kwargs["reasoning"] == {"effort": "low"}
    text_format = responses.create_kwargs["text"]["format"]
    assert text_format == {
        "type": "json_schema",
        "name": ANALYSIS_TOOL_NAME,
        "description": "검증된 Heimdallr 투자 분석 결과",
        "schema": ANALYSIS_SCHEMA,
        "strict": True,
    }
    assert responses.create_kwargs["store"] is False
    assert responses.create_kwargs["reasoning"] == {"effort": "low"}
    assert response.payload == {"one_line_thesis": "근거 있는 해석"}
    # OpenAI input_tokens에는 cached/cache-write가 포함된다. 그대로 더하면 이중 과금이다.
    assert response.usage == NormalizedUsage(
        input_tokens=70,
        cache_write_tokens=5,
        cache_read_tokens=25,
        output_tokens=50,
        reasoning_tokens=7,
    )


def test_openai_canary_can_disable_sdk_retries(monkeypatch):
    import sys

    captured = {}

    class _Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=_Client))
    monkeypatch.setattr(
        "src.llm.providers.openai.require_env", lambda name: "test-key"
    )

    OpenAIProvider(max_retries=0)._client()

    assert captured == {"api_key": "test-key", "max_retries": 0}


def test_anthropic_canary_can_disable_sdk_retries(monkeypatch):
    import sys

    captured = {}

    class _Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setitem(sys.modules, "anthropic", SimpleNamespace(Anthropic=_Client))
    monkeypatch.setattr(
        "src.llm.providers.anthropic.require_env", lambda name: "test-key"
    )

    AnthropicProvider(max_retries=0)._client()

    assert captured == {"api_key": "test-key", "max_retries": 0}


def test_openai_adapter_rejects_web_search_before_any_paid_call():
    responses = _OpenAIResponses()
    provider = OpenAIProvider(client=SimpleNamespace(responses=responses))

    with pytest.raises(ValueError, match="web search"):
        provider.generate_structured(_request(web_search=True))

    assert responses.create_kwargs is None


def test_openai_invalid_json_is_returned_as_parse_error_with_usage_preserved():
    responses = _OpenAIResponses()

    def broken(**kwargs):
        result = _OpenAIResponses().create(**kwargs)
        result.output_text = "{broken"
        return result

    responses.create = broken
    response = OpenAIProvider(client=SimpleNamespace(responses=responses)).generate_structured(
        _request()
    )

    assert response.payload is None
    assert response.parse_error
    assert response.usage.output_tokens == 50


def test_analysis_orchestration_uses_provider_contract_without_sdk_objects(monkeypatch):
    """호출부에는 Anthropic/OpenAI 응답 객체가 새지 않아야 한다."""
    from src.analysis import analyze as module

    class _Provider:
        name = "fake"

        def __init__(self):
            self.counted = 0
            self.generated = 0

        def count_input_tokens(self, request):
            self.counted += 1
            return 111

        def generate_structured(self, request):
            self.generated += 1
            return LLMResponse(
                provider=self.name,
                model=request.model,
                payload={"one_line_thesis": "해석"},
                usage=NormalizedUsage(input_tokens=10, output_tokens=20),
                stop_reason="completed",
                response_id="fake_1",
            )

    captured = []
    monkeypatch.setattr(
        module,
        "record_usage",
        lambda model, usage, **kwargs: captured.append((model, usage)) or 0.001,
    )
    provider = _Provider()
    result = module.analyze(
        module.AnalysisInput(code="005930", name="삼성전자", board="KOSPI"),
        enforce_budget=False,
        token_budget=200,
        provider=provider,
        model=ANALYSIS_MODEL,
    )

    assert (provider.counted, provider.generated) == (1, 1)
    assert captured == [(ANALYSIS_MODEL, NormalizedUsage(input_tokens=10, output_tokens=20))]
    assert result.model == ANALYSIS_MODEL
    assert result.input_tokens == 10
    assert result.output_tokens == 20


def test_unpriced_model_is_blocked_before_provider_calls(monkeypatch):
    """단가 없는 모델로 먼저 호출하고 나중에 비용을 알아내는 순서는 허용하지 않는다."""
    from src.analysis import analyze as module
    from src.utils.cost_guard import UnknownModelError

    class _Provider:
        name = "fake"
        called = False

        def count_input_tokens(self, request):
            self.called = True
            return 1

        def generate_structured(self, request):
            self.called = True
            raise AssertionError("유료 호출 경로에 들어오면 안 된다")

    provider = _Provider()
    with pytest.raises(UnknownModelError):
        module.analyze(
            module.AnalysisInput(code="005930", name="삼성전자", board="KOSPI"),
            enforce_budget=False,
            provider=provider,
            model="unpriced-openai-model",
        )
    assert provider.called is False


def test_dependency_and_all_paid_workflows_declare_openai_settings():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"openai>=' in pyproject

    required = (
        "OPENAI_API_KEY",
        "ANALYSIS_LLM_PROVIDER",
        "OPENAI_ANALYSIS_MODEL",
        "OPENAI_INPUT_PER_MTOK",
        "OPENAI_OUTPUT_PER_MTOK",
        "OPENAI_CACHE_WRITE_PER_MTOK",
        "OPENAI_CACHE_READ_PER_MTOK",
    )
    for name in ("llm_batch.yml", "disclosure_poll.yml", "telegram_listen.yml"):
        body = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        missing = [setting for setting in required if setting not in body]
        assert not missing, f"{name}: OpenAI 전환 설정 누락 {missing}"


def test_registry_selects_explicit_provider_without_silent_fallback():
    anthropic, anthropic_model = resolve_provider("anthropic")
    openai, openai_model = resolve_provider("openai", "gpt-tested-snapshot")

    assert isinstance(anthropic, AnthropicProvider)
    assert anthropic_model == ANALYSIS_MODEL
    assert isinstance(openai, OpenAIProvider)
    assert openai_model == "gpt-tested-snapshot"
    with pytest.raises(ValueError, match="지원하지 않는"):
        resolve_provider("gemini")
