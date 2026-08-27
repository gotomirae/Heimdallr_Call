# PRD Ref: §7 전체 · ADR 3, 4
"""LLM Provider가 따라야 하는 최소 계약.

Provider SDK 객체를 분석·비용·저장 계층으로 흘려보내지 않는다. 특히 usage는
`NormalizedUsage`로 바꿔야 cached input을 일반 input과 이중 과금하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMRequest:
    """Provider에 독립적인 구조화 분석 요청."""

    model: str
    system_prompt: str
    user_message: str
    schema_name: str
    schema: dict
    max_output_tokens: int
    effort: str | None = None
    web_search: bool = False
    web_search_allowed_domains: tuple[str, ...] = ()
    web_search_max_uses: int = 0
    prompt_cache_key: str | None = None


@dataclass(frozen=True)
class NormalizedUsage:
    """비용 계산용 usage.

    `input_tokens`는 cached/cache-write를 제외한 입력 토큰이다. Provider가 total input을
    반환하면 Adapter에서 빼고 넘긴다. 이 계약이 없으면 같은 토큰을 두 번 과금한다.
    """

    input_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass(frozen=True)
class LLMResponse:
    provider: str
    model: str
    payload: dict | None
    usage: NormalizedUsage
    stop_reason: str | None = None
    response_id: str | None = None
    parse_error: str | None = None


class StructuredLLMProvider(Protocol):
    """분석 서비스가 의존하는 유일한 Provider 표면."""

    name: str

    def count_input_tokens(self, request: LLMRequest) -> int:
        """실제 생성 호출 전에 입력 토큰 수를 돌려준다."""

    def generate_structured(self, request: LLMRequest) -> LLMResponse:
        """Canonical JSON Schema를 만족하는 구조화 분석을 생성한다."""
