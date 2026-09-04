# PRD Ref: §9 /settings · CLAUDE.md 코딩 컨벤션
"""대시보드용 상수 JSON이 `constants.py`와 어긋나지 않는지 검사한다.

★★ **임계값이 두 곳에 있으면 조용히 어긋난다.**
   참고 프로젝트에서 딥분석 문턱이 3곳에 흩어져 실제로 겪은 사고다.
   대시보드는 TypeScript라 파이썬을 못 읽으므로 JSON으로 내보내는데,
   **생성물이 낡는 것도 같은 종류의 사고**다 — 그래서 여기서 막는다.
"""

from __future__ import annotations

import json
import re
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
    assert sum(payload[f"p{i}"] for i in range(1, 6)) == 100


def test_pri_min_denominator_blocks_thin_evidence():
    """★ 25점짜리 항목 하나로는 판정하지 못해야 한다(T35)."""
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

def test_sector_rules_are_exported():
    """★ 대시보드가 **읽는 시점에** 섹터를 분류한다(DB 컬럼 없이).

    규칙을 TS에 다시 적으면 두 곳이 조용히 어긋난다 — 파이썬을 유일한 출처로 두고
    JSON으로 내보낸다. `dashboard/lib/sector.ts`가 이걸 읽는다.
    """
    import json
    from pathlib import Path

    from src.universe.sector_map import SECTOR_RULES, UNKNOWN_SECTOR

    path = Path(__file__).resolve().parents[1] / "dashboard" / "lib" / "constants.json"
    data = json.loads(path.read_text(encoding="utf-8"))

    exported = data["sector_rules"]
    assert len(exported) == len(SECTOR_RULES), (
        "생성물이 낡았다 — python -m src.config.export_constants 를 다시 돌려라"
    )
    # ★ **순서가 우선순위다.** 순서가 바뀌면 두산에너빌리티가 조용히 조선으로 간다(T68).
    assert [r["sector"] for r in exported] == [name for name, _ in SECTOR_RULES]
    for row, (name, keywords) in zip(exported, SECTOR_RULES):
        assert row["keywords"] == list(keywords), f"{name} 키워드가 어긋났다"
    assert data["sector_unknown"] == UNKNOWN_SECTOR


def _strip_ts_comments(source: str) -> str:
    """주석을 걷어낸다. **검사기가 자기 설명 주석에 걸리면 안 된다.**

    실측: `sector.ts` 주석에 '반도체장비'라는 낱말이 예시로 들어 있어
    "규칙이 TS에 박혔다"는 오탐이 났다.
    """
    import re

    without_block = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return "\n".join(
        line for line in without_block.splitlines()
        if not line.lstrip().startswith(("//", "*"))
    )


def test_dashboard_does_not_redefine_sector_rules():
    """★ TS에 규칙을 손으로 적어 두면 파이썬을 고쳐도 화면이 안 바뀐다."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "dashboard" / "lib" / "sector.ts").read_text(
        encoding="utf-8"
    )
    assert "constants.sector_rules" in src, "규칙을 생성물에서 읽지 않는다"

    code = _strip_ts_comments(src)
    for keyword in ("반도체장비", "터어빈", "양극재", "이차전지"):
        assert keyword not in code, (
            f"'{keyword}'가 TS 코드에 직접 적혀 있다 — sector_map.py가 유일한 출처여야 한다"
        )


def test_sector_guard_actually_catches_it():
    """검사기를 **반드시 걸려야 하는 입력**으로 먼저 검증한다(T54)."""
    assert "터어빈" in _strip_ts_comments('const R = ["터어빈"];')
    assert "터어빈" not in _strip_ts_comments("// 터어빈은 예시다\nconst x = 1;")
    assert "터어빈" not in _strip_ts_comments("/* 터어빈 설명 */\nconst x = 1;")


# ═══════════════════════════════════════════════════════════════════
# T82 — 상한은 세 곳에 흩어져 있다: constants.py · .env.example · 워크플로 env
# ═══════════════════════════════════════════════════════════════════
ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"

#: 상한을 실제로 쓰는(= LLM을 부르는) 워크플로. 판정은 파일명이 아니라
#: **ANTHROPIC_API_KEY 보유**로 한다 — 새 워크플로가 생겨도 자동으로 걸린다.
BUDGET_ENV_KEYS = ("MONTHLY_COST_CEILING_USD", "DAILY_ANALYSIS_LIMIT")


def _llm_workflows() -> list[Path]:
    return [
        p for p in sorted(WORKFLOW_DIR.glob("*.yml"))
        if "ANTHROPIC_API_KEY" in p.read_text(encoding="utf-8")
    ]


def test_env_example_matches_code_defaults():
    """★★ T82 — `.env.example`이 낡으면 **로컬만** 다른 상한으로 돈다.

    실측(2026-08-21): 코드 기본값이 12·80인데 `.env.example`은 **8·20**이었다.
    이 파일을 복사해 `.env`를 만든 사람은 자기도 모르게 더 낮은 상한으로 돌고,
    CI와 결과가 달라진다. 에러는 없고 "왜 로컬에서만 일찍 막히지"만 남는다.
    """
    from src.config import constants

    body = (ROOT / ".env.example").read_text(encoding="utf-8")
    for key in BUDGET_ENV_KEYS:
        match = re.search(rf"^{key}=(\d+)$", body, re.M)
        assert match, f".env.example에 {key}가 없다"
        assert int(match.group(1)) == getattr(constants, key), (
            f".env.example의 {key}={match.group(1)}가 코드 기본값 "
            f"{getattr(constants, key)}와 다르다 — 로컬만 다른 상한으로 돈다"
        )


@pytest.mark.parametrize("path", _llm_workflows(), ids=lambda p: p.name)
def test_llm_workflows_pass_budget_env(path: Path):
    """★★ T82 — 워크플로가 상한 env를 넘기지 않으면 **저장소 변수가 무시된다.**

    `optional_env_int`라 env로 조절되게 설계해 놓고, 정작 워크플로에서
    안 넘기고 있었다(실측: LLM을 부르는 3개 워크플로 전부 누락).
    GitHub Variable을 만들어도 **에러 없이** 코드 기본값이 쓰인다 —
    "올렸는데 왜 그대로지"를 로그로는 알 수 없다.
    """
    body = path.read_text(encoding="utf-8")
    for key in BUDGET_ENV_KEYS:
        assert re.search(rf"^\s*{key}:\s*\$\{{\{{\s*vars\.{key}\s*\}}\}}", body, re.M), (
            f"{path.name}이 LLM을 부르는데 {key}를 env로 넘기지 않는다 — "
            "저장소 변수를 만들어도 조용히 무시된다"
        )


def test_budget_env_guard_actually_catches_it():
    """★ 검사기를 **반드시 걸려야 하는 입력**으로 먼저 검증한다(T54).

    `_llm_workflows()`가 빈 목록을 주면 parametrize가 0건이 되어
    **아무것도 검사하지 않고 통과**한다 — 가장 위험한 실패 모양이다.
    """
    assert _llm_workflows(), "LLM 워크플로를 하나도 못 찾았다 — 검사기가 무력화됐다"

    good = "    MONTHLY_COST_CEILING_USD: ${{ vars.MONTHLY_COST_CEILING_USD }}\n"
    bad = "    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}\n"
    pattern = r"^\s*MONTHLY_COST_CEILING_USD:\s*\$\{\{\s*vars\.MONTHLY_COST_CEILING_USD\s*\}\}"
    assert re.search(pattern, good, re.M)
    assert not re.search(pattern, bad, re.M)
    # secrets로 잘못 넘기는 형태도 걸러야 한다 — 상한은 비밀이 아니라 설정이다
    assert not re.search(
        pattern, "    MONTHLY_COST_CEILING_USD: ${{ secrets.MONTHLY_COST_CEILING_USD }}\n", re.M
    )


def test_workflow_comments_do_not_hardcode_budget_numbers():
    """★ T65와 같은 부류 — 주석에 손으로 적은 상한은 조용히 어긋난다.

    실측(2026-08-21): 같은 상한을 두고 세 워크플로 주석이 제각각
    `월 $8` · `월 $8 · 일 20건` · `월 실링 $12`를 말하고 있었다.
    코드는 12였다 — **셋 다 틀렸다.** 숫자 대신 출처를 가리키게 한다.
    """
    offenders = []
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "#" not in line:
                continue
            comment = line.split("#", 1)[1]
            if re.search(r"월\s*(실링\s*)?\$\d", comment) or re.search(r"일\s*\d+건", comment):
                offenders.append(f"{path.name}:{lineno}{comment.strip()[:50]}")
    assert not offenders, (
        "워크플로 주석에 상한 숫자가 박혀 있다 — constants.py를 가리켜라(T82):\n"
        + "\n".join(offenders)
    )
