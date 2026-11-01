# PRD Ref: §7/9 · ADR50 — no network/model calls in queue replay.
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.analysis import pro_worker as worker
from src.llm.subscription import SubscriptionWait, write_json


def job(identity="current", **fields):
    return {"id": identity, "kind": "company", "target": identity, "historical": False,
            "status": "pending", "requested_at": "2026-11-01T00:00:00+00:00", **fields}


@pytest.fixture
def replay(tmp_path, monkeypatch):
    import src.db.supabase_client as db_module
    rows, updates = [], []
    class DB:
        def table(self, name): return self
        def update(self, values): updates.append(values); return self
        def eq(self, *args): return self
        def execute(self): return SimpleNamespace(data=[{"id": "claimed"}])
    monkeypatch.setattr(worker, "STATE", tmp_path)
    monkeypatch.setattr(worker, "get_client", DB)
    monkeypatch.setattr(db_module, "select_all", lambda table, columns, **kw: [r for r in rows if r['status']==kw['filters']['status']])
    return rows, updates, tmp_path


def test_current_manual_request_precedes_historical_backfill(replay, monkeypatch):
    rows, updates, _ = replay
    rows.extend([job("old", historical=True), job("manual")])
    seen=[]
    monkeypatch.setattr(worker, "company", lambda j: seen.append(j["target"]) or {"evidence_hash":"facts"})
    assert worker.run_once()["status"] == "completed"
    assert seen == ["manual"]


def test_usage_wait_keeps_request_and_explicit_reset(replay, monkeypatch):
    rows, updates, _ = replay;rows.append(job())
    retry=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    monkeypatch.setattr(worker,"company",lambda j: (_ for _ in ()).throw(SubscriptionWait("USAGE",retry)))
    result=worker.run_once()
    assert result["status"]=="deferred" and result["retry_after"]==retry
    assert not any(u.get("status")=="completed" for u in updates)


def test_delivery_retry_uses_saved_result_without_model(replay, monkeypatch):
    rows, _, root = replay;row=job();rows.append(row)
    write_json(root/"jobs/current.json",{"requested_at":row["requested_at"],"result":{"evidence_hash":"saved"}})
    monkeypatch.setattr(worker,"company",lambda j:pytest.fail("must not regenerate a saved result"))
    assert worker.run_once()["evidence_hash"]=="saved"


def test_invalid_result_does_not_complete_request(replay, monkeypatch):
    rows, updates, _ = replay;rows.append(job())
    monkeypatch.setattr(worker,"company",lambda j:(_ for _ in ()).throw(ValueError("PRO_RESULT_INVALID")))
    assert worker.run_once()["status"]=="failed"
    assert not any(u.get("status")=="completed" for u in updates)


def test_unknown_foreign_working_job_is_not_restarted(replay, monkeypatch):
    rows, updates, _ = replay;rows.append(job(status="working"))
    monkeypatch.setattr(worker,"company",lambda j:pytest.fail("must not take someone else's working job"))
    assert worker.run_once()["status"]=="idle" and not updates


def test_locally_claimed_interrupted_job_resumes(replay, monkeypatch):
    rows, _, root = replay;row=job(status="working");rows.append(row)
    write_json(root/"jobs/current-claim.json",{"requested_at":row["requested_at"]})
    monkeypatch.setattr(worker,"company",lambda j:{"evidence_hash":"recovered"})
    assert worker.run_once()["status"]=="completed"


def test_known_quota_wait_does_not_claim_or_call_model(replay, monkeypatch):
    rows, updates, root = replay;rows.append(job())
    write_json(root/"usage-wait.json",{"retry_at":(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()})
    monkeypatch.setattr(worker,"company",lambda j:pytest.fail("known usage wait"))
    assert worker.run_once()["model_calls"]==0 and not updates
