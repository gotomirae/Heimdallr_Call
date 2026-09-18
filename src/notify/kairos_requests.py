# PRD Ref: §8 · SC: 인증된 텔레그램 기업명 요청만 심층 분석 큐에 기록
"""Heimdallr 수신 메시지에서 Kairos 요청을 판별하고 영구 저장한다."""

from __future__ import annotations

import re

from src.db.supabase_client import get_client
from src.notify.resolve import Match


def direct_company_request(message: dict, match: Match, chats: set[str]) -> bool:
    """개인 채팅의 본인 입력이며 종목명·티커 단독 입력일 때만 참이다."""
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    text = (message.get("text") or "").strip()
    if (
        chat.get("type") != "private"
        or str(chat.get("id", "")) not in chats
        or str(sender.get("id", "")) != str(chat.get("id", ""))
        or sender.get("is_bot")
        or message.get("forward_origin")
        or message.get("forward_date")
        or message.get("via_bot")
        or not text
        or "\n" in text
    ):
        return False
    if match.how == "code":
        return bool(re.fullmatch(r"[0-9][0-9A-Z]{5}", text.upper()))
    if match.how == "exact":
        return text == match.name
    if match.how == "normalized":
        from src.notify.resolve import normalize

        return normalize(text) == normalize(match.name)
    return False


def enqueue(update_id: int, message: dict, match: Match) -> bool:
    """Telegram update ID를 멱등 키로 저장한다. True는 신규 접수다."""
    payload = {
        "update_id": update_id,
        "chat_id": int(message["chat"]["id"]),
        "user_id": int(message["from"]["id"]),
        "code": match.code,
        "company_name": match.name,
        "raw_text": message["text"].strip(),
        "status": "pending",
    }
    try:
        get_client().table("kairos_requests").insert(payload).execute()
    except Exception as exc:
        # 재전달된 update를 upsert하면 sent/working이 pending으로 되돌아간다.
        if str(getattr(exc, "code", "")) == "23505":
            return False
        raise
    return True
