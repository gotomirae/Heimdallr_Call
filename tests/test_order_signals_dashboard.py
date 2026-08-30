# PRD Ref: §9.1 · traps.md T99/T100
"""종목 상세의 수주 공시 신호가 조용히 과장되지 않는지 검증한다."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard"
SCRIPT = DASHBOARD / "scripts" / "order_signal_cases.mjs"


pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (DASHBOARD / "node_modules" / "jiti").exists(),
    reason="node 또는 dashboard/node_modules/jiti가 없다 (npm install 필요)",
)


def _run(cases: list[dict]) -> list[dict | None]:
    proc = subprocess.run(
        [shutil.which("node") or "node", str(SCRIPT)],
        input=json.dumps(cases, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=DASHBOARD,
        timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"order_signal_cases.mjs 실패:\n{proc.stderr[-2000:]}")
    return json.loads(proc.stdout)


def test_order_signal_requires_same_quarter_and_actual_order_language():
    cases = [
        {
            "row": {
                "fiscal_year": 2026,
                "fiscal_quarter": 2,
                "sections": {"매출 및 수주상황": "신규 수주 350억원을 확보했다."},
            },
            "year": 2026,
            "quarter": 2,
        },
        {
            "row": {
                "fiscal_year": 2026,
                "fiscal_quarter": 1,
                "sections": {"매출 및 수주상황": "수주잔고 900억원"},
            },
            "year": 2026,
            "quarter": 2,
        },
        {
            "row": {
                "fiscal_year": 2026,
                "fiscal_quarter": 2,
                "sections": {"매출 및 수주상황": "제품별 매출 실적을 기재한다."},
            },
            "year": 2026,
            "quarter": 2,
        },
        {
            "row": {
                "fiscal_year": 2026,
                "fiscal_quarter": 2,
                "sections": {"원재료 및 생산설비": "원재료 장기공급계약을 체결했다."},
            },
            "year": 2026,
            "quarter": 2,
        },
    ]

    found, wrong_quarter, heading_only, procurement_contract = _run(cases)
    assert found is not None
    assert found["status"] == "evidence"
    assert found["sourceLabel"] == "2026년 2분기 정기보고서"
    assert "350억원" in found["evidence"]
    assert wrong_quarter is None
    assert heading_only is None
    assert procurement_contract is None


def test_nondisclosure_and_truncation_are_exposed_not_inferred():
    limited, clipped = _run(
        [
            {
                "row": {
                    "fiscal_year": 2026,
                    "fiscal_quarter": 2,
                    "sections": {"매출 및 수주상황": "수주잔고는 영업상 비공개입니다."},
                },
                "year": 2026,
                "quarter": 2,
            },
            {
                "row": {
                    "fiscal_year": 2026,
                    "fiscal_quarter": 2,
                    "sections": {
                        "매출 및 수주상황": "수주잔고 관련 내용 …(이하 1,240자 생략)"
                    },
                },
                "year": 2026,
                "quarter": 2,
            },
        ]
    )

    assert limited is not None and limited["status"] == "limited"
    assert limited["truncated"] is False
    assert clipped is not None and clipped["truncated"] is True
