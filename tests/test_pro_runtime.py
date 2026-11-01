# PRD Ref: §7/9/10 · ADR50
from datetime import date, datetime, timedelta, timezone
import json
from types import SimpleNamespace

import pytest

from src.utils import operating_calendar as calendar
from src.llm import subscription


@pytest.mark.parametrize("day,expected", [("2026-11-01", False), ("2026-10-31", False),
    ("2026-01-01", False), ("2026-08-17", False), ("2026-11-02", True)])
def test_calendar_weekends_holidays_substitute_and_workday(day, expected):
    assert calendar.indicator_day(date.fromisoformat(day)) is expected


def test_1600_kst_boundary_not_host_time():
    assert not calendar.indicators_due(datetime(2026, 11, 2, 6, 59, tzinfo=timezone.utc))
    assert calendar.indicators_due(datetime(2026, 11, 2, 7, 0, tzinfo=timezone.utc))
    assert not calendar.indicators_due(datetime(2026, 11, 1, 7, 0, tzinfo=timezone.utc))


def test_new_temporary_holiday_override(monkeypatch):
    monkeypatch.setattr(calendar, "KOREA_EXTRA_HOLIDAYS", ("2026-11-02",))
    assert not calendar.indicator_day(date(2026, 11, 2))


def test_season_includes_annual_report_window():
    assert calendar.earnings_season(date(2026, 3, 31))
    assert not calendar.earnings_season(date(2026, 6, 1))


def test_api_providers_fail_before_client_or_network():
    from src.llm.registry import resolve_provider
    from src.llm.providers.anthropic import AnthropicProvider
    from src.llm.providers.openai import OpenAIProvider
    assert resolve_provider()[0].name == "codex_subscription"
    for name in ("openai", "anthropic"):
        with pytest.raises(ValueError, match="API_DISABLED"):
            resolve_provider(name)
    for provider in (AnthropicProvider(), OpenAIProvider()):
        with pytest.raises(RuntimeError, match="API_DISABLED"):
            provider._client()


def test_child_environment_never_inherits_api_keys(monkeypatch):
    from src.utils.env import codex_subscription_env
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.setenv(key, "must-not-inherit")
    env = codex_subscription_env()
    assert not any(key in env for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_BASE_URL"))


def test_quota_wait_and_successful_checkpoint_make_zero_cli_calls(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("CLI must not be contacted")
    monkeypatch.setattr(subscription, "cli_path", forbidden)
    subscription.write_json(tmp_path / "usage-wait.json", {"retry_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
    with pytest.raises(subscription.SubscriptionWait, match="USAGE"):
        subscription.execute("prompt", {}, key="test", phase="draft", root=tmp_path)


def test_saved_stage_reused_without_auth_or_model(tmp_path, monkeypatch):
    import hashlib
    folder = tmp_path / hashlib.sha256(b"test").hexdigest() / "draft"
    subscription.write_json(folder / "checkpoint.json", {"status": "completed"})
    subscription.write_json(folder / "result.json", {"report": "saved"})
    monkeypatch.setattr(subscription, "cli_path", lambda: pytest.fail("No CLI on cached stage"))
    assert subscription.execute("prompt", {}, key="test", phase="draft", root=tmp_path) == {"report": "saved"}


def test_cli_is_forced_to_chatgpt_and_api_environment_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(subscription, "cli_path", lambda: "codex")
    monkeypatch.setattr(subscription, "require_chatgpt", lambda cli: None)
    seen = []
    class Process:
        pid = 123
        returncode = 0
        def __init__(self, args, **kwargs):
            seen.append((args, kwargs))
            self.args, self.stdout = args, kwargs["stdout"]
        def communicate(self, prompt, timeout):
            from pathlib import Path
            Path(self.args[self.args.index("--output-last-message") + 1]).write_text('{"report":"verified"}', encoding="utf-8")
            self.stdout.write('{"type":"thread.started","thread_id":"same-session"}\n')
            self.stdout.flush()
    monkeypatch.setattr(subscription.subprocess, "Popen", Process)
    value = subscription.execute("task", {}, key="test", phase="draft", root=tmp_path)
    assert value["report"] == "verified"
    assert 'forced_login_method="chatgpt"' in seen[0][0]
    assert "OPENAI_API_KEY" not in seen[0][1]["env"]
    assert subscription.execute("task", {}, key="test", phase="draft", root=tmp_path) == value
    assert len(seen) == 1


def test_price_change_does_not_change_report_evidence():
    from src.analysis.pro_worker import evidence_hash
    data = SimpleNamespace(quarters=[], excerpt="same filing", disclosures=[], is_estimate=False, price={"close": 100})
    before = evidence_hash(data)
    data.price = {"close": 200}
    assert evidence_hash(data) == before
    data.disclosures = [{"rcept_no": "new-important-filing"}]
    assert evidence_hash(data) != before


def test_empty_queue_has_zero_model_or_auth_calls(monkeypatch):
    from src.analysis import pro_worker
    import src.db.supabase_client as db
    monkeypatch.setattr(pro_worker, "get_client", lambda: object())
    monkeypatch.setattr(db, "select_all", lambda *args, **kwargs: [])
    monkeypatch.setattr(pro_worker, "execute", lambda *args, **kwargs: pytest.fail("Empty queue model call"))
    assert pro_worker.run_once() == {"status": "idle", "model_calls": 0}


def test_scheduled_workflows_have_no_api_model_credentials():
    from pathlib import Path
    import yaml
    root = Path(__file__).resolve().parents[1]
    for path in (root / ".github/workflows").glob("*.yml"):
        body = path.read_text(encoding="utf-8")
        spec = yaml.safe_load(body)
        if not (spec.get("on", spec.get(True, {})) or {}).get("schedule"):
            continue
        assert "ANTHROPIC_API_KEY" not in body and "OPENAI_API_KEY" not in body
        assert "src.analysis.batch" not in body and "src.analysis.dashboard_requests" not in body
