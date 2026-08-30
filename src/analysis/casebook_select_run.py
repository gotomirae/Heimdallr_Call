# PRD Ref: §7.4 · traps.md T7, T116, T117
"""승인된 Stage A 사례집 후보 metadata를 bounded read로 선택한다.

Supabase SELECT만 수행하며 DB·Provider·DART·텔레그램을 쓰지 않는다. 결과는 stdout으로만
출력한다. 한 테이블이 두 페이지를 모두 가득 채우면 승인 상한을 넘기기 전에 중단한다.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from src.analysis.casebook_selection import select_casebook_candidates
from src.db.supabase_client import get_client, project_ref
from src.utils.console import enable_utf8_stdout


PAGE_SIZE = 1_000
MAX_PAGES_PER_TABLE = 2

SCREEN_COLUMNS = (
    "code,fiscal_year,fiscal_quarter,gate_passed,turnaround,score_flash,"
    "has_consensus,pri,grade"
)
UNIVERSE_COLUMNS = "code,industry"


class CandidateReadLimitError(RuntimeError):
    """승인된 최대 두 페이지를 모두 채워 추가 GET이 필요함."""


@dataclass(frozen=True)
class CandidateMetadataRead:
    rows: tuple[dict[str, Any], ...]
    http_gets: int
    table_pages: dict[str, int]
    screen_row_count: int
    universe_row_count: int


def _read_bounded_pages(
    table: str,
    query_for_page: Callable[[int, int], Any],
) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    for page in range(MAX_PAGES_PER_TABLE):
        start = page * PAGE_SIZE
        chunk = query_for_page(start, start + PAGE_SIZE - 1).execute().data or []
        rows.extend(chunk)
        if len(chunk) < PAGE_SIZE:
            return rows, page + 1
    raise CandidateReadLimitError(
        f"{table}: {MAX_PAGES_PER_TABLE}페이지가 모두 {PAGE_SIZE}행; "
        "승인 범위를 넘는 다음 GET 전에 중단"
    )


def read_candidate_metadata(
    client: Any,
    *,
    fiscal_year: int,
    fiscal_quarter: int,
) -> CandidateMetadataRead:
    """Stage A의 두 endpoint를 최대 2페이지씩 읽고 industry를 code로 결합한다."""
    screens, screen_pages = _read_bounded_pages(
        "screen_results",
        lambda start, end: (
            client.table("screen_results")
            .select(SCREEN_COLUMNS)
            .eq("fiscal_year", fiscal_year)
            .eq("fiscal_quarter", fiscal_quarter)
            .eq("gate_passed", True)
            .in_("grade", ["★", "○"])
            .range(start, end)
        ),
    )
    codes = sorted({str(row.get("code") or "") for row in screens if row.get("code")})
    if not codes:
        return CandidateMetadataRead(
            rows=(),
            http_gets=screen_pages,
            table_pages={"screen_results": screen_pages, "krx_universe": 0},
            screen_row_count=0,
            universe_row_count=0,
        )

    universe, universe_pages = _read_bounded_pages(
        "krx_universe",
        lambda start, end: (
            client.table("krx_universe")
            .select(UNIVERSE_COLUMNS)
            .in_("code", codes)
            .range(start, end)
        ),
    )
    industries: dict[str, str | None] = {}
    for row in universe:
        code = str(row.get("code") or "")
        if code in industries:
            raise ValueError(f"krx_universe code 중복: {code}")
        industries[code] = row.get("industry")
    joined = tuple(
        {**row, "industry": industries.get(str(row.get("code") or ""))}
        for row in screens
    )
    return CandidateMetadataRead(
        rows=joined,
        http_gets=screen_pages + universe_pages,
        table_pages={
            "screen_results": screen_pages,
            "krx_universe": universe_pages,
        },
        screen_row_count=len(screens),
        universe_row_count=len(universe),
    )


def _existing_cases(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for case in raw.get("cases", []):
        data = case.get("input") or {}
        score = data.get("score") or {}
        gate = data.get("gate") or {}
        out.append({
            "code": data.get("code"),
            "grade": score.get("grade"),
            "has_consensus": score.get("has_consensus"),
            "turnaround": gate.get("turnaround"),
            "industry": data.get("industry"),
        })
    return out


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="사례집 Stage A read-only 후보 선택")
    parser.add_argument("--quarter", default="2026.2")
    parser.add_argument(
        "--existing-suite",
        type=Path,
        default=Path("docs/evals/suites/hj-097230-2026q2-openai-terra.json"),
    )
    parser.add_argument("--execute-approved-read", action="store_true")
    args = parser.parse_args()
    if not args.execute_approved_read:
        parser.error("Stage A 승인 뒤 --execute-approved-read를 명시해야 한다")
    year, quarter = (int(value) for value in args.quarter.split("."))
    existing = _existing_cases(args.existing_suite)
    metadata = read_candidate_metadata(
        get_client(), fiscal_year=year, fiscal_quarter=quarter
    )
    selection = select_casebook_candidates(
        list(metadata.rows),
        existing_cases=existing,
        fiscal_year=year,
        fiscal_quarter=quarter,
    )
    cell_counts: dict[str, int] = {}
    for row in metadata.rows:
        if row.get("grade") in {"★", "○"} and isinstance(row.get("has_consensus"), bool):
            cell = f"{row['grade']}/{str(row['has_consensus']).lower()}"
            cell_counts[cell] = cell_counts.get(cell, 0) + 1
    selected_cells = {item.cell for item in selection.selected}
    result = {
        "status": "completed",
        "stage": "casebook_candidate_metadata",
        "project_ref": project_ref(),
        "fiscal_year": year,
        "fiscal_quarter": quarter,
        "external_reads": {
            "http_gets": metadata.http_gets,
            "table_pages": metadata.table_pages,
            "screen_rows": metadata.screen_row_count,
            "universe_rows": metadata.universe_row_count,
        },
        "external_writes": 0,
        "candidate_pool_by_cell": dict(sorted(cell_counts.items())),
        "selected": [asdict(item) for item in selection.selected],
        "not_selected_by_cell": {
            cell: count - (1 if cell in selected_cells else 0)
            for cell, count in sorted(cell_counts.items())
        },
        "coverage": {
            "ready": selection.ready,
            "missing_cells": list(selection.missing_cells),
            "industry_count": selection.industry_count,
            "turnaround_states": list(selection.turnaround_states),
        },
        "stage_b_executed": False,
        "provider_calls": 0,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
