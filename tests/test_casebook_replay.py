# PRD Ref: §7.4 · traps.md T107, T112, T115, T117
"""Stage B 실제 replay를 외부 호출 전에 검증한다."""

from __future__ import annotations

import pytest

from src.analysis.analyze import AnalysisInput
from src.analysis.casebook_replay_run import (
    CandidateExpectation,
    ReplayValidationError,
    commit_json_artifacts,
    validate_casebook_replay,
)


def _input(*, has_consensus: bool = True) -> AnalysisInput:
    quarters = [
        {
            "code": "004000",
            "fiscal_year": year,
            "fiscal_quarter": quarter,
            "revenue": 100_000_000_000,
            "op": 10_000_000_000,
            "np": 8_000_000_000,
            "opm": 10.0,
        }
        for year, quarter in ((2025, 2), (2025, 3), (2025, 4), (2026, 1), (2026, 2))
    ]
    return AnalysisInput(
        code="004000",
        name="롯데정밀화학",
        board="KOSPI",
        industry="기초 화학물질 제조업",
        fiscal_year=2026,
        fiscal_quarter=2,
        quarters=quarters,
        gate={"passed": True, "turnaround": False},
        score={"grade": "○", "has_consensus": has_consensus},
        consensus=(
            {"n_estimates": 3, "snapshot_at": "2026-08-01T00:00:00+00:00"}
            if has_consensus else None
        ),
        price={"snap_date": "2026-08-27", "close": 50_000},
        pri={"pri": 48.37},
        excerpt="[출처: 2026년 2분기 정기보고서]\n\n### 매출 및 수주상황\n내용",
        quarter_prices=[],
        disclosures=[],
        as_of="2026-08-27",
    )


def _expected() -> CandidateExpectation:
    return CandidateExpectation(
        code="004000",
        grade="○",
        has_consensus=True,
        turnaround=False,
        industry="기초 화학물질 제조업",
    )


def test_stage_b_replay_validation_returns_measured_contract():
    metrics = validate_casebook_replay(_input(), _expected())

    assert metrics.quarter_count == 5
    assert metrics.latest_period == "2026.2Q"
    assert metrics.consensus_snapshot_at == "2026-08-01T00:00:00+00:00"
    assert metrics.as_of == "2026-08-27"
    assert metrics.user_message_chars > 0


def test_stage_b_replay_rejects_screen_and_input_consensus_mismatch():
    with pytest.raises(ReplayValidationError, match="has_consensus"):
        validate_casebook_replay(_input(has_consensus=False), _expected())


def test_stage_b_replay_rejects_fallback_excerpt_from_another_quarter():
    data = _input()
    data.excerpt = (
        "[출처: ★ 2026년 1분기 정기보고서 — **2026년 2분기 것이 아니다.**]\n내용"
    )

    with pytest.raises(ReplayValidationError, match="같은 분기 발췌"):
        validate_casebook_replay(data, _expected())


def test_stage_b_artifacts_are_committed_from_their_target_directory(tmp_path):
    replay = tmp_path / "replays" / "004000-2026q2.json"
    result = tmp_path / "results" / "stage-b.json"

    commit_json_artifacts([
        (replay, {"input": {"code": "004000"}}),
        (result, {"status": "completed"}),
    ])

    assert replay.read_text(encoding="utf-8").startswith("{")
    assert result.read_text(encoding="utf-8").startswith("{")
    assert list(tmp_path.rglob("*.tmp-stage-b")) == []
