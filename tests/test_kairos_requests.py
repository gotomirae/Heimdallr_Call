# PRD Ref: §8 · SC: Telegram 인증·중복·전달 상태 보존
"""Kairos 연결에서 조용히 잘못될 수 있는 경계를 확인한다."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.notify.kairos_requests import (
    AnalysisTarget,
    FolderConfirmation,
    answer_drive_folder_confirmation,
    direct_company_request,
    direct_industry_request,
    drive_industry_folder_matches,
    enqueue,
    resolve_industry,
)
from src.notify import listen
from src.notify.telegram import TelegramError
from src.notify.resolve import Match


MATCH = Match("005930", "삼성전자", "exact")
ROOT = Path(__file__).resolve().parents[1]


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


def test_industry_requires_exact_direct_name():
    target = resolve_industry("2차 전지", {"2차전지", "반도체"})
    assert target == AnalysisTarget("industry", "2차전지")
    assert direct_industry_request(message("2차 전지"), target, {"111"})
    assert resolve_industry("반도체 분석해줘", {"반도체"}) is None
    assert resolve_industry("2차 전지", {"2차 전지", "2차전지"}) == AnalysisTarget(
        "industry", "2차전지"
    )
    assert not direct_industry_request(
        {**message("2차 전지"), "forward_origin": {"type": "channel"}}, target, {"111"}
    )


@pytest.mark.parametrize("name", [
    "AI", "화장품_미용기기", "여행", "양자컴퓨터",
    "배터리", "우주방산", "음식료", "로봇기계",
])
def test_industry_accepts_current_sector_names(name):
    assert resolve_industry(name, set()) == AnalysisTarget("industry", name)


def test_drive_industry_folder_match_ignores_only_order_and_separators():
    assert drive_industry_folder_matches("2차전지", "16. 2차 전지")
    assert drive_industry_folder_matches("미용 의료기기", "4. 미용_의료기기")
    assert not drive_industry_folder_matches("엔터", "3. K-엔터")
    assert not drive_industry_folder_matches("미용기기", "4. 미용_의료기기")


def test_industry_enqueue_uses_typed_target_without_fake_stock_code(monkeypatch):
    query = Mock()
    client = Mock()
    client.table.return_value = query
    monkeypatch.setattr("src.notify.kairos_requests.get_client", lambda: client)
    assert enqueue(124, message("반도체"), AnalysisTarget("industry", "반도체"))
    payload = query.insert.call_args.args[0]
    assert payload["request_kind"] == "industry"
    assert payload["target_name"] == payload["industry"] == "반도체"
    assert payload["code"] is None and payload["company_name"] is None


def test_database_contract_supports_company_and_industry_targets():
    schema = (ROOT / "src/db/schema.sql").read_text(encoding="utf-8")
    migration = (ROOT / "docs/migrations/kairos_requests.sql").read_text(encoding="utf-8")
    confirmation = (
        ROOT / "docs/migrations/kairos_drive_confirmation.sql"
    ).read_text(encoding="utf-8")
    for source in (schema, migration):
        assert "request_kind" in source and "target_name" in source
        assert "'company', 'industry'" in source
        assert "'failed'" in source and "'awaiting_input'" in source
        assert "drive_folder_name" in source and "confirmation_message_id" in source
    assert "ALTER TABLE public.kairos_requests ALTER COLUMN code DROP NOT NULL" in migration
    assert "DROP CONSTRAINT IF EXISTS kairos_requests_status_check" in confirmation
    assert "drive_folder_confirmed" in confirmation


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


def test_industry_name_beats_partial_company_matches_and_is_queued(monkeypatch):
    client = Mock()
    queued = []
    monkeypatch.setattr(
        listen, "enqueue", lambda update_id, msg, target: queued.append(target) or True
    )
    monkeypatch.setattr(listen, "receipt_message_id", lambda *a: None)
    monkeypatch.setattr(listen, "record_receipt", lambda *a: None)
    client.send_message.return_value = {"result": {"message_id": 88}}
    outcome = listen.handle_message(
        client,
        message("반도체"),
        {"042700": "한미반도체", "000001": "반도체솔루션"},
        analyze=False,
        chats={"111"},
        industries={"반도체"},
        update_id=124,
    )
    assert outcome["result"] == "분석 접수"
    assert queued == [AnalysisTarget("industry", "반도체")]
    assert "반도체 산업 분석 접수" in client.send_message.call_args_list[0].args[0]


def test_folder_confirmation_reply_is_consumed_before_new_analysis(monkeypatch):
    client = Mock()
    monkeypatch.setattr(
        listen, "answer_drive_folder_confirmation",
        lambda *a: FolderConfirmation(124, "confirmed", "3. K-엔터"),
    )
    outcome = listen.handle_message(
        client,
        {**message("예"), "reply_to_message": {"message_id": 90}},
        {}, analyze=False, chats={"111"}, industries={"엔터"}, update_id=125,
    )
    assert outcome["result"] == "Drive 폴더 선택 확인"
    assert "같은 분석 작업을 이어서" in client.send_message.call_args.args[0]


def test_folder_confirmation_requires_reply_and_persists_yes(monkeypatch):
    updates = []

    class Query:
        def __init__(self, mode, payload=None):
            self.mode, self.payload = mode, payload

        def select(self, *args):
            self.mode = "select"
            return self

        def update(self, payload):
            self.mode, self.payload = "update", payload
            return self

        def eq(self, *args):
            return self

        def limit(self, *args):
            return self

        def execute(self):
            if self.mode == "select":
                return SimpleNamespace(data=[{
                    "update_id": 124, "status": "awaiting_input",
                    "drive_folder_name": "3. K-엔터",
                    "drive_folder_confirmed": False, "confirmation_response": None,
                }])
            updates.append(self.payload)
            return SimpleNamespace(data=[{"update_id": 124}])

    class Client:
        def table(self, *args):
            return Query("table")

    monkeypatch.setattr("src.notify.kairos_requests.get_client", lambda: Client())
    assert answer_drive_folder_confirmation(message("예"), {"111"}) is None
    result = answer_drive_folder_confirmation(
        {**message("예"), "reply_to_message": {"message_id": 90}}, {"111"}
    )
    assert result == FolderConfirmation(124, "confirmed", "3. K-엔터")
    assert updates[0]["status"] == "working"
    assert updates[0]["drive_folder_confirmed"] is True


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
