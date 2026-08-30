# PRD Ref: §7.4 · ADR 9 · traps.md T7, T84, T106
"""승인된 Provider 단건 canary CLI.

준비 단계는 필터된 Supabase 읽기만 하고 로컬 replay를 만든다. 호출 단계는 그 파일만
읽어 token-count 1회와 생성 1회를 실행하며 DB에는 아무것도 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from src.analysis.analyze import AnalysisInput
from src.analysis.canary import (
    CanaryExecutionError,
    CanaryPlan,
    CanaryProviderError,
    build_canary_plan,
    run_canary,
)
from src.analysis.run import build_input
from src.config.constants import ANALYSIS_MODEL
from src.llm.providers.anthropic import AnthropicProvider
from src.llm.providers.openai import OpenAIProvider
from src.llm.provider import StructuredLLMProvider
from src.utils.console import enable_utf8_stdout
from src.utils.env import require_env


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def prepare_replay(code: str, year: int, quarter: int, output: Path) -> AnalysisInput:
    """저장된 DB 값만 읽어 canary 입력을 고정한다. DART 폴백은 금지한다."""
    data = build_input(code, year=year, quarter=quarter, allow_fetch=False)
    missing = []
    if not data.quarters:
        missing.append("quarters")
    if not data.excerpt:
        missing.append("excerpt")
    if not data.as_of:
        missing.append("as_of")
    if (data.pri or {}).get("pri") is None:
        missing.append("pri.pri")
    if missing:
        raise SystemExit(
            f"{code}: 대표 replay 필수 입력 누락 {', '.join(missing)}; 외부 폴백 없이 중단"
        )
    _write_json(
        output,
        {
            "synthetic": False,
            "source": "Heimdallr Supabase read-only export",
            "input": asdict(data),
        },
    )
    return data


def load_replay(path: Path) -> AnalysisInput:
    raw = json.loads(path.read_text(encoding="utf-8"))
    source = raw.get("input", raw)
    if not isinstance(source, dict):
        raise ValueError("replay.input은 object여야 한다")
    data = AnalysisInput(**source)
    if (data.pri or {}).get("pri") is None:
        raise ValueError("replay.input.pri.pri가 없다 — 최종 주가반영도 없이 호출 금지(T107)")
    return data


def write_canary_plan(
    input_path: Path,
    output: Path,
    *,
    model: str,
    effort: str | None = None,
) -> CanaryPlan:
    """외부 호출 없이 exact 요청·가격·하드캡 승인 계약을 저장한다."""
    data = load_replay(input_path)
    plan = build_canary_plan(data, model=model, effort=effort)
    _write_json(
        output,
        {
            "status": "planned",
            "external_calls_executed": 0,
            "plan": plan.payload,
            "plan_sha256": plan.plan_sha256,
        },
    )
    return plan


def execute_canary(
    input_path: Path,
    output: Path,
    *,
    model: str,
    approved_plan_sha256: str,
    provider: StructuredLLMProvider | None = None,
    effort: str | None = None,
) -> None:
    """SDK 자동 재시도 없이 한 번만 생성하고 로컬 결과를 기록한다."""
    data = load_replay(input_path)
    selected_provider = provider or OpenAIProvider(max_retries=0)
    try:
        result = run_canary(
            data,
            provider=selected_provider,
            model=model,
            approved_plan_sha256=approved_plan_sha256,
            effort=effort,
        )
    except CanaryProviderError as exc:
        _write_json(
            output,
            {
                "status": "provider_error",
                "input": asdict(data),
                "candidate": {
                    "provider": selected_provider.name,
                    "model": exc.model,
                    "response_id": None,
                    "cost_usd": None,
                    "counted_input_tokens": exc.counted_input_tokens,
                    "worst_case_cost_usd": exc.worst_case_cost_usd,
                    "usage": None,
                    "payload": None,
                    "request_snapshot": exc.request_snapshot,
                    "request_sha256": exc.request_sha256,
                    "input_sha256": exc.input_sha256,
                    "plan_sha256": exc.plan_sha256,
                    "error": {
                        "type": exc.provider_error_type,
                        "message": exc.provider_error_message,
                    },
                },
            },
        )
        raise
    except CanaryExecutionError as exc:
        failure = exc.failure
        _write_json(
            output,
            {
                "status": "failed",
                "input": asdict(data),
                "candidate": {
                    "provider": selected_provider.name,
                    "model": failure.response_model,
                    "response_id": failure.response_id,
                    "cost_usd": failure.actual_cost_usd,
                    "counted_input_tokens": failure.counted_input_tokens,
                    "worst_case_cost_usd": failure.worst_case_cost_usd,
                    "usage": asdict(failure.usage),
                    "payload": failure.payload,
                    "request_snapshot": failure.request_snapshot,
                    "request_sha256": failure.request_sha256,
                    "input_sha256": failure.input_sha256,
                    "plan_sha256": failure.plan_sha256,
                    "error": failure.error,
                },
            },
        )
        raise
    analysis = result.analysis
    _write_json(
        output,
        {
            "status": "completed",
            "input": asdict(data),
            "candidate": {
                "provider": selected_provider.name,
                "model": analysis.model,
                "response_id": result.response_id,
                "cost_usd": analysis.cost_usd,
                "counted_input_tokens": result.counted_input_tokens,
                "worst_case_cost_usd": result.worst_case_cost_usd,
                "usage": {
                    "input_tokens": analysis.input_tokens,
                    "cache_write_tokens": analysis.cache_write_tokens,
                    "cache_read_tokens": analysis.cache_read_tokens,
                    "output_tokens": analysis.output_tokens,
                },
                "payload": analysis.payload,
                "request_snapshot": result.request_snapshot,
                "request_sha256": result.request_sha256,
                "input_sha256": result.input_sha256,
                "plan_sha256": result.plan_sha256,
            },
        },
    )


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="Provider 단건 canary (승인 후 실행)")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare", help="필터된 DB 읽기로 로컬 replay 생성")
    prepare.add_argument("--code", default="097230")
    prepare.add_argument("--quarter", default="2026.2")
    prepare.add_argument("--output", type=Path, required=True)

    plan = sub.add_parser("plan", help="외부 호출 없이 exact 승인 계약 생성")
    plan.add_argument("--input", type=Path, required=True)
    plan.add_argument("--output", type=Path, required=True)
    plan.add_argument("--provider", choices=("openai", "anthropic"), default="openai")
    plan.add_argument("--effort", choices=("low", "medium", "high"))

    call = sub.add_parser("call", help="로컬 replay로 선택 Provider를 정확히 한 번 호출")
    call.add_argument("--input", type=Path, required=True)
    call.add_argument("--output", type=Path, required=True)
    call.add_argument("--execute-approved-canary", action="store_true")
    call.add_argument("--approved-plan-sha256", required=True)
    call.add_argument("--provider", choices=("openai", "anthropic"), default="openai")
    call.add_argument("--effort", choices=("low", "medium", "high"))

    args = parser.parse_args()
    if args.command == "prepare":
        year, quarter = (int(value) for value in args.quarter.split("."))
        prepare_replay(args.code, year, quarter, args.output)
        print(f"replay 저장: {args.output}")
        return 0

    if args.command == "plan":
        model = (
            ANALYSIS_MODEL
            if args.provider == "anthropic"
            else require_env("OPENAI_ANALYSIS_MODEL")
        )
        result = write_canary_plan(
            args.input,
            args.output,
            model=model,
            effort=args.effort,
        )
        print(f"canary 승인 계획 저장: {args.output}")
        print(f"plan_sha256: {result.plan_sha256}")
        return 0

    if not args.execute_approved_canary:
        parser.error("유료 호출 승인 뒤 --execute-approved-canary를 명시해야 한다")
    model = (
        ANALYSIS_MODEL
        if args.provider == "anthropic"
        else require_env("OPENAI_ANALYSIS_MODEL")
    )
    provider = (
        AnthropicProvider(max_retries=0)
        if args.provider == "anthropic"
        else OpenAIProvider(max_retries=0)
    )
    execute_canary(
        args.input,
        args.output,
        model=model,
        approved_plan_sha256=args.approved_plan_sha256,
        provider=provider,
        effort=args.effort,
    )
    print(f"canary 결과 저장: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
