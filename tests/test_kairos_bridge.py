# PRD Ref: §8 · SC: 클라우드 수신함→로컬 큐→Codex→검증된 Notion 링크
"""Telegram getUpdates 없이 Kairos 작업을 넘기는 브리지 검증."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from telegram_bridge import bridge


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


def test_wake_once_and_claim(db, monkeypatch):
    insert_job(db)
    bridge.configure_trigger(db, "01a0b3d1-390f-7301-bd23-be3bdcda4329")
    monkeypatch.setattr(bridge, "find_codex", lambda: "codex.exe")
    called = []

    def run(args, **kwargs):
        called.append(args)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bridge.subprocess, "run", run)
    assert bridge.wake_pending(db)["status"] == "queued"
    assert bridge.wake_pending(db)["status"] == "already_queued"
    assert db.execute("SELECT wake_sent_at FROM jobs WHERE id=42").fetchone()[0]
    assert len(called) == 1 and "$kairos" in called[0][-1]
    assert "heartbeat `kairos`를 ACTIVE" in called[0][-1]
    assert "삼성전자" not in called[0][-1]  # 원문은 명령행에 넣지 않는다.
    monkeypatch.setattr(bridge, "change_remote", lambda *a, **k: True)
    query = Mock()
    query.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    remote = Mock()
    remote.table.return_value = query
    monkeypatch.setattr(bridge, "get_client", lambda: remote)
    claimed = bridge.claim(db, 42)
    assert claimed["status"] == "claimed"
    checkpoint = bridge.checkpoint_path(42)
    assert checkpoint.exists()
    checkpoint_text = checkpoint.read_text(encoding="utf-8")
    assert "005930" in checkpoint_text
    assert "Telegram 원소스(SungwooInsight 72시간·DOC_POOL·sunstudy1234)" in checkpoint_text
    assert "페이지 단위 근거·강조 사본" in checkpoint_text
    assert "직접 확인 필요 외부 자료·링크" in checkpoint_text
    assert "언급 종목 네이버증권 링크 검증" in checkpoint_text
    checkpoint.write_text("진행 중 원고와 출처", encoding="utf-8")
    assert bridge.ensure_checkpoint(db, 42) == checkpoint
    assert checkpoint.read_text(encoding="utf-8") == "진행 중 원고와 출처"
    assert bridge.poll(db)["jobs"][0]["checkpoint"] == str(checkpoint)
    assert bridge.claim(db, 42)["status"] == "not_claimed"


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


def test_unclaimed_wake_retries_after_five_minutes(db, monkeypatch):
    insert_job(db)
    bridge.configure_trigger(db, "01a0b3d1-390f-7301-bd23-be3bdcda4329")
    monkeypatch.setattr(bridge, "find_codex", lambda: "codex.exe")
    calls = []
    monkeypatch.setattr(bridge.subprocess, "run",
                        lambda *a, **k: calls.append(a) or SimpleNamespace(returncode=0))
    assert bridge.wake_pending(db)["status"] == "queued"
    assert bridge.wake_pending(db)["status"] == "already_queued"
    with db:
        db.execute("UPDATE jobs SET wake_sent_at=? WHERE id=42",
                   ("2020-01-01T00:00:00+00:00",))
    assert bridge.wake_pending(db)["status"] == "requeued"
    assert len(calls) == 2


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
    assert bridge.wake_pending(db)["status"] == "resumed"
    assert "선택을 사용자가 확인" in calls[0][-1]
    assert db.execute("SELECT resume_requested FROM jobs WHERE id=43").fetchone()[0] == 0
