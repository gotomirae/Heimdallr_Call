# PRD Ref: §7 · ADR50
"""Canonical 분석을 구독 Codex 작성→검수 두 단계로 생성한다."""
import hashlib
import json

from src.config.constants import CODEX_INPUT_MAX_CHARS
from src.llm.provider import LLMRequest, LLMResponse, NormalizedUsage
from src.llm.subscription import execute, usage


class CodexSubscriptionProvider:
    name = "codex_subscription"

    def count_input_tokens(self, request: LLMRequest) -> int:
        # API token-count endpoint is intentionally unused. This is a conservative byte bound.
        return len((request.system_prompt + request.user_message).encode("utf-8"))

    def generate_structured(self, request: LLMRequest) -> LLMResponse:
        prompt = request.system_prompt + "\n" + request.user_message
        if len(prompt) > CODEX_INPUT_MAX_CHARS:
            raise ValueError("CODEX_INPUT_TOO_LARGE")
        key = hashlib.sha256(json.dumps({"model": request.model, "prompt": prompt,
                                        "schema": request.schema}, sort_keys=True).encode()).hexdigest()
        draft = execute(prompt + "\n숫자는 입력표 그대로 사용하고 미확보를 명시하라. 최종 JSON만 반환하라.",
                        request.schema, key=key, phase="draft", web_search=request.web_search)
        reviewed = execute(prompt + "\n다음 초안을 검수하라. 단위/기간/원문근거/반대논거/미확보를 대조하고 "
                           "오류를 수정한 전체 최종 JSON을 반환하라. 같은 모델의 자체검수임을 전제로 한다.\n"
                           + json.dumps(draft, ensure_ascii=False), request.schema, key=key, phase="review", web_search=request.web_search)
        used = usage(key, ("draft", "review"))
        return LLMResponse(provider=self.name, model=request.model, payload=reviewed,
                           usage=NormalizedUsage(input_tokens=max(0, used["input_tokens"]-used["cached_input_tokens"]),
                               cache_read_tokens=used["cached_input_tokens"], output_tokens=used["output_tokens"],
                               reasoning_tokens=used["reasoning_output_tokens"]), stop_reason="completed", response_id=key)
