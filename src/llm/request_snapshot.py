# PRD Ref: §7.4 · ADR 9 · traps.md T105, T111
"""Canonical LLM 요청과 원 입력의 재현 가능한 snapshot/hash.

Provider 결과를 나중에 평가할 때 최신 prompt builder를 다시 실행하면 과거 결과가 실제로
받지 않은 숫자·스키마를 근거로 재채점된다. 호출 순간의 계약을 JSON snapshot으로 고정한다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from src.llm.provider import LLMRequest


REQUEST_SNAPSHOT_VERSION = 1


def canonical_sha256(value: Any) -> str:
    """JSON 의미가 같은 값에 동일한 SHA-256을 돌려준다."""
    body = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def snapshot_llm_request(request: LLMRequest) -> dict[str, Any]:
    """Provider 호출에 전달한 전체 Canonical 계약을 버전과 함께 고정한다."""
    return {
        "version": REQUEST_SNAPSHOT_VERSION,
        "request": asdict(request),
    }


def analysis_input_sha256(data: Any) -> str:
    """dataclass AnalysisInput이 suite의 case input과 같은지 확인한다."""
    return canonical_sha256(asdict(data))
