# PRD Ref: §7 전체 · ADR 3, 4 · traps.md T9, T84, T103
"""OpenAI Responses API Adapter.

재무 숫자를 생성·계산하는 계층이 아니다. 검증된 구조화 입력을 해석하고 Canonical
JSON Schema로만 반환한다. 현재 웹 검색은 Provider 간 의미가 달라 명시적으로 막는다.
"""

from __future__ import annotations

import json

from src.llm.provider import LLMRequest, LLMResponse, NormalizedUsage
from src.utils.env import require_env


class OpenAIProvider:
    name = "openai"

    def __init__(self, client=None):
        self._provided_client = client

    def _client(self):
        if self._provided_client is not None:
            return self._provided_client
        from openai import OpenAI

        return OpenAI(api_key=require_env("OPENAI_API_KEY"))

    @staticmethod
    def _text_config(request: LLMRequest) -> dict:
        return {
            "format": {
                "type": "json_schema",
                "name": request.schema_name,
                "description": "검증된 Heimdallr 투자 분석 결과",
                "schema": request.schema,
                "strict": True,
            }
        }

    @staticmethod
    def _ensure_supported(request: LLMRequest) -> None:
        # 검색 도구·도메인 제한·출처 검증은 Provider마다 계약이 다르다. 같은 기능인 척
        # 조용히 약화시키지 않고 별도 Phase에서 구현한다.
        if request.web_search:
            raise ValueError("OpenAI provider web search is not enabled")

    def count_input_tokens(self, request: LLMRequest) -> int:
        self._ensure_supported(request)
        response = self._client().responses.input_tokens.count(
            model=request.model,
            instructions=request.system_prompt,
            input=request.user_message,
            text=self._text_config(request),
        )
        return int(response.input_tokens)

    @staticmethod
    def _refusal_of(response) -> str | None:
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                if getattr(content, "type", None) == "refusal":
                    return str(getattr(content, "refusal", None) or "refusal")
        return None

    @staticmethod
    def _usage_of(response) -> NormalizedUsage:
        usage = getattr(response, "usage", None)
        if usage is None:
            return NormalizedUsage()
        input_details = getattr(usage, "input_tokens_details", None)
        output_details = getattr(usage, "output_tokens_details", None)
        cache_read = int(getattr(input_details, "cached_tokens", 0) or 0)
        cache_write = int(getattr(input_details, "cache_write_tokens", 0) or 0)
        input_total = int(getattr(usage, "input_tokens", 0) or 0)
        # OpenAI input_tokens는 cached/cache-write를 포함한다. 비용 계산에서 다시
        # 더하므로 여기서 제외하지 않으면 조용히 이중 과금된다.
        uncached = max(input_total - cache_read - cache_write, 0)
        return NormalizedUsage(
            input_tokens=uncached,
            cache_write_tokens=cache_write,
            cache_read_tokens=cache_read,
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            reasoning_tokens=int(getattr(output_details, "reasoning_tokens", 0) or 0),
        )

    def generate_structured(self, request: LLMRequest) -> LLMResponse:
        self._ensure_supported(request)
        kwargs = {
            "model": request.model,
            "instructions": request.system_prompt,
            "input": request.user_message,
            "max_output_tokens": request.max_output_tokens,
            "text": self._text_config(request),
            # 분석 원문은 DB의 canonical payload만 저장한다. Provider 서버 저장은 끈다.
            "store": False,
        }
        if request.prompt_cache_key:
            kwargs["prompt_cache_key"] = request.prompt_cache_key
        response = self._client().responses.create(**kwargs)

        refusal = self._refusal_of(response)
        status = str(getattr(response, "status", None) or "unknown")
        error = getattr(response, "error", None)
        incomplete = getattr(response, "incomplete_details", None)
        if refusal:
            stop_reason = "refusal"
        elif error is not None:
            stop_reason = f"error:{getattr(error, 'code', 'unknown')}"
        elif status == "incomplete":
            stop_reason = str(getattr(incomplete, "reason", None) or "incomplete")
        else:
            stop_reason = status

        payload = None
        parse_error = None
        raw_text = str(getattr(response, "output_text", None) or "")
        if raw_text:
            try:
                parsed = json.loads(raw_text)
                if isinstance(parsed, dict):
                    payload = parsed
                else:
                    parse_error = f"structured output가 object가 아니라 {type(parsed).__name__}"
            except json.JSONDecodeError as exc:
                parse_error = f"structured output JSON 파싱 실패: {exc.msg}"

        return LLMResponse(
            provider=self.name,
            model=str(getattr(response, "model", None) or request.model),
            payload=payload,
            usage=self._usage_of(response),
            stop_reason=stop_reason,
            response_id=getattr(response, "id", None),
            parse_error=parse_error,
        )
