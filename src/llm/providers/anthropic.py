# PRD Ref: §7 전체 · ADR 3, 4 · traps.md T9, T34, T91, T96
"""기존 Anthropic 분석 동작을 보존하는 Provider Adapter."""

from __future__ import annotations

from src.llm.provider import LLMRequest, LLMResponse, NormalizedUsage
from src.utils.env import require_env


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, client=None, *, max_retries: int | None = None):
        self._provided_client = client
        self._max_retries = max_retries

    def _client(self):
        if self._provided_client is not None:
            return self._provided_client
        import anthropic

        kwargs = {"api_key": require_env("ANTHROPIC_API_KEY")}
        if self._max_retries is not None:
            kwargs["max_retries"] = self._max_retries
        return anthropic.Anthropic(**kwargs)

    @staticmethod
    def _analysis_tool(request: LLMRequest) -> dict:
        return {
            "name": request.schema_name,
            "description": "분석 결과를 구조화해 기록한다. 반드시 이 도구로만 응답한다.",
            "input_schema": request.schema,
            "strict": True,
        }

    @staticmethod
    def _web_search_tool(request: LLMRequest) -> dict:
        return {
            "type": "web_search_20260209",
            "name": "web_search",
            "max_uses": request.web_search_max_uses,
            "allowed_domains": list(request.web_search_allowed_domains),
        }

    def _tools(self, request: LLMRequest) -> list[dict]:
        tools = [self._analysis_tool(request)]
        if request.web_search:
            tools.append(self._web_search_tool(request))
        return tools

    def count_input_tokens(self, request: LLMRequest) -> int:
        response = self._client().messages.count_tokens(
            model=request.model,
            system=[{"type": "text", "text": request.system_prompt}],
            messages=[{"role": "user", "content": request.user_message}],
            tools=self._tools(request),
        )
        return int(response.input_tokens)

    def generate_structured(self, request: LLMRequest) -> LLMResponse:
        kwargs = {
            "model": request.model,
            "max_tokens": request.max_output_tokens,
            "system": [
                {
                    "type": "text",
                    "text": request.system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": request.effort or "low"},
            "tools": self._tools(request),
            # 강제 tool_choice와 서버 웹 검색은 함께 동작하지 않는다(T96).
            "tool_choice": (
                {"type": "auto"}
                if request.web_search
                else {"type": "tool", "name": request.schema_name}
            ),
            "messages": [{"role": "user", "content": request.user_message}],
        }
        response = self._client().messages.create(**kwargs)
        payload = next(
            (
                block.input
                for block in response.content
                if getattr(block, "type", None) == "tool_use"
                and getattr(block, "name", None) == request.schema_name
            ),
            None,
        )
        usage = response.usage
        return LLMResponse(
            provider=self.name,
            model=str(getattr(response, "model", None) or request.model),
            payload=payload,
            stop_reason=getattr(response, "stop_reason", None),
            response_id=getattr(response, "id", None),
            usage=NormalizedUsage(
                input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                cache_write_tokens=int(
                    getattr(usage, "cache_creation_input_tokens", 0) or 0
                ),
                cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            ),
        )
