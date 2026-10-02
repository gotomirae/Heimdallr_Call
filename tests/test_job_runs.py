# PRD Ref: §10 · traps.md T217, T229
"""universe_daily 정시 시작(pg_cron) + 예비 schedule의 게이트. 외부 I/O 없음.

★ 06:00 KST 예약이 9/28~10/2 내내 08:41~09:51에 시작해 장중가가 종가로 저장됐다(T217).
  pg_cron으로 정시에 띄워도, 실행이 길어져 09:00을 넘기면 `price_run`이 **시작 시각의 날짜로**
  장중가를 저장한다 — 게이트가 '장 시작 전에 끝날 수 있는가'를 같이 봐야 하는 이유다.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.db import job_runs

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "docs" / "migrations" / "cron_universe_daily.sql"
WORKFLOW = ROOT / ".github" / "workflows" / "universe_daily.yml"


def _at(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=KST)


@pytest.mark.parametrize(
    "kst, unsafe",
    [
        ("2026-10-06 06:00", False),  # 화 · 정시 — 07:30 종료
        ("2026-10-06 07:30", False),  # 09:00 정각 종료 — 경계는 안전
        ("2026-10-06 07:31", True),
        ("2026-10-06 09:35", True),   # 실측 지연 시작 시각
        ("2026-10-06 15:59", True),
        ("2026-10-06 16:00", False),  # 확정 종가
        ("2026-10-06 16:30", False),  # 보충 슬롯
        ("2026-10-06 23:00", False),
        ("2026-10-03 10:00", False),  # 토요일
        ("2026-10-04 12:00", False),  # 일요일
    ],
)
def test_unsafe_start_window(kst: str, unsafe: bool):
    assert job_runs.unsafe_start(_at(kst), 90) is unsafe


def test_unsafe_start_is_timezone_safe():
    """러너는 UTC다. 00:35 UTC = 09:35 KST(평일)는 위험이다."""
    assert job_runs.unsafe_start(datetime(2026, 10, 6, 0, 35, tzinfo=ZoneInfo("UTC")), 90) is True
    assert job_runs.run_day(datetime(2026, 10, 5, 21, 0, tzinfo=ZoneInfo("UTC"))).isoformat() == "2026-10-06"


@pytest.mark.parametrize(
    "complete, kst, skip",
    [
        (True, "2026-10-06 06:30", True),    # 정시 실행 완료 뒤 예비
        (False, "2026-10-06 06:30", False),  # 정시 실행 실패 → 예비가 메운다
        (False, "2026-10-06 10:00", True),   # 지연된 예비가 장중에 도착 → 거부
        (False, "2026-10-06 16:30", False),  # 보충
        (True, "2026-10-06 16:30", True),
    ],
)
def test_gate_decision(complete: bool, kst: str, skip: bool):
    assert job_runs.gate_decision(complete, _at(kst), 95)[0] is skip


def test_gate_fails_open(monkeypatch, tmp_path):
    def _down(job, day):
        raise ConnectionError("no table")

    monkeypatch.setattr(job_runs, "is_complete", _down)
    monkeypatch.setattr(job_runs, "unsafe_start", lambda now, minutes: False)
    out = tmp_path / "out"
    assert job_runs.gate("universe_daily", 95, str(out)) == 0
    assert out.read_text("utf-8").strip() == "skip=false"


def test_done_never_fails_the_job(monkeypatch):
    def _down(*a, **k):
        raise ConnectionError("no table")

    monkeypatch.setattr(job_runs, "mark_complete", _down)
    assert job_runs.done("universe_daily") == 0


# ═══ SQL ↔ 워크플로 정합 ════════════════════════════════════════════
def _minutes(cron: str) -> int:
    minute, hour, *_ = cron.split()
    return int(hour) * 60 + int(minute)


def _pg_cron_jobs() -> list[tuple[str, str, dict]]:
    sql = SQL.read_text(encoding="utf-8")
    pattern = re.compile(
        r"cron\.schedule\('([^']+)',\s*'([^']+)',\s*\$\$select heimdallr_ops\.dispatch_workflow\("
        r"'universe_daily\.yml',\s*'(\{[^']*\})'\)\$\$\)",
    )
    found = [(name, cron, json.loads(inputs)) for name, cron, inputs in pattern.findall(sql)]
    assert len(found) == sql.count("cron.schedule("), "정규식이 일부 잡을 놓쳤다 — 검사가 무력화된다(T54)"
    return found


def _spec() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_pg_cron_slots_are_outside_market_hours():
    crons = [cron for _, cron, _ in _pg_cron_jobs()]
    assert crons == ["0 21 * * *", "30 7 * * *"]  # 06:00 · 16:30 KST
    for cron in crons:
        minute, hour = int(cron.split()[0]), int(cron.split()[1])
        kst = datetime(2026, 10, 6, (hour + 9) % 24, minute, tzinfo=KST)
        assert not job_runs.unsafe_start(kst, 95), f"{cron}은 게이트가 스스로 거부하는 시각이다"


def test_schedule_is_backup_thirty_minutes_after_pg_cron():
    on = _spec().get(True) or _spec().get("on")
    backups = [_minutes(row["cron"]) for row in on["schedule"]]
    primaries = [_minutes(cron) for _, cron, _ in _pg_cron_jobs()]
    assert backups == [(m + 30) % (24 * 60) for m in primaries]


def test_dispatched_inputs_are_declared():
    """선언되지 않은 input을 보내면 GitHub가 422로 거절한다."""
    declared = set((_spec().get(True) or _spec().get("on"))["workflow_dispatch"]["inputs"])
    for name, _, inputs in _pg_cron_jobs():
        assert set(inputs) <= declared, f"{name}: {set(inputs) - declared}"


def test_gate_margin_covers_refresh_timeout():
    """게이트가 장중 겹침을 재는 시간 ≥ refresh 제한시간 + 5분(gate 잡 소요)."""
    jobs = _spec()["jobs"]
    gate_run = next(step["run"] for step in jobs["gate"]["steps"] if step.get("id") == "gate")
    margin = int(re.search(r"--timeout-minutes (\d+)", gate_run).group(1))
    assert margin >= jobs["refresh"]["timeout-minutes"] + 5
    assert '|| echo "skip=false"' in gate_run, "게이트가 죽으면 refresh가 통째로 건너뛰어진다 — fail-open"


def test_refresh_waits_for_gate_and_marks_done_last():
    jobs = _spec()["jobs"]
    refresh = jobs["refresh"]
    assert refresh["needs"] == "gate"
    assert refresh["if"] == "needs.gate.outputs.skip != 'true'"
    assert jobs["gate"]["outputs"]["skip"] == "${{ steps.gate.outputs.skip }}"
    last = refresh["steps"][-1]
    assert "python -m src.db.job_runs done --job universe_daily" in last["run"]
    assert "if" not in last and "continue-on-error" not in last, "필수 스텝이 실패하면 표식이 남으면 안 된다"


def test_sql_creates_private_marker_table():
    sql = SQL.read_text(encoding="utf-8")
    assert "create table if not exists public.job_runs" in sql
    assert "primary key (job, run_day)" in sql
    assert "enable row level security" in sql
    assert "create policy" not in sql.lower(), "job_runs는 anon에 열지 않는다"
