# PRD Ref: §7 · ADR 3 — LLM은 성장 가속 종목에만 사용한다.
"""LLM 분석 대상의 단일 정의."""

from __future__ import annotations


def is_growth_acceleration(row: dict) -> bool:
    """세 성장 게이트를 통과했고 흑자전환 분류가 아닌 종목만 허용한다."""
    return row.get("gate_passed") is True and row.get("turnaround") is not True

