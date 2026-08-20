# PRD Ref: §9 · traps.md T11
"""파이썬과 TS의 섹터 분류가 **같은 답을 내는지** 실제 값으로 대조한다.

왜 필요한가:
  규칙 **데이터**는 `constants.json` 한 곳에서 오지만(export_constants),
  **알고리즘**은 `sector_map.py`와 `dashboard/lib/sector.ts`에 따로 적혀 있다 —
  위치 우선 · 제외어 · 업종전용 키워드. 한쪽만 고치면 같은 종목이
  화면과 DB에서 다른 섹터로 보이는데 **에러가 나지 않는다.**

  기존 테스트는 "TS가 규칙을 다시 적지 않았는가"(문자열 검사)까지만 봤다.
  그건 데이터 중복은 막지만 **로직이 갈라지는 것은 못 막는다.**
  실제로 이 테스트는 처음 돌린 날 불일치를 잡았다(생성물이 낡아 TS만 옛 답을 냈다).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.universe.sector_map import classify_sector
from tests.sector_labels import LABELED_CASES

DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard"
SCRIPT = DASHBOARD / "scripts" / "sector_parity.mjs"


def _run_typescript(cases: list[tuple[str | None, str | None]]) -> list[str]:
    payload = json.dumps([[i, p] for i, p in cases], ensure_ascii=False)
    proc = subprocess.run(
        [shutil.which("node") or "node", str(SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=DASHBOARD,
        timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"sector_parity.mjs 실패:\n{proc.stderr[-2000:]}")
    return json.loads(proc.stdout)


# ★ node나 의존성이 없으면 **실패가 아니라 skip**이다. 다만 skip은 통과가 아니므로
#   기준선(passed+skipped 둘 다)과 대조해야 커버리지 소실을 알아챈다(T53).
pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (DASHBOARD / "node_modules" / "jiti").exists(),
    reason="node 또는 dashboard/node_modules/jiti 가 없다 (npm install 필요)",
)


def test_typescript_matches_python_on_labeled_cases():
    cases = [(industry, products) for _, industry, products, _ in LABELED_CASES]
    ts_results = _run_typescript(cases)
    py_results = [
        classify_sector(name, industry, products)
        for name, industry, products, _ in LABELED_CASES
    ]

    assert len(ts_results) == len(py_results)
    mismatched = [
        (LABELED_CASES[i][0], py, ts)
        for i, (py, ts) in enumerate(zip(py_results, ts_results))
        if py != ts
    ]
    assert not mismatched, "파이썬과 TS가 다른 섹터를 냈다:\n" + "\n".join(
        f"  {n}: python={py} · typescript={ts}" for n, py, ts in mismatched
    )


def test_parity_harness_actually_detects_a_mismatch():
    """★ 검사기는 **반드시 걸려야 하는 입력으로 먼저 검증한다** (T54).

    대조기가 조용히 무력화되면(예: 빈 배열만 돌려주면) 위 테스트는 영원히 통과한다.
    """
    ts_results = _run_typescript([(None, "반도체 후공정장비"), (None, "협동로봇")])
    assert ts_results == ["반도체장비", "기계·로봇"], (
        f"대조기가 엉뚱한 값을 준다 — 이 상태의 통과는 의미가 없다: {ts_results}"
    )
