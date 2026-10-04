# PRD Ref: §7 전체 · ADR 3, 4 · traps.md T9, T34, T91, T96
"""기존 Anthropic 분석 동작을 보존하는 Provider Adapter."""

from __future__ import annotations

import json

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
    def _section_transport(request: LLMRequest) -> bool:
        # Dashboard's mandatory value-chain schema exceeded the provider grammar
        # compiler despite having no optional fields. Keep the canonical contract.
        return "value_chain" in request.schema.get("required", [])

    @staticmethod
    def _analysis_tool(request: LLMRequest) -> dict:
        schema = request.schema
        description = "분석 결과를 구조화해 기록한다. 반드시 이 도구로만 응답한다."
        if AnthropicProvider._section_transport(request):
            # Only the wire grammar is shallow. Objects/arrays are JSON strings;
            # decoded content still passes the full canonical validation before save.
            description += (
                " 각 항목은 아래 원래 계약을 따라 작성한다. 객체/배열 항목은 "
                "마크다운 없이 올바른 JSON 문자열로 인코딩한다. 단순 문자열은 그대로 쓴다. "
                "근거 없는 숫자나 누락 항목을 만들어 채우지 않는다. 원래 계약: "
                + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
            )
            schema = {
                "type": "object", "additionalProperties": False,
                "required": list(schema["required"]),
                "properties": {
                    key: {"type": "string"}
                    for key in schema["properties"]
                },
            }
        return {
            "name": request.schema_name,
            "description": description,
            "input_schema": schema,
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
        parse_error = None
        if payload is not None and self._section_transport(request):
            try:
                if not isinstance(payload, dict):
                    raise ValueError("section transport must be an object")
                if set(payload) != set(request.schema["properties"]):
                    raise ValueError("section transport keys differ from canonical contract")
                decoded = {}
                for key, spec in request.schema["properties"].items():
                    value = payload[key]
                    if not isinstance(value, str):
                        raise ValueError(f"{key}: section transport must be a string")
                    decoded[key] = (
                        value if spec.get("type") == "string" else json.loads(value)
                    )
                payload = decoded
            except (ValueError, TypeError) as exc:
                # Never lose paid response usage when decoding fails.
                payload = None
                parse_error = f"section transport decode failed: {exc}"
        usage = response.usage
        server_tool_use = getattr(usage, "server_tool_use", None)
        if isinstance(server_tool_use, dict):
            web_search_requests = int(server_tool_use.get("web_search_requests", 0) or 0)
        else:
            web_search_requests = int(
                getattr(server_tool_use, "web_search_requests", 0) or 0
            )
        source_urls: list[str] = []
        for block in response.content:
            if getattr(block, "type", None) != "web_search_tool_result":
                continue
            content = getattr(block, "content", None)
            # 서버 검색 오류일 때 content는 결과 배열이 아니라 오류 객체다.
            # 유료 응답을 받은 뒤 Adapter가 TypeError로 죽지 않게 결과 배열만 순회한다.
            items = content if isinstance(content, (list, tuple)) else ()
            for item in items:
                url = item.get("url") if isinstance(item, dict) else getattr(item, "url", None)
                if isinstance(url, str) and url.startswith(("https://", "http://")):
                    source_urls.append(url)
        return LLMResponse(
            provider=self.name,
            model=str(getattr(response, "model", None) or request.model),
            payload=payload,
            parse_error=parse_error,
            stop_reason=getattr(response, "stop_reason", None),
            response_id=getattr(response, "id", None),
            usage=NormalizedUsage(
                input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
                cache_write_tokens=int(
                    getattr(usage, "cache_creation_input_tokens", 0) or 0
                ),
                cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
                web_search_requests=web_search_requests,
            ),
            source_urls=tuple(dict.fromkeys(source_urls)),
        )
