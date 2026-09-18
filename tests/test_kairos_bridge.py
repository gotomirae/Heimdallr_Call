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
    assert "삼성전자" not in called[0][-1]  # 원문은 명령행에 넣지 않는다.
    monkeypatch.setattr(bridge, "change_remote", lambda *a, **k: True)
    assert bridge.claim(db, 42)["status"] == "claimed"
    assert bridge.claim(db, 42)["status"] == "not_claimed"


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
