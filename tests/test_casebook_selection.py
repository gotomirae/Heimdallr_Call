# PRD Ref: §7.4 · traps.md T116
"""실제 투자판단 사례집 후보를 외부 I/O 없이 결정론적으로 고른다."""

from __future__ import annotations

import pytest

from src.analysis.casebook_select_run import (
    CandidateReadLimitError,
    read_candidate_metadata,
)
from src.analysis.casebook_selection import select_casebook_candidates


EXISTING = [{
    "code": "097230",
    "grade": "★",
    "has_consensus": False,
    "turnaround": False,
    "industry": "토목 건설업",
}]


def _row(
    code: str,
    grade: str,
    has_consensus: bool,
    turnaround: bool,
    industry: str,
    *,
    score: float = 80.0,
    pri: float = 20.0,
) -> dict:
    return {
        "code": code,
        "fiscal_year": 2026,
        "fiscal_quarter": 2,
        "gate_passed": True,
        "grade": grade,
        "has_consensus": has_consensus,
        "turnaround": turnaround,
        "score_flash": score,
        "pri": pri,
        "industry": industry,
    }


def test_selector_fills_three_missing_cells_and_prefers_representative_cross_section():
    rows = [
        _row("000001", "★", True, False, "토목 건설업", score=99),
        _row("000002", "★", True, True, "반도체", score=90),
        _row("000003", "○", True, False, "소프트웨어", score=88),
        _row("000004", "○", False, False, "조선", score=87),
        # 점수만 보면 이 행이 앞서지만 같은 업종만 늘리므로 대표성 조합에서는 밀린다.
        _row("000005", "○", False, False, "토목 건설업", score=98),
    ]

    result = select_casebook_candidates(
        rows,
        existing_cases=EXISTING,
        fiscal_year=2026,
        fiscal_quarter=2,
    )

    assert result.ready is True
    assert [item.cell for item in result.selected] == ["○/false", "○/true", "★/true"]
    assert {item.code for item in result.selected} == {"000002", "000003", "000004"}
    assert result.industry_count == 4
    assert result.turnaround_states == (False, True)


def test_selector_is_independent_of_postgrest_row_order():
    rows = [
        _row("000002", "★", True, True, "반도체"),
        _row("000003", "○", True, False, "소프트웨어"),
        _row("000004", "○", False, False, "조선"),
    ]

    forward = select_casebook_candidates(
        rows, existing_cases=EXISTING, fiscal_year=2026, fiscal_quarter=2
    )
    reverse = select_casebook_candidates(
        list(reversed(rows)), existing_cases=EXISTING,
        fiscal_year=2026, fiscal_quarter=2,
    )

    assert forward == reverse


def test_selector_reports_missing_cell_without_inventing_a_candidate():
    rows = [
        _row("000002", "★", True, True, "반도체"),
        _row("000003", "○", True, False, "소프트웨어"),
    ]

    result = select_casebook_candidates(
        rows, existing_cases=EXISTING, fiscal_year=2026, fiscal_quarter=2
    )

    assert result.ready is False
    assert result.missing_cells == ("○/false",)
    assert {item.cell for item in result.selected} == {"★/true", "○/true"}


def test_selector_excludes_wrong_period_failed_gate_and_unknown_boolean():
    rows = [
        _row("000001", "★", True, True, "반도체"),
        {**_row("000002", "○", True, False, "소프트웨어"), "gate_passed": False},
        {**_row("000003", "○", False, False, "조선"), "fiscal_quarter": 1},
        {**_row("000004", "○", False, False, "조선"), "has_consensus": None},
    ]

    result = select_casebook_candidates(
        rows, existing_cases=EXISTING, fiscal_year=2026, fiscal_quarter=2
    )

    assert [item.code for item in result.selected] == ["000001"]
    assert result.missing_cells == ("○/false", "○/true")


class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table = table
        self.start = 0
        self.end = 999

    def select(self, _columns):
        return self

    def eq(self, _column, _value):
        return self

    def in_(self, _column, _values):
        return self

    def range(self, start, end):
        self.start, self.end = start, end
        return self

    def execute(self):
        self.client.calls.append((self.table, self.start, self.end))
        page = self.start // 1000
        rows = self.client.pages[self.table][page]
        return type("Response", (), {"data": rows})()


class _Client:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def table(self, name):
        return _Query(self, name)


def test_stage_a_reads_exactly_two_gets_when_each_result_fits_one_page():
    screen = [
        _row("000002", "★", True, True, "ignored"),
        _row("000003", "○", True, False, "ignored"),
        _row("000004", "○", False, False, "ignored"),
    ]
    universe = [
        {"code": "000002", "industry": "반도체"},
        {"code": "000003", "industry": "소프트웨어"},
        {"code": "000004", "industry": "조선"},
    ]
    client = _Client({"screen_results": [screen], "krx_universe": [universe]})

    result = read_candidate_metadata(client, fiscal_year=2026, fiscal_quarter=2)

    assert result.http_gets == 2
    assert result.table_pages == {"screen_results": 1, "krx_universe": 1}
    assert result.rows[0]["industry"] == "반도체"
    assert client.calls == [
        ("screen_results", 0, 999),
        ("krx_universe", 0, 999),
    ]


def test_stage_a_stops_after_two_full_pages_instead_of_exceeding_approval():
    full_page = [
        _row(f"{index:06d}", "★", True, False, "ignored")
        for index in range(1000)
    ]
    client = _Client({"screen_results": [full_page, full_page]})

    with pytest.raises(CandidateReadLimitError, match="screen_results"):
        read_candidate_metadata(client, fiscal_year=2026, fiscal_quarter=2)

    assert client.calls == [
        ("screen_results", 0, 999),
        ("screen_results", 1000, 1999),
    ]
