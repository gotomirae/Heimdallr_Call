# PRD Ref: §9 /settings · CLAUDE.md 코딩 컨벤션
"""대시보드용 상수 JSON이 `constants.py`와 어긋나지 않는지 검사한다.

★★ **임계값이 두 곳에 있으면 조용히 어긋난다.**
   참고 프로젝트에서 딥분석 문턱이 3곳에 흩어져 실제로 겪은 사고다.
   대시보드는 TypeScript라 파이썬을 못 읽으므로 JSON으로 내보내는데,
   **생성물이 낡는 것도 같은 종류의 사고**다 — 그래서 여기서 막는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config import constants
from src.config.export_constants import OUTPUT, build


def test_export_file_exists():
    assert OUTPUT.exists(), (
        "dashboard/lib/constants.json이 없다. "
        "`python -m src.config.export_constants`를 실행하라."
    )


def test_export_is_in_sync():
    """★ 상수를 고치고 내보내기를 잊으면 대시보드가 옛 숫자를 보여준다."""
    on_disk = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert on_disk == build(), (
        "constants.json이 현재 상수와 다르다. "
        "`python -m src.config.export_constants`로 다시 만들어라."
    )


def test_axis_weights_sum_to_100():
    """A+B+C+D = 100. 여기가 어긋나면 정규화 분모가 전부 틀어진다."""
    payload = build()
    assert sum(payload["score_axes"].values()) == 100


def test_denominators_match_axis_sums():
    """★ 분모는 **측정된 축의 배점 합**이어야 한다(ADR 2)."""
    axes = build()["score_axes"]
    a, b, c, d = (
        axes["A_성장가속"], axes["B_수익성"],
        axes["C_서프라이즈"], axes["D_회계품질"],
    )
    assert constants.SCORE_DENOM_FLASH_NO_CONSENSUS == a + b
    assert constants.SCORE_DENOM_FLASH_WITH_CONSENSUS == a + b + c
    assert constants.SCORE_DENOM_FINAL_NO_CONSENSUS == a + b + d
    assert constants.SCORE_DENOM_FINAL_WITH_CONSENSUS == a + b + c + d


def test_pri_weights_sum_to_100():
    payload = build()["pri"]
    assert payload["p1"] + payload["p2"] + payload["p3"] + payload["p4"] == 100


def test_pri_min_denominator_blocks_thin_evidence():
    """★ P2(52주 위치, 25점) 하나로는 판정하지 못해야 한다(T35)."""
    assert build()["pri"]["min_denominator"] > constants.PRI_WEIGHTS["p2"]


def test_matrix_thresholds_are_ordered():
    m = build()["matrix"]
    assert m["score_mid"] < m["score_high"]
    assert m["pri_low"] < m["pri_high"]


def test_notify_grades_are_star_and_circle():
    assert build()["notify"]["grades"] == ["★", "○"]


def test_dashboard_url_default_matches_env_example():
    """★ 대시보드 기본 URL이 `.env.example`과 어긋나면 안 된다.

    이 값이 틀리면 **에러 없이 텔레그램 링크만 죽는다** — 메시지는 멀쩡하고
    배포도 성공이라 눌러보기 전까지 아무도 모른다.

    실제로 겪었다: Vercel 프로젝트명을 `heinmdallr`로 알고 두 곳을 고쳤는데
    배포된 도메인은 `heimdallr-call`이었다(`heinmdallr.vercel.app` → **404**).
    두 곳을 따로 고치는 구조라 한쪽만 고치면 그대로 어긋난다.

    운영 값은 저장소 변수 `DASHBOARD_BASE_URL`이 덮으므로 이 상수는 fallback이지만,
    fallback이 틀려 있으면 변수가 빠진 순간 조용히 죽는다.
    """
    from pathlib import Path

    from src.config.constants import DASHBOARD_URL_DEFAULT

    env_example = (Path(__file__).resolve().parents[1] / ".env.example").read_text(
        encoding="utf-8"
    )
    declared = [
        line.split("=", 1)[1].strip()
        for line in env_example.splitlines()
        if line.startswith("DASHBOARD_BASE_URL=")
    ]
    assert declared, ".env.example에 DASHBOARD_BASE_URL 항목이 없다"
    assert declared[0] == DASHBOARD_URL_DEFAULT, (
        f".env.example({declared[0]})과 constants({DASHBOARD_URL_DEFAULT})가 어긋났다"
    )
