# PRD Ref: §7 · ADR 3, ADR 5 · traps.md T69
"""LLM 배치 선정 로직. 외부 I/O 없이 돈다(`targets`는 DB를 읽으므로 순수부만 검사).

★★ 이 파일이 막는 것: **발송 등급인데 해석이 없는 종목이 생기는 것.**
   실측(2026-08-17) 발송 대상 70종목 중 22종목이 그 상태였다 —
   발송은 등급 기준(★/○)인데 분석은 스코어 하한(75)으로 뽑고 있었다.
   등급은 스코어와 반영도의 **교차** 판정이라 두 기준이 갈라지면 사이로 빠진다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.analysis.batch import (
    DEFAULT_MAX_SECONDS,
    DEFAULT_MIN_SCORE,
    DEFAULT_TOP,
    attractiveness,
)
from src.config.constants import (
    DAILY_ANALYSIS_LIMIT,
    MONTHLY_COST_CEILING_USD,
    NOTIFY_GRADES,
    SCORE_HIGH,
)


def _pick(rows: list[dict], *, top: int, min_score: float) -> list[dict]:
    """`targets()`의 **선정 규칙만** 떼어낸 것. DB 없이 검사하기 위한 복제다.

    ★ 규칙이 갈라지지 않게 아래 `test_pick_matches_targets_source`가
      실제 소스에 같은 조건이 있는지 확인한다.
    """
    picked = [
        r for r in rows
        if r.get("gate_passed") is True
        and r.get("grade") is not None
        and (
            r["grade"] in NOTIFY_GRADES
            or (r.get("score_flash") is not None and float(r["score_flash"]) >= min_score)
        )
    ]
    picked.sort(key=lambda r: (attractiveness(r) is None, -(attractiveness(r) or 0)))
    return picked[:top]


#: 실측에서 실제로 빠졌던 종목들(스코어가 하한 미달인 ○).
REAL_MISSED = [
    {"code": "A", "grade": "○", "score_flash": 74.9, "pri": 3.4, "gate_passed": True},
    {"code": "B", "grade": "○", "score_flash": 68.7, "pri": 2.7, "gate_passed": True},  # 롯데케미칼
    {"code": "C", "grade": "○", "score_flash": 69.3, "pri": 1.8, "gate_passed": True},  # GKL
]
HIGH_SCORE = [
    {"code": "D", "grade": "★", "score_flash": 92.0, "pri": 10.0, "gate_passed": True},
    {"code": "E", "grade": "·", "score_flash": 80.0, "pri": 55.0, "gate_passed": True},
]
LOW_MID = [
    {"code": "F", "grade": "·", "score_flash": 61.0, "pri": 50.0, "gate_passed": True},
    {"code": "G", "grade": "✕", "score_flash": 58.0, "pri": 80.0, "gate_passed": True},
]
FAILED = [
    {"code": "H", "grade": None, "score_flash": None, "pri": None, "gate_passed": False},
    {"code": "I", "grade": None, "score_flash": None, "pri": None, "gate_passed": None},
]
ALL = REAL_MISSED + HIGH_SCORE + LOW_MID + FAILED


def test_notify_grades_always_included_even_below_score_floor():
    """★★ A′ — 발송 등급은 스코어 하한과 **무관하게** 포함된다.

    하한을 75로 올려도 스코어 68.7·69.3·74.9인 ○가 남아야 한다.
    빠지면 "알림은 나가는데 해석이 없는" 종목이 생긴다.
    """
    picked = {r["code"] for r in _pick(ALL, top=1000, min_score=75)}
    for r in REAL_MISSED:
        assert r["code"] in picked, f"{r['code']}(○, 스코어 {r['score_flash']})가 빠졌다"


def test_every_notify_grade_is_covered_at_any_floor():
    """어떤 하한을 줘도 발송 등급은 하나도 안 빠져야 한다."""
    notify = {r["code"] for r in ALL if r.get("grade") in NOTIFY_GRADES}
    for floor in (0, 60, 75, 90, 100, 1000):
        picked = {r["code"] for r in _pick(ALL, top=1000, min_score=floor)}
        assert notify <= picked, f"하한 {floor}에서 발송 등급이 빠졌다: {notify - picked}"


def test_default_covers_all_gate_passed():
    """★ B — 기본값은 게이트 통과 **전부**를 담는다."""
    picked = _pick(ALL, top=DEFAULT_TOP, min_score=DEFAULT_MIN_SCORE)
    gate_passed = [r for r in ALL if r.get("gate_passed") is True]
    assert len(picked) == len(gate_passed)


def test_gate_failed_and_undecided_are_excluded():
    """탈락·판정불가는 대상이 아니다(ADR 3 — LLM은 통과 종목의 해석 전용)."""
    picked = {r["code"] for r in _pick(ALL, top=DEFAULT_TOP, min_score=0)}
    assert "H" not in picked and "I" not in picked


def test_attractiveness_puts_low_pri_first():
    """★ 시간·비용이 모자라 끊겨도 중요한 종목이 먼저 처리돼야 한다.

    같은 스코어면 반영도가 낮은 쪽(아직 안 오른 쪽)이 앞이다.
    """
    a = {"score_flash": 80.0, "pri": 10.0}
    b = {"score_flash": 80.0, "pri": 60.0}
    assert attractiveness(a) > attractiveness(b)


def test_attractiveness_none_when_unmeasured():
    """★ 0으로 채우면 측정 못 한 종목이 '매력 없음'으로 바뀐다."""
    assert attractiveness({"score_flash": None, "pri": 10.0}) is None
    assert attractiveness({"score_flash": 80.0, "pri": None}) is None


def test_unmeasured_sorted_last_not_dropped():
    """매력도가 없어도 **빠지지는 않는다** — 뒤로 갈 뿐이다."""
    rows = ALL + [
        {"code": "Z", "grade": "○", "score_flash": None, "pri": None, "gate_passed": True}
    ]
    picked = _pick(rows, top=1000, min_score=0)
    assert picked[-1]["code"] == "Z"
    assert "Z" in {r["code"] for r in picked}


def test_pick_matches_targets_source():
    """★ 위 `_pick`은 복제다. 실제 소스가 같은 조건을 갖고 있는지 확인한다.

    복제가 낡으면 테스트는 통과하는데 실물은 틀린다 — 가장 나쁜 형태다.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "src" / "analysis" / "batch.py").read_text(
        encoding="utf-8"
    )
    assert 'r["grade"] in NOTIFY_GRADES' in src, (
        "targets()가 발송 등급을 무조건 포함하지 않는다 — A′ 결함이 되살아났다"
    )
    assert 'r.get("gate_passed") is True' in src


def test_budget_covers_all_gate_passed_stocks():
    """★ 실측 단가로 게이트 통과 전부를 돌릴 수 있는 실링인가.

    캐시히트 $0.0315 · 238종목 = $7.50. 실링이 이보다 작으면 월중에 막힌다.
    """
    per_call = 0.0315
    quarter_cost = per_call * 238
    assert MONTHLY_COST_CEILING_USD >= quarter_cost, (
        f"실링 ${MONTHLY_COST_CEILING_USD}로는 238종목(${quarter_cost:.2f})을 못 돈다"
    )


def test_daily_limit_cannot_burn_ceiling_in_one_day():
    """★ 일 상한이 실링을 하루에 태우면 방어선이 없다."""
    per_call = 0.0363  # 미스 단가(보수적)
    assert DAILY_ANALYSIS_LIMIT * per_call < MONTHLY_COST_CEILING_USD


def test_time_budget_is_smaller_than_workflow_timeout():
    """★ 시간 예산이 워크플로 timeout보다 크면 **강제 종료**된다.

    강제 종료되면 진행 상황이 로그에 안 남아 어디까지 됐는지 모른다.
    """
    yaml = pytest.importorskip("yaml")
    from pathlib import Path
    import re

    root = Path(__file__).resolve().parents[1] / ".github" / "workflows"
    for name in ("disclosure_poll.yml", "llm_batch.yml"):
        body = (root / name).read_text(encoding="utf-8")
        if "analysis.batch" not in body:
            continue
        spec = yaml.safe_load(body)
        for job in (spec.get("jobs") or {}).values():
            timeout_sec = int(job["timeout-minutes"]) * 60
            for secs in re.findall(r"--max-seconds (\d+)", body):
                assert int(secs) < timeout_sec, (
                    f"{name}: --max-seconds {secs} >= timeout {timeout_sec}초"
                )


def test_default_max_seconds_is_set():
    assert DEFAULT_MAX_SECONDS > 0
    # 기본 10분은 disclosure_poll(15분)에도 들어간다.
    assert DEFAULT_MAX_SECONDS <= 15 * 60


# ── 진행 리포트 (2026-08-17) ──────────────────────────────────────
# ★ 배치는 DB에만 쓰므로 커밋할 파일이 없다. 밤마다 도는 따라잡기가 어디까지
#   갔는지 알 방법이 Actions 로그뿐이었다 → 잡 요약 + (사건일 때만) 텔레그램.


def test_job_summary_appends_when_env_set(tmp_path, monkeypatch):
    from src.analysis.batch import write_job_summary

    path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(path))
    assert write_job_summary(["첫 줄", "둘째 줄"]) is True
    assert write_job_summary(["셋째 줄"]) is True  # append — 덮어쓰지 않는다
    body = path.read_text(encoding="utf-8")
    assert "첫 줄" in body and "셋째 줄" in body


def test_job_summary_is_silent_without_env(monkeypatch):
    """로컬 실행에서 요약을 못 쓴다고 배치가 죽으면 안 된다."""
    from src.analysis.batch import write_job_summary

    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert write_job_summary(["아무거나"]) is False


def test_job_summary_survives_bad_path(monkeypatch, tmp_path):
    """경로가 틀려도 분석은 이미 끝났다 — 예외를 밖으로 내보내지 않는다."""
    from src.analysis.batch import write_job_summary

    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "없는폴더" / "s.md"))
    assert write_job_summary(["x"]) is False


def test_notify_progress_never_raises(monkeypatch):
    """텔레그램이 죽어도 배치 결과(이미 DB에 있다)를 실패로 만들지 않는다."""
    from src.analysis import batch

    import src.notify.telegram as tg

    def boom(*_a, **_k):
        raise RuntimeError("텔레그램 다운")

    monkeypatch.setattr(tg, "TelegramClient", boom)
    assert batch.notify_progress("테스트") is False


def test_telegram_notice_is_event_driven_not_daily():
    """★ 매일 밤 같은 진행 메시지를 보내면 알림이 소음이 되고 종목 알림을 덮는다.

    통지는 **사건일 때만** 나가야 한다: 전부 끝남 / 비용 상한 / 실패 다수.
    따라잡기가 끝난 뒤 매일 들어오는 `not pending` 경로에는 통지가 없어야 한다.
    """
    import ast

    src = Path(__file__).resolve().parents[1] / "src" / "analysis" / "batch.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    run = next(n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "run")

    # `not pending` 조기 반환 블록 안에 notify_progress가 있으면 매일 발송된다.
    for node in ast.walk(run):
        if not (isinstance(node, ast.If) and isinstance(node.test, ast.UnaryOp)
                and isinstance(node.test.op, ast.Not)):
            continue
        if not (isinstance(node.test.operand, ast.Name)
                and node.test.operand.id == "pending"):
            continue
        calls = [c for c in ast.walk(node)
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]
        names = {c.func.id for c in calls}
        assert "notify_progress" not in names, (
            "따라잡기 완료 후 매일 밤 이 경로로 들어온다 — 여기서 보내면 매일 온다"
        )
        assert "write_job_summary" in names, "요약은 남겨야 진행 상황이 보인다"
        break
    else:
        raise AssertionError("`if not pending:` 조기 반환을 찾지 못했다")


def test_llm_batch_workflow_has_telegram_secrets():
    """통지를 코드에 넣고 워크플로에 시크릿을 안 주면 **조용히 안 간다**(T51 모양)."""
    import yaml

    path = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "llm_batch.yml"
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    env = spec["jobs"]["run"]["env"]
    assert "HEIMDALLR_TELEGRAM_BOT_TOKEN" in env
    assert "HEIMDALLR_TELEGRAM_CHAT_ID" in env
