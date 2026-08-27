# PRD Ref: §7 전체 · ADR 3, 4 · traps.md T9
"""분석 Provider 선택. 미지원 값이나 빠진 모델을 조용히 폴백하지 않는다."""

from __future__ import annotations

from src.config.constants import ANALYSIS_LLM_PROVIDER, ANALYSIS_MODEL
from src.llm.provider import StructuredLLMProvider
from src.llm.providers.anthropic import AnthropicProvider
from src.llm.providers.openai import OpenAIProvider
from src.utils.env import require_env


def resolve_provider(
    provider_name: str | None = None,
    model: str | None = None,
) -> tuple[StructuredLLMProvider, str]:
    selected = (provider_name or ANALYSIS_LLM_PROVIDER).strip().lower()
    if selected == "anthropic":
        return AnthropicProvider(), model or ANALYSIS_MODEL
    if selected == "openai":
        # 모델 alias/snapshot은 운영자가 같은 replay 평가 후 명시한다. 최신 모델을
        # 추측해 자동 선택하면 비용과 출력이 예고 없이 바뀐다.
        return OpenAIProvider(), model or require_env("OPENAI_ANALYSIS_MODEL")
    raise ValueError(
        f"지원하지 않는 ANALYSIS_LLM_PROVIDER={selected!r}; anthropic 또는 openai만 가능"
    )
