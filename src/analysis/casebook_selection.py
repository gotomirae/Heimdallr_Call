# PRD Ref: §7.4 · traps.md T116
"""실제 투자판단 replay 사례집의 빈 횡단면을 채우는 순수 선택기.

외부 I/O를 하지 않는다. 같은 분기의 게이트 통과 ★/○ 메타데이터를 받아
등급×컨센서스 셀을 채우되 업종과 턴어라운드/가속화 다양성을 먼저 보존한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any

from src.config.constants import (
    LLM_EVAL_CASEBOOK_MIN_INDUSTRIES,
)


_REQUIRED_CELLS = tuple(sorted(
    f"{grade}/{str(has_consensus).lower()}"
    for grade in ("★", "○")
    for has_consensus in (True, False)
))


def _cell(grade: str, has_consensus: bool) -> str:
    return f"{grade}/{str(has_consensus).lower()}"


def _number(value: Any, *, default: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return default


@dataclass(frozen=True)
class CasebookCandidate:
    code: str
    cell: str
    grade: str
    has_consensus: bool
    turnaround: bool
    industry: str
    score_flash: float | None
    pri: float | None


@dataclass(frozen=True)
class CasebookSelection:
    selected: tuple[CasebookCandidate, ...]
    missing_cells: tuple[str, ...]
    industry_count: int
    turnaround_states: tuple[bool, ...]
    ready: bool


def _candidate_of(
    row: dict[str, Any],
    *,
    fiscal_year: int,
    fiscal_quarter: int,
) -> CasebookCandidate | None:
    grade = row.get("grade")
    has_consensus = row.get("has_consensus")
    turnaround = row.get("turnaround")
    industry = str(row.get("industry") or "").strip()
    code = str(row.get("code") or "").strip()
    if (
        row.get("fiscal_year") != fiscal_year
        or row.get("fiscal_quarter") != fiscal_quarter
        or row.get("gate_passed") is not True
        or grade not in {"★", "○"}
        or not isinstance(has_consensus, bool)
        or not isinstance(turnaround, bool)
        or not code
        or not industry
    ):
        return None
    score = row.get("score_flash")
    pri = row.get("pri")
    return CasebookCandidate(
        code=code,
        cell=_cell(grade, has_consensus),
        grade=grade,
        has_consensus=has_consensus,
        turnaround=turnaround,
        industry=industry,
        score_flash=(
            float(score)
            if isinstance(score, (int, float)) and not isinstance(score, bool)
            else None
        ),
        pri=(
            float(pri)
            if isinstance(pri, (int, float)) and not isinstance(pri, bool)
            else None
        ),
    )


def select_casebook_candidates(
    rows: list[dict[str, Any]],
    *,
    existing_cases: list[dict[str, Any]],
    fiscal_year: int,
    fiscal_quarter: int,
) -> CasebookSelection:
    """빈 grade/consensus 셀을 채우는 가장 대표적인 결정론 조합을 고른다."""
    existing_codes = {str(row.get("code") or "") for row in existing_cases}
    existing_cells = {
        _cell(str(row["grade"]), row["has_consensus"])
        for row in existing_cases
        if row.get("grade") in {"★", "○"}
        and isinstance(row.get("has_consensus"), bool)
    }
    existing_industries = {
        str(row.get("industry") or "").strip()
        for row in existing_cases
        if str(row.get("industry") or "").strip()
    }
    existing_turnaround = {
        row["turnaround"]
        for row in existing_cases
        if isinstance(row.get("turnaround"), bool)
    }

    candidates = [
        candidate
        for row in rows
        if (candidate := _candidate_of(
            row,
            fiscal_year=fiscal_year,
            fiscal_quarter=fiscal_quarter,
        )) is not None
        and candidate.code not in existing_codes
    ]
    by_cell: dict[str, list[CasebookCandidate]] = {}
    for candidate in candidates:
        if candidate.cell not in existing_cells:
            by_cell.setdefault(candidate.cell, []).append(candidate)
    for values in by_cell.values():
        values.sort(key=lambda candidate: candidate.code)

    target_cells = [cell for cell in _REQUIRED_CELLS if cell not in existing_cells]
    unavailable = tuple(cell for cell in target_cells if not by_cell.get(cell))
    available = [cell for cell in target_cells if by_cell.get(cell)]
    combinations = product(*(by_cell[cell] for cell in available)) if available else [()]

    def rank(items: tuple[CasebookCandidate, ...]) -> tuple[Any, ...]:
        industries = existing_industries | {item.industry for item in items}
        turnaround = existing_turnaround | {item.turnaround for item in items}
        all_cells = existing_cells | {item.cell for item in items}
        representative = (
            all_cells == set(_REQUIRED_CELLS)
            and len(industries) >= LLM_EVAL_CASEBOOK_MIN_INDUSTRIES
            and turnaround == {True, False}
        )
        score_sum = sum(_number(item.score_flash, default=-1_000.0) for item in items)
        pri_sum = sum(_number(item.pri, default=1_000.0) for item in items)
        return (
            not representative,
            -len(industries),
            -len(turnaround),
            -score_sum,
            pri_sum,
            tuple(item.code for item in items),
        )

    selected = min(combinations, key=rank)
    selected = tuple(sorted(selected, key=lambda item: item.cell))
    all_cells = existing_cells | {item.cell for item in selected}
    industries = existing_industries | {item.industry for item in selected}
    turnaround = existing_turnaround | {item.turnaround for item in selected}
    missing_cells = tuple(cell for cell in _REQUIRED_CELLS if cell not in all_cells)
    ready = (
        not missing_cells
        and len(industries) >= LLM_EVAL_CASEBOOK_MIN_INDUSTRIES
        and turnaround == {True, False}
    )
    # `unavailable`는 missing_cells의 원인이며, 별도 후보를 만들어 메우지 않는다.
    assert set(unavailable).issubset(missing_cells)
    return CasebookSelection(
        selected=selected,
        missing_cells=missing_cells,
        industry_count=len(industries),
        turnaround_states=tuple(sorted(turnaround)),
        ready=ready,
    )
