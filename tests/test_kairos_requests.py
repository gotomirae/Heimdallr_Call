# PRD Ref: §8 · SC: Telegram 인증·중복·전달 상태 보존
"""Kairos 연결에서 조용히 잘못될 수 있는 경계를 확인한다."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from src.notify.kairos_requests import direct_company_request, enqueue
from src.notify import listen
from src.notify.telegram import TelegramError
from src.notify.resolve import Match


MATCH = Match("005930", "삼성전자", "exact")


def message(text="삼성전자") -> dict:
    return {"chat": {"id": 111, "type": "private"},
            "from": {"id": 111, "is_bot": False}, "text": text}


def test_only_direct_private_company_name_is_accepted():
    assert direct_company_request(message(), MATCH, {"111"})
    assert direct_company_request(message("비엠티"),
                                  Match("086670", "비엠티", "exact"), {"111"})
    assert direct_company_request(message("005930"),
                                  Match("005930", "삼성전자", "code"), {"111"})
    for bad in (
        {**message(), "chat": {"id": 111, "type": "group"}},
        {**message(), "from": {"id": 222}},
        {**message(), "forward_origin": {"type": "channel"}},
        {**message(), "via_bot": {"id": 1}},
        message("삼성전자 분석해줘"),
    ):
        assert not direct_company_request(bad, MATCH, {"111"})
    assert not direct_company_request(message(), MATCH, {"222"})


def test_duplicate_update_does_not_reset_completed_request(monkeypatch):
    class Duplicate(Exception):
        code = "23505"

    query = Mock()
    query.insert.return_value.execute.side_effect = Duplicate()
    client = Mock()
    client.table.return_value = query
    monkeypatch.setattr("src.notify.kairos_requests.get_client", lambda: client)
    assert enqueue(123, message(), MATCH) is False
    payload = query.insert.call_args.args[0]
    assert payload["update_id"] == 123 and payload["code"] == "005930"
    assert payload["status"] == "pending"


def test_queue_error_is_not_silenced(monkeypatch):
    query = Mock()
    query.insert.return_value.execute.side_effect = RuntimeError("database unavailable")
    client = Mock()
    client.table.return_value = query
    monkeypatch.setattr("src.notify.kairos_requests.get_client", lambda: client)
    with pytest.raises(RuntimeError, match="database unavailable"):
        enqueue(123, message(), MATCH)


def test_telegram_update_sends_progress_receipt_without_short_report(monkeypatch):
    client = Mock()
    client.call.return_value = {"result": [
        {"update_id": 123, "message": message()}
    ]}
    client.send_message.return_value = {"result": {"message_id": 77}}
    monkeypatch.setattr(listen, "load_universe", lambda: {"005930": "삼성전자"})
    monkeypatch.setattr(listen, "allowed_chats", lambda: {"111"})
    monkeypatch.setattr(listen, "build_report",
                        lambda *a, **k: pytest.fail("short report must not run"))
    queued = []
    monkeypatch.setattr(listen, "enqueue",
                        lambda update_id, msg, match: queued.append(update_id) or True)
    receipts = []
    monkeypatch.setattr(listen, "record_receipt",
                        lambda update_id, msg_id: receipts.append((update_id, msg_id)))
    monkeypatch.setattr(listen, "confirm", lambda client, update_id: None)
    result = listen.poll_once(client, analyze=False)
    assert queued == [123]
    assert receipts == [(123, 77)]
    assert result[0]["kairos"] == "접수"
    assert "분석 접수" in client.send_message.call_args.args[0]
    assert "30~90분" in client.send_message.call_args.args[0]


def test_receipt_send_failure_keeps_update_for_retry(monkeypatch):
    client = Mock()
    client.call.return_value = {"result": [
        {"update_id": 123, "message": message()}
    ]}
    client.send_message.side_effect = [TelegramError("temporary"),
                                       {"result": {"message_id": 78}}]
    monkeypatch.setattr(listen, "load_universe", lambda: {"005930": "삼성전자"})
    monkeypatch.setattr(listen, "allowed_chats", lambda: {"111"})
    arrivals = []
    monkeypatch.setattr(listen, "enqueue",
                        lambda *a: arrivals.append(1) or len(arrivals) == 1)
    monkeypatch.setattr(listen, "receipt_message_id", lambda *a: None)
    receipts = []
    monkeypatch.setattr(listen, "record_receipt",
                        lambda *a: receipts.append(a))
    confirms = []
    monkeypatch.setattr(listen, "confirm", lambda *a: confirms.append(a))
    assert "발송 실패" in listen.poll_once(client, analyze=False)[0]["result"]
    assert confirms == []
    assert listen.poll_once(client, analyze=False)[0]["result"] == "분석 접수"
    assert receipts == [(123, 78)]
    assert len(confirms) == 1
