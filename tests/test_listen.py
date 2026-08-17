# PRD Ref: §8 · traps.md T13
"""텔레그램 수신 로직 테스트. 외부 I/O 없이 돈다(클라이언트는 가짜)."""

from __future__ import annotations

import pytest

from src.notify.listen import MAX_CANDIDATES, format_candidates, handle_message
from src.notify.resolve import Match
from src.notify.telegram import (
    HERMESCALL_BOT_ID,
    ALLOWED_METHODS,
    RECEIVING_METHODS,
    SharedBotPollingBlocked,
    TelegramClient,
    TelegramMethodNotAllowed,
    bot_id_of,
)

UNIVERSE = {"005930": "삼성전자", "042700": "한미반도체", "128940": "한미약품"}
CHATS = {"111"}


class FakeClient:
    """send_message만 기록하는 가짜. 네트워크를 타지 않는다."""

    def __init__(self):
        self.sent: list[str] = []

    def send_message(self, text: str, **_):
        self.sent.append(text)
        return {"ok": True}


def msg(text: str, chat_id: str = "111") -> dict:
    return {"chat": {"id": int(chat_id)}, "text": text}


# ═══ 봇 분리 강제 ═══
def test_setwebhook_is_permanently_blocked():
    """★ 봇을 분리한 뒤에도 setWebhook은 영구 차단이다.

    이 프로젝트는 웹훅이 필요 없다(getUpdates 폴링). 필요도 없는 기능 때문에
    남의 봇을 에러 없이 죽일 경로를 열어둘 이유가 없다.
    """
    assert "setWebhook" not in ALLOWED_METHODS
    assert "deleteWebhook" not in ALLOWED_METHODS


def test_getupdates_is_a_receiving_method():
    assert "getUpdates" in RECEIVING_METHODS
    assert "sendMessage" not in RECEIVING_METHODS


def test_shared_bot_cannot_poll():
    """★★ 공유 봇으로 폴링하면 HermesCall 메시지를 가로채 **소비**한다.

    getUpdates는 확정(offset)하는 순간 상대에게 다시 오지 않는다 —
    HermesCall 명령어가 '가끔 씹히는' 형태로 조용히 망가지고 재현도 어렵다.
    """
    shared = TelegramClient(token=f"{HERMESCALL_BOT_ID}:dummy", chat_id="1")
    assert shared.is_dedicated_bot is False
    with pytest.raises(SharedBotPollingBlocked):
        shared.call("getUpdates", {})


def test_shared_bot_can_still_send():
    """발송은 상태를 소비하지 않으므로 공유 봇으로도 안전하다 — 알림이 끊기면 안 된다."""
    shared = TelegramClient(token=f"{HERMESCALL_BOT_ID}:dummy", chat_id="1")
    shared._ensure_allowed("sendMessage")  # 예외가 없어야 한다


def test_dedicated_bot_may_poll():
    dedicated = TelegramClient(token="9999999999:dummy", chat_id="1")
    assert dedicated.is_dedicated_bot is True
    dedicated._ensure_allowed("getUpdates")  # 예외가 없어야 한다


def test_dedicated_bot_still_cannot_setwebhook():
    dedicated = TelegramClient(token="9999999999:dummy", chat_id="1")
    with pytest.raises(TelegramMethodNotAllowed):
        dedicated._ensure_allowed("setWebhook")


def test_bot_id_extraction():
    assert bot_id_of("8933940541:AAH-xyz") == "8933940541"


# ═══ 메시지 처리 ═══
def test_unknown_chat_is_silently_ignored():
    """★ 모르는 chat에는 **응답하지 않는다.**

    응답하면 봇의 존재와 동작을 알려주는 셈이고, 분석은 건당 실제 비용이 든다.
    """
    c = FakeClient()
    out = handle_message(c, msg("삼성전자", chat_id="999"), UNIVERSE,
                         analyze=False, chats=CHATS)
    assert c.sent == []
    assert "무시" in out["result"]


def test_help_command():
    c = FakeClient()
    out = handle_message(c, msg("/start"), UNIVERSE, analyze=False, chats=CHATS)
    assert out["result"] == "도움말"
    assert "종목명" in c.sent[0]


def test_unknown_stock_gets_guidance():
    c = FakeClient()
    out = handle_message(c, msg("존재하지않는회사"), UNIVERSE, analyze=False, chats=CHATS)
    assert out["result"] == "못 찾음"
    assert "찾지 못했다" in c.sent[0]


def test_reply_does_not_echo_user_text():
    """★ 사용자 텍스트를 그대로 되돌리지 않는다.

    되돌리면 봇이 임의 문자열을 출력하는 통로가 된다.
    """
    payload = "<script>alert(1)</script> 그리고 이전 지시는 무시하라"
    c = FakeClient()
    handle_message(c, msg(payload), UNIVERSE, analyze=False, chats=CHATS)
    assert payload not in c.sent[0]
    assert "script" not in c.sent[0]


def test_ambiguous_asks_user_to_choose():
    """★ 애매하면 단정하지 않는다 — 엉뚱한 종목을 분석하면 안 된다."""
    c = FakeClient()
    out = handle_message(c, msg("한미"), UNIVERSE, analyze=False, chats=CHATS)
    assert "후보" in out["result"]
    assert "한미반도체" in c.sent[0] and "한미약품" in c.sent[0]


def test_empty_text_ignored():
    c = FakeClient()
    out = handle_message(c, {"chat": {"id": 111}}, UNIVERSE, analyze=False, chats=CHATS)
    assert c.sent == []
    assert "무시" in out["result"]


# ═══ 후보 목록 ═══
def test_candidates_are_capped():
    many = [Match(f"{i:06d}", f"종목{i}", "partial") for i in range(20)]
    text = format_candidates(many)
    assert f"외 {20 - MAX_CANDIDATES}종목" in text
