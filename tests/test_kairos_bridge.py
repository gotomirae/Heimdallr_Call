# PRD Ref: §8 · SC: 클라우드 수신함→로컬 큐→Codex→검증된 Notion 링크
"""Telegram getUpdates 없이 Kairos 작업을 넘기는 브리지 검증."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.db.supabase_client import service_error_code
from telegram_bridge import bridge


def test_poll_read_only_does_not_initialize_or_modify_queue(db):
    insert_job(db)
    before = bridge.STATE.read_bytes()
    reader = bridge.connect(read_only=True)
    try:
        assert bridge.poll(reader)["jobs"][0]["id"] == 42
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.execute("DELETE FROM jobs")
    finally:
        reader.close()
    assert bridge.STATE.read_bytes() == before


def test_read_only_missing_queue_does_not_create_empty_database(tmp_path, monkeypatch):
    path = tmp_path / "missing" / "queue.sqlite3"
    monkeypatch.setattr(bridge, "STATE", path)
    with pytest.raises(sqlite3.OperationalError):
        bridge.connect(read_only=True)
    assert not path.parent.exists()


def test_quota_error_is_actionable_without_exposing_raw_details():
    from postgrest.exceptions import APIError

    error = APIError({"message": "JSON could not be generated", "code": 402,
                      "hint": "details", "details": "exceed_egress_quota secret-value"})
    assert service_error_code(error) == "SUPABASE_EGRESS_QUOTA"
    other = APIError({"message": "secret-value", "code": "401", "details": "secret-value",
                      "hint": "secret-value"})
    assert service_error_code(other) == "APIError"


def test_listener_reuses_complete_catalog_and_refreshes_expired_cache(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    import json
    from telegram_bridge import listener_once

    monkeypatch.setattr(listener_once, "CATALOG", tmp_path / "catalog.json")
    fetch = Mock(return_value=({"005930": "삼성전자"}, {"반도체"}))
    monkeypatch.setattr(listener_once, "load_catalogs", fetch)
    for _ in range(60):
        assert listener_once.load_listener_catalogs() == ({"005930": "삼성전자"}, {"반도체"})
    assert fetch.call_count == 1
    cache = json.loads(listener_once.CATALOG.read_text(encoding="utf-8"))
    cache["checked_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    listener_once.CATALOG.write_text(json.dumps(cache), encoding="utf-8")
    fetch.side_effect = RuntimeError("DB unavailable")
    with pytest.raises(RuntimeError, match="DB unavailable"):
        listener_once.load_listener_catalogs()
    assert fetch.call_count == 2


def test_listener_database_failure_does_not_consume_telegram_updates(tmp_path, monkeypatch):
    from postgrest.exceptions import APIError
    from telegram_bridge import listener_once
    import json

    monkeypatch.setattr(listener_once, "HEALTH", tmp_path / "health.json")
    monkeypatch.setattr(listener_once, "TelegramClient", lambda: SimpleNamespace(token="test"))
    monkeypatch.setattr(listener_once, "bot_id_of", lambda _: listener_once.HEIMDALLR_BOT_ID)
    monkeypatch.setattr(listener_once, "allowed_chats", lambda: {"111"})
    error = APIError({"message": "restricted", "code": 402, "hint": "",
                      "details": "exceed_egress_quota"})
    monkeypatch.setattr(listener_once, "load_listener_catalogs", Mock(side_effect=error))
    receive = Mock()
    monkeypatch.setattr(listener_once, "poll_once", receive)
    assert listener_once.main() == 1
    receive.assert_not_called()
    assert json.loads(listener_once.HEALTH.read_text())["last_error"] == "SUPABASE_EGRESS_QUOTA"


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "STATE", tmp_path / "queue.sqlite3")
    connection = bridge.connect()
    yield connection
    connection.close()


def insert_job(db, status="pending"):
    with db:
        db.execute(
            "INSERT INTO jobs(id,code,company,raw_text,chat_id,status) VALUES(?,?,?,?,?,?)",
            (42, "005930", "삼성전자", "삼성전자", 111, status),
        )


def insert_industry_job(db, status="pending"):
    with db:
        db.execute(
            "INSERT INTO jobs(id,code,company,request_kind,target_name,raw_text,chat_id,status) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (43, "", "반도체", "industry", "반도체", "반도체", 111, status),
        )


def test_sync_requires_right_bot_and_owner(db, monkeypatch):
    monkeypatch.setattr(bridge, "verify_bot", lambda: None)
    monkeypatch.setattr(bridge, "allowed_chats", lambda: {"111"})
    rows = [
        {"update_id": 42, "chat_id": 111, "user_id": 111, "code": "005930",
         "company_name": "삼성전자", "raw_text": "삼성전자"},
        {"update_id": 43, "chat_id": 111, "user_id": 222, "code": "005930",
         "company_name": "삼성전자", "raw_text": "삼성전자"},
    ]
    monkeypatch.setattr(bridge, "select_all", lambda *a, **k: rows)
    assert bridge.sync_pending(db) == 1
    assert bridge.sync_pending(db) == 0
    assert [r[0] for r in db.execute("SELECT id FROM jobs")] == [42]


def test_sync_accepts_industry_without_stock_code(db, monkeypatch):
    monkeypatch.setattr(bridge, "verify_bot", lambda: None)
    monkeypatch.setattr(bridge, "allowed_chats", lambda: {"111"})
    monkeypatch.setattr(bridge, "select_all", lambda *a, **k: [{
        "update_id": 43, "chat_id": 111, "user_id": 111,
        "request_kind": "industry", "target_name": "반도체", "code": None,
        "company_name": None, "industry": "반도체", "raw_text": "반도체",
        "telegram_message_id": 56,
    }])
    assert bridge.sync_pending(db) == 1
    row = db.execute(
        "SELECT request_kind,target_name,code FROM jobs WHERE id=43"
    ).fetchone()
    assert tuple(row) == ("industry", "반도체", "")


def test_bridge_refuses_a_different_bot(monkeypatch):
    monkeypatch.setattr(bridge, "TelegramClient",
                        lambda: SimpleNamespace(token="8605695587:secret"))
    with pytest.raises(RuntimeError, match="HEIMDALLR_BOT_ID_MISMATCH"):
        bridge.verify_bot()


def test_python_dispatch_does_not_wake_a_model_and_preserves_claim(db, monkeypatch):
    insert_job(db)
    monkeypatch.setattr(bridge, "find_codex", lambda: pytest.fail("Python dispatch must not wake an app model"))
    assert bridge.wake_pending(db)=={"status":"python_queue","model_calls":0}
    assert bridge.wake_pending(db)=={"status":"python_queue","model_calls":0}
    assert db.execute("SELECT status FROM jobs WHERE id=42").fetchone()[0]=="pending"


def test_reconfiguring_trigger_requeues_pending_and_reports_freshness(db):
    insert_job(db)
    first = bridge.configure_trigger(db, "01a0b3d1-390f-7301-bd23-be3bdcda4329")
    with db:
        db.execute(
            "UPDATE jobs SET wake_sent=1,wake_sent_at='2026-09-26T00:00:00+00:00',"
            "wake_error='STALE' WHERE id=42"
        )

    second = bridge.configure_trigger(db, "01a0d886-422f-7971-8645-c2e387e817e2")

    assert first["requeued_pending"] == 0
    assert second["requeued_pending"] == 1
    assert tuple(db.execute(
        "SELECT wake_sent,wake_sent_at,wake_error FROM jobs WHERE id=42"
    ).fetchone()) == (0, None, None)
    status = bridge.poll(db)
    assert status["trigger_thread"] == "01a0d886-422f-7971-8645-c2e387e817e2"
    assert status["trigger_thread_updated_at"] == second["configured_at"]


def test_unclaimed_request_is_preserved_without_model_heartbeat(db, monkeypatch):
    insert_job(db)
    monkeypatch.setattr(bridge.subprocess, "run", lambda *a, **k: pytest.fail("no heartbeat subprocess"))
    assert bridge.wake_pending(db)["model_calls"]==0
    assert db.execute("SELECT wake_sent_at FROM jobs WHERE id=42").fetchone()[0] is None


def test_progress_edits_existing_receipt_once(db, monkeypatch):
    insert_job(db, "working")
    with db:
        db.execute("UPDATE jobs SET telegram_message_id=55 WHERE id=42")
    monkeypatch.setattr(bridge, "verify_bot", lambda: None)
    client = Mock()
    monkeypatch.setattr(bridge, "TelegramClient", lambda **k: client)
    assert bridge.set_progress(db, 42, "company")["stage"] == "company"
    assert bridge.set_progress(db, 42, "company")["stage"] == "company"
    assert client.call.call_count == 1
    assert client.call.call_args.args[0] == "editMessageText"
    assert client.call.call_args.args[1]["message_id"] == 55


def test_progress_is_recorded_even_when_telegram_edit_fails(db, monkeypatch):
    insert_job(db, "working")
    with db:
        db.execute("UPDATE jobs SET telegram_message_id=55 WHERE id=42")
    monkeypatch.setattr(bridge, "verify_bot", lambda: None)
    client = Mock()
    client.call.side_effect = RuntimeError("offline")
    monkeypatch.setattr(bridge, "TelegramClient", lambda **k: client)
    result = bridge.set_progress(db, 42, "web")
    assert result["telegram_updated"] is False
    assert result["telegram_error"] == "RuntimeError"
    assert db.execute(
        "SELECT progress_stage FROM jobs WHERE id=42"
    ).fetchone()[0] == "web"


def test_checkpoint_requires_working_job(db):
    insert_job(db)
    with pytest.raises(RuntimeError, match="NOT_WORKING"):
        bridge.ensure_checkpoint(db, 42)


def test_failed_delivery_is_uncertain_and_never_retried(db, monkeypatch):
    insert_job(db, "working")
    monkeypatch.setattr(bridge, "verify_bot", lambda: None)
    monkeypatch.setattr(bridge, "change_remote", lambda *a, **k: True)
    client = Mock()
    client.call.side_effect = RuntimeError("uncertain")
    monkeypatch.setattr(bridge, "TelegramClient", lambda **k: client)
    with pytest.raises(RuntimeError, match="uncertain"):
        bridge.deliver(db, 42, "https://app.notion.com/p/abc", "반도체")
    assert db.execute("SELECT status FROM jobs WHERE id=42").fetchone()[0] == "uncertain"
    with pytest.raises(RuntimeError, match="NOT_WORKING_OR_ALREADY_SENT"):
        bridge.deliver(db, 42, "https://app.notion.com/p/abc", "반도체")
    assert client.call.call_count == 1


def test_verified_link_delivery_marks_sent(db, monkeypatch):
    insert_job(db, "working")
    monkeypatch.setattr(bridge, "verify_bot", lambda: None)
    changes = []
    monkeypatch.setattr(bridge, "change_remote",
                        lambda *a, **k: changes.append((a, k)) or True)
    client = Mock()
    client.call.return_value = {"result": {"message_id": 77}}
    monkeypatch.setattr(bridge, "TelegramClient", lambda **k: client)
    result = bridge.deliver(db, 42, "https://app.notion.com/p/abc", "반도체")
    assert result["status"] == "sent"
    assert [item[0][2] for item in changes] == ["sending", "sent"]
    assert db.execute("SELECT status FROM jobs WHERE id=42").fetchone()[0] == "sent"
    payload = client.call.call_args.args[1]
    assert payload["reply_markup"]["inline_keyboard"][0][0]["url"] == "https://app.notion.com/p/abc"


def test_industry_delivery_uses_industry_layout_without_requiring_flag(db, monkeypatch):
    insert_industry_job(db, "working")
    monkeypatch.setattr(bridge, "verify_bot", lambda: None)
    monkeypatch.setattr(bridge, "change_remote", lambda *a, **k: True)
    client = Mock()
    client.call.return_value = {"result": {"message_id": 79}}
    monkeypatch.setattr(bridge, "TelegramClient", lambda **k: client)
    result = bridge.deliver(db, 43, "https://app.notion.com/p/industry")
    assert result["status"] == "sent"
    assert "산업 분석이 완료" in client.call.call_args.args[1]["text"]
    assert "기업:" not in client.call.call_args.args[1]["text"]


def test_failed_analysis_updates_status_and_explains_cause(db, monkeypatch):
    insert_industry_job(db, "working")
    with db:
        db.execute("UPDATE jobs SET telegram_message_id=56 WHERE id=43")
    monkeypatch.setattr(bridge, "verify_bot", lambda: None)
    monkeypatch.setattr(bridge, "change_remote", lambda *a, **k: True)
    client = Mock()
    monkeypatch.setattr(bridge, "TelegramClient", lambda **k: client)
    result = bridge.fail(db, 43, "NOTION_WRITE")
    assert result["status"] == "failed"
    assert db.execute("SELECT status FROM jobs WHERE id=43").fetchone()[0] == "failed"
    assert "Notion 페이지 작성에 실패" in client.call.call_args.args[1]["text"]
    assert bridge.poll(db)["jobs"] == []


def test_exact_drive_folder_is_recorded_without_telegram_question(db, monkeypatch):
    insert_industry_job(db, "working")
    changes = []
    monkeypatch.setattr(
        bridge, "change_remote", lambda *a, **k: changes.append((a, k)) or True
    )
    result = bridge.ask_folder(
        db, 43, "1. 반도체",
        "https://drive.google.com/drive/folders/abc_123",
    )
    assert result["status"] == "matched"
    row = db.execute(
        "SELECT status,drive_folder_name,drive_folder_confirmed FROM jobs WHERE id=43"
    ).fetchone()
    assert tuple(row) == ("working", "1. 반도체", 1)
    assert changes[0][0][1:] == ("working", "working")


def test_mismatched_drive_folder_pauses_and_sends_force_reply(db, monkeypatch):
    insert_industry_job(db, "working")
    monkeypatch.setattr(bridge, "change_remote", lambda *a, **k: True)
    monkeypatch.setattr(bridge, "verify_bot", lambda: None)
    telegram = Mock()
    telegram.call.return_value = {"result": {"message_id": 90}}
    monkeypatch.setattr(bridge, "TelegramClient", lambda **k: telegram)
    update = Mock()
    update.eq.return_value = update
    update.execute.return_value.data = [{"update_id": 43}]
    table = Mock()
    table.update.return_value = update
    client = Mock()
    client.table.return_value = table
    monkeypatch.setattr(bridge, "get_client", lambda: client)

    result = bridge.ask_folder(
        db, 43, "3. K-엔터",
        "https://drive.google.com/drive/folders/abc_123",
    )
    assert result["status"] == "awaiting_input"
    row = db.execute(
        "SELECT status,confirmation_message_id,progress_stage FROM jobs WHERE id=43"
    ).fetchone()
    assert tuple(row) == ("awaiting_input", 90, "folder_confirmation")
    payload = telegram.call.call_args.args[1]
    assert payload["reply_markup"] == {"force_reply": True, "selective": True}
    assert "요청 산업명: 반도체" in payload["text"]


def test_confirmed_folder_sync_requeues_same_job(db, monkeypatch):
    insert_industry_job(db, "awaiting_input")
    with db:
        db.execute(
            "UPDATE jobs SET drive_folder_name='3. K-엔터',confirmation_message_id=90 "
            "WHERE id=43"
        )
    query = Mock()
    query.select.return_value = query
    query.eq.return_value = query
    query.limit.return_value = query
    query.execute.return_value.data = [{
        "status": "working", "drive_folder_name": "3. K-엔터",
        "drive_folder_url": "https://drive.google.com/drive/folders/abc",
        "drive_folder_confirmed": True, "confirmation_message_id": 90,
        "confirmation_response": "예", "confirmation_responded_at": "2026-09-26T00:00:00+00:00",
        "error": None,
    }]
    client = Mock()
    client.table.return_value = query
    monkeypatch.setattr(bridge, "get_client", lambda: client)
    assert bridge.sync_folder_confirmations(db) == 1
    assert tuple(db.execute(
        "SELECT status,drive_folder_confirmed,resume_requested FROM jobs WHERE id=43"
    ).fetchone()) == ("working", 1, 1)

    bridge.configure_trigger(db, "01a0b3d1-390f-7301-bd23-be3bdcda4329")
    monkeypatch.setattr(bridge, "find_codex", lambda: "codex.exe")
    calls = []
    monkeypatch.setattr(
        bridge.subprocess, "run",
        lambda args, **kwargs: calls.append(args) or SimpleNamespace(returncode=0),
    )
    assert bridge.wake_pending(db)["status"] == "python_queue"
    assert calls == []
    assert db.execute("SELECT resume_requested FROM jobs WHERE id=43").fetchone()[0] == 1


def test_heartbeat_intake_never_queues_pending_or_resume(db, monkeypatch):
    insert_job(db)
    result = bridge.configure_trigger(db, "01a11689-cd7f-7fb0-bc8d-af71da3a7d4b", "heartbeat")
    assert result["trigger_mode"] == "heartbeat"
    def forbidden(*args, **kwargs):
        pytest.fail("heartbeat must not send queue messages")
    monkeypatch.setattr(bridge, "find_codex", forbidden)
    assert bridge.wake_pending(db) == {"status": "python_queue", "model_calls": 0}
    with db:
        db.execute("UPDATE jobs SET status='working',resume_requested=1 WHERE id=42")
    assert bridge.wake_pending(db) == {"status": "python_queue", "model_calls": 0}
    assert db.execute("SELECT resume_requested FROM jobs WHERE id=42").fetchone()[0] == 1


def test_shadow_readiness_failure_does_not_break_heartbeat_or_claim(db, monkeypatch):
    from telegram_bridge import intake_readiness
    insert_job(db)
    bridge.configure_trigger(db, '01a11689-cd7f-7fb0-bc8d-af71da3a7d4b', 'heartbeat')
    bridge.save_setting(db, 'intake_readiness_enabled', '1')
    monkeypatch.setattr(bridge, 'find_codex', lambda: 'codex.exe')
    def unavailable(*args, **kwargs):
        raise RuntimeError('shared server unavailable')
    monkeypatch.setattr(intake_readiness, 'inspect', unavailable)
    assert bridge.wake_pending(db) == {'status': 'python_queue', 'model_calls': 0}
    assert db.execute('SELECT status FROM jobs WHERE id=42').fetchone()[0] == 'pending'


def test_poll_prioritizes_working_and_oldest_pending_with_negative_ids(db):
    insert_job(db)
    with db:
        db.execute("UPDATE jobs SET created_at='2026-10-07T10:00:00Z' WHERE id=42")
        db.execute("INSERT INTO jobs(id,code,company,raw_text,chat_id,status,created_at) VALUES(-1,'142210','유니트론텍','유니트론텍',111,'pending','2026-10-07T11:00:00Z')")
        db.execute("INSERT INTO jobs(id,code,company,raw_text,chat_id,status,created_at) VALUES(-2,'005930','삼성전자','삼성전자',111,'pending','2026-10-07T12:00:00Z')")
        db.execute("INSERT INTO jobs(id,code,company,raw_text,chat_id,status,created_at) VALUES(99,'005930','삼성전자','삼성전자',111,'working','2026-10-07T13:00:00Z')")
    assert [job['id'] for job in bridge.poll(db)['jobs']] == [99,42,-1,-2]
