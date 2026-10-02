# PRD Ref: §8.4, §8.8, §10 · traps.md T228
"""정시 시작(pg_cron → workflow_dispatch) + 예비 schedule이 같은 날 둘 다 돌 때의 멱등.

★ 10/1까지 📊일일 요약은 **하루 세 번** 나갔다(9/22~10/1 notifications id 182~207).
  `send_once`는 code가 None이면 중복 검사를 건너뛰고, UNIQUE(code, …)는 NULL끼리 다르다.
  워크플로 주석은 "notifications가 막는다"고 적고 있었다 — 아무것도 막고 있지 않았다.

외부 I/O는 전부 스텁으로 막는다.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.notify import batch
from src.notify.entry_checks_run import keep_complete_rows

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parents[1]
SQL = ROOT / "docs" / "migrations" / "cron_dispatch.sql"
WORKFLOW = ROOT / ".github" / "workflows" / "daily_digest.yml"


# ═══ digest_day — 16:00 KST 경계 ═══════════════════════════════════
@pytest.mark.parametrize(
    "kst, expected",
    [
        ("2026-10-01 17:37", "2026-10-01"),  # 정시
        ("2026-10-02 00:37", "2026-10-01"),  # 실측 7시간 지연분 — 전날 요약이다
        ("2026-10-02 06:32", "2026-10-01"),  # 10/1 entry_checks가 실제로 계산된 시각
        ("2026-10-02 15:59", "2026-10-01"),  # 장 확정 전 — 아직 오늘 몫이 아니다
        ("2026-10-02 16:00", "2026-10-02"),
        ("2026-10-02 19:07", "2026-10-02"),
    ],
)
def test_digest_day_rolls_over_at_confirmed_close(kst: str, expected: str):
    now = datetime.strptime(kst, "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    assert batch.digest_day(now).isoformat() == expected


def test_digest_day_is_timezone_safe():
    """러너는 UTC다. 같은 순간이면 같은 답이어야 한다."""
    utc = datetime(2026, 10, 1, 15, 37, tzinfo=ZoneInfo("UTC"))  # = 10/2 00:37 KST
    assert batch.digest_day(utc).isoformat() == "2026-10-01"


# ═══ 완료 판정 ══════════════════════════════════════════════════════
def test_entry_state_ignores_other_runs_summary():
    summary = {"date": "2026-10-01", "status": "complete", "check_date": "2026-10-01", "saved": 1152}
    assert batch.entry_checks_state(summary, "2026-10-02") == {"status": "missing"}
    assert batch.entry_checks_state(None, "2026-10-02") == {"status": "missing"}
    assert batch.entry_checks_state(summary, "2026-10-01") == {
        "status": "complete", "check_date": "2026-10-01", "saved": 1152,
    }


@pytest.mark.parametrize(
    "state, done",
    [
        ({"status": "complete", "saved": 1152}, True),
        ({"status": "complete", "saved": 0}, False),          # dry-run·저장 0행은 완료가 아니다
        ({"status": "scan_degraded", "saved": 1152}, False),   # 일봉 실패율 초과 → 재시도해야 한다
        ({"status": "calendar_failed"}, False),
        ({"status": "missing"}, False),
        (None, False),                                         # 옛 요약 행(표식 없음)
    ],
)
def test_day_complete(state, done):
    row = {"payload": {"entry_checks": state}} if state is not None else {"payload": {}}
    assert batch.day_complete(row) is done
    assert batch.day_complete(None) is False


# ═══ 📊 요약 1일 1회 ════════════════════════════════════════════════
@pytest.fixture
def digest(monkeypatch, tmp_path):
    """run_digest의 DB·텔레그램을 스텁으로. 반환: 호출 기록."""
    calls: dict[str, list] = {"send": [], "update": []}
    monkeypatch.setattr(batch, "select_all", lambda *a, **k: [])
    monkeypatch.setattr(batch, "latest_screens", lambda: [])
    monkeypatch.setattr(batch, "notify_targets", lambda: [])
    monkeypatch.setattr(batch, "revenue_yoy_map", lambda targets: {})
    monkeypatch.setattr(batch, "TelegramClient", lambda: object())
    monkeypatch.setattr(
        batch, "send_once", lambda client, **kw: calls["send"].append(kw) or True,
    )

    class _Query:
        def __init__(self, payload):
            self.payload = payload

        def update(self, payload):
            return _Query(payload)

        def eq(self, column, value):
            calls["update"].append((self.payload, column, value))
            return self

        def execute(self):
            return self

    class _Client:
        def table(self, name):
            assert name == "notifications"
            return _Query(None)

    monkeypatch.setattr(batch, "get_client", lambda: _Client())
    entry = tmp_path / "entry-checks.json"
    monkeypatch.setenv("ENTRY_CHECKS_SUMMARY_PATH", str(entry))
    monkeypatch.delenv("TECHNICAL_SCAN_SUMMARY_PATH", raising=False)
    calls["entry_path"] = entry
    return calls


def _write_entry(path: Path, status: str, saved: int) -> None:
    import json

    today = datetime.now(KST).date().isoformat()
    path.write_text(json.dumps({"date": today, "status": status, "check_date": today, "saved": saved}), "utf-8")


def test_first_digest_is_sent_with_day_marker(monkeypatch, digest):
    monkeypatch.setattr(batch, "find_daily", lambda day: None)
    _write_entry(digest["entry_path"], "complete", 1152)
    assert batch.run_digest(send=True) == 0
    assert len(digest["send"]) == 1
    payload = digest["send"][0]["payload"]
    assert payload["digest_date"] == batch.digest_day(datetime.now(KST)).isoformat()
    assert payload["entry_checks"]["status"] == "complete"


def test_second_run_same_day_never_resends(monkeypatch, digest):
    """★ 핵심 계약: 예비 schedule이 뒤늦게 돌아도 텔레그램은 다시 안 나간다."""
    existing = {"id": 207, "payload": {"digest_date": "x", "entry_checks": {"status": "complete", "saved": 1152}}}
    monkeypatch.setattr(batch, "find_daily", lambda day: existing)
    _write_entry(digest["entry_path"], "complete", 1152)
    assert batch.run_digest(send=True) == 0
    assert digest["send"] == []
    assert digest["update"] == []


def test_retry_completes_marker_without_resending(monkeypatch, digest):
    """앞 실행이 entry_checks 실패 상태로 요약만 보냈으면, 재시도는 표식만 완료로 고친다."""
    existing = {"id": 207, "payload": {"digest_date": "d", "gate_passed": 3,
                                        "entry_checks": {"status": "scan_degraded", "saved": 1152}}}
    monkeypatch.setattr(batch, "find_daily", lambda day: existing)
    _write_entry(digest["entry_path"], "complete", 1152)
    assert batch.run_digest(send=True) == 0
    assert digest["send"] == []
    [(payload, column, value)] = digest["update"]
    assert (column, value) == ("id", 207)
    assert payload["payload"]["entry_checks"]["status"] == "complete"
    assert payload["payload"]["gate_passed"] == 3, "기존 payload를 지우면 안 된다"


def test_dry_digest_touches_nothing(monkeypatch, digest):
    def _boom(day):
        raise AssertionError("--send 없이 DB를 읽었다")

    monkeypatch.setattr(batch, "find_daily", _boom)
    assert batch.run_digest(send=False) == 0
    assert digest["send"] == [] and digest["update"] == []


def test_send_once_still_skips_check_for_codeless_kinds():
    """★ 이 테스트가 깨지면(= send_once가 code=None도 막게 되면) find_daily와 겹친다 — 정리하라.

    지금은 요약의 중복 방어가 **find_daily 한 곳**이라는 사실을 못박는다.
    """
    import inspect

    from src.notify import telegram

    source = inspect.getsource(telegram.send_once)
    assert "if code is not None and fiscal_year is not None and fiscal_quarter is not None:" in source
    assert "batch.find_daily(day)" not in source
    assert "existing = find_daily(day)" in inspect.getsource(batch.run_digest)


# ═══ 게이트 ═════════════════════════════════════════════════════════
def test_gate_skips_only_when_day_is_complete(monkeypatch, tmp_path):
    out = tmp_path / "out"
    monkeypatch.setattr(
        batch, "find_daily",
        lambda day: {"id": 1, "payload": {"entry_checks": {"status": "complete", "saved": 10}}},
    )
    batch.run_digest_gate(str(out))
    monkeypatch.setattr(batch, "find_daily", lambda day: None)
    batch.run_digest_gate(str(out))
    assert out.read_text("utf-8").splitlines() == ["skip=true", "skip=false"]


def test_gate_fails_open(monkeypatch, tmp_path):
    """조회 실패로 그날 몫을 통째로 건너뛰면 안 된다 — 중복은 뒤 스텝이 막는다."""
    def _down(day):
        raise ConnectionError("supabase down")

    monkeypatch.setattr(batch, "find_daily", _down)
    out = tmp_path / "out"
    assert batch.run_digest_gate(str(out)) == 0
    assert out.read_text("utf-8").strip() == "skip=false"


# ═══ entry_checks 재실행이 완전한 행을 결측으로 덮지 않는다 ═══════════
def _row(code: str, stage: str, notes: list[str] | None = None, m2: bool | None = True) -> dict:
    detail = {"stage": stage}
    if notes:
        detail["notes"] = notes
    return {"code": code, "m1_detail": detail, "m2_pass": m2}


def test_failed_fetch_does_not_overwrite_complete_row():
    existing = [_row("A", "price"), _row("B", "price"), _row("C", "fundamental"),
                _row("D", "price", ["daily_fetch_failed"], None)]
    new = [
        _row("A", "fundamental", ["daily_fetch_failed"], None),  # 지킨다 — 앞 실행이 완전했다
        _row("B", "price", ["flow_fetch_failed"]),              # 지킨다 — 수급만 실패해도 결측이다
        _row("C", "fundamental", ["daily_fetch_failed"], None),  # 덮는다 — 앞 행이 일봉 단계가 아니었다
        _row("D", "fundamental", ["daily_fetch_failed"], None),  # 덮는다 — 앞 행도 실패였다
        _row("E", "fundamental", ["daily_fetch_failed"], None),  # 새 종목
        _row("F", "price", ["stale_bars"]),                     # 거래정지는 판정이지 원천 실패가 아니다
    ]
    kept, protected = keep_complete_rows(new, existing)
    assert [row["code"] for row in kept] == ["C", "D", "E", "F"]
    assert protected == 2


def test_complete_rerun_overwrites_everything():
    """원천을 다 받은 재실행은 그대로 덮는다 — 더 늦은(완전한) 수급을 봤을 수 있다."""
    existing = [_row("A", "price"), _row("B", "fundamental")]
    new = [_row("A", "price", m2=False), _row("B", "price")]
    kept, protected = keep_complete_rows(new, existing)
    assert kept == new and protected == 0


# ═══ SQL ↔ 워크플로 정합 ════════════════════════════════════════════
def _sql() -> str:
    return SQL.read_text(encoding="utf-8")


def _pg_cron_jobs() -> list[tuple[str, str, dict]]:
    import json

    pattern = re.compile(
        r"cron\.schedule\('([^']+)',\s*'([^']+)',\s*\$\$select heimdallr_ops\.dispatch_workflow\("
        r"'([a-z0-9_]+\.yml)',\s*'(\{[^']*\})'\)\$\$\)",
    )
    found = [(name, cron, workflow, json.loads(inputs)) for name, cron, workflow, inputs in pattern.findall(_sql())]
    assert len(found) == _sql().count("cron.schedule("), "정규식이 일부 잡을 놓쳤다 — 검사가 무력화된다(T54)"
    return [(name, cron, inputs) for name, cron, workflow, inputs in found if workflow == "daily_digest.yml"]


def _minutes(cron: str) -> int:
    minute, hour, *_ = cron.split()
    return int(hour) * 60 + int(minute)


def test_pg_cron_fires_before_jarvis_judgement():
    """정시 17:37 KST 1차, 마지막 재시도도 JARVIS 19:10 판정 전이다."""
    crons = [cron for _, cron, _ in _pg_cron_jobs()]
    assert crons == ["37 8 * * 1-5", "17 9 * * 1-5", "7 10 * * 1-5"]
    assert max(_minutes(c) for c in crons) < _minutes("10 10 * * *")


def test_schedule_is_backup_thirty_minutes_after_pg_cron():
    yaml = pytest.importorskip("yaml")
    spec = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    on = spec.get(True) or spec.get("on")
    backups = [_minutes(row["cron"]) for row in on["schedule"]]
    primaries = [_minutes(cron) for _, cron, _ in _pg_cron_jobs()]
    assert backups == [m + 30 for m in primaries]


def test_dispatched_inputs_are_declared():
    """선언되지 않은 input을 보내면 GitHub가 422로 거절한다 — pg_cron은 에러 없이 응답만 쌓는다."""
    yaml = pytest.importorskip("yaml")
    spec = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    declared = set((spec.get(True) or spec.get("on"))["workflow_dispatch"]["inputs"])
    for name, _, inputs in _pg_cron_jobs():
        assert set(inputs) <= declared, f"{name}이 선언 안 된 input을 보낸다: {set(inputs) - declared}"
    test_line = re.search(r"dispatch_workflow\('daily_digest\.yml', '(\{[^']*\})'\);", _sql())
    assert test_line, "SQL 안내의 즉시 시험 줄이 사라졌다"
    import json

    assert set(json.loads(test_line.group(1))) <= declared


def test_sql_dispatches_main_of_this_repo_without_token():
    sql = _sql()
    assert "'ref', 'main'" in sql
    assert "repos/gotomirae/Heimdallr_Call/actions/workflows/" in sql
    assert "heimdallr_github_dispatch_token" in sql
    assert sql.count("'GITHUB_TOKEN_HERE'") >= 2, "토큰 자리표시자가 사라졌다 — 실제 토큰이 커밋됐을 수 있다"
    assert not re.search(r"github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}", sql), "토큰이 파일에 있다"
    # anon이 RPC로 워크플로를 띄우지 못하게 — 노출 안 되는 스키마 + 권한 회수
    assert "create or replace function heimdallr_ops.dispatch_workflow" in sql
    assert "revoke all on function heimdallr_ops.dispatch_workflow(text, jsonb) from public, anon, authenticated" in sql


def test_every_digest_step_after_gate_is_gated():
    """게이트가 skip=true인데 스텝 하나라도 돌면 그 스텝은 하루 6번 돈다."""
    yaml = pytest.importorskip("yaml")
    steps = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["digest"]["steps"]
    index = next(i for i, step in enumerate(steps) if step.get("id") == "gate")
    gate_run = steps[index]["run"]
    assert "--digest-gate --gate-output \"$GITHUB_OUTPUT\" || echo \"skip=false\"" in gate_run, (
        "게이트 스텝이 실패하면 뒤 스텝의 암묵적 success()가 entry_checks를 건너뛴다 — 셸에서 fail-open"
    )
    assert "continue-on-error" not in steps[index]
    after = steps[index + 1:]
    assert len(after) == 3
    for step in after:
        assert "steps.gate.outputs.skip != 'true'" in str(step.get("if")), step.get("name")
