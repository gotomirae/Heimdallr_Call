# PRD Ref: §7 전체 · ADR 3, 4 · traps.md T9
"""분석 Provider 선택. 미지원 값이나 빠진 모델을 조용히 폴백하지 않는다."""

from __future__ import annotations

from src.config.constants import ANALYSIS_LLM_PROVIDER, ANALYSIS_MODEL, CODEX_ANALYSIS_MODEL
from src.llm.provider import StructuredLLMProvider
from src.llm.providers.anthropic import AnthropicProvider
from src.llm.providers.openai import OpenAIProvider
from src.utils.env import require_env


def resolve_provider(
    provider_name: str | None = None,
    model: str | None = None,
) -> tuple[StructuredLLMProvider, str]:
    selected = (provider_name or ANALYSIS_LLM_PROVIDER).strip().lower()
    if selected == "codex_subscription":
        from src.llm.providers.codex_subscription import CodexSubscriptionProvider
        return CodexSubscriptionProvider(), model or CODEX_ANALYSIS_MODEL
    # ADR50: 명시적 provider 인자로도 유료 API를 되살리지 않는다.
    raise ValueError("API_DISABLED_PRO_SUBSCRIPTION_ONLY")
