# PRD Ref: §8.7 · SC: 인증된 텔레그램 기업명·산업명 요청만 심층 분석 큐에 기록
"""Heimdallr 수신 메시지에서 Kairos 요청을 판별하고 영구 저장한다."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from src.db.supabase_client import get_client, missing_column_of
from src.notify.resolve import Match


@dataclass(frozen=True)
class AnalysisTarget:
    """텔레그램 단독 입력에서 확정한 분석 대상."""

    kind: str  # company | industry
    name: str
    code: str | None = None


@dataclass(frozen=True)
class FolderConfirmation:
    """Telegram reply applied to one persisted Drive folder question."""

    job_id: int
    decision: str  # confirmed | declined | invalid
    folder_name: str


# Notion 모니터링 DB와 지정 Drive의 실제 상위 분류를 함께 받는다.
# 세부 KRX 업종·투자 섹터는 listener가 DB에서 추가한다.
#: ★ 표준 이름은 JARVIS 노션 L1 18개다(INTEGRATION_TASKS B-9 · JARVIS PRD 부록 A.4).
#:   정본은 JARVIS `config/taxonomy.yaml > l1`이며 이름을 바꾸면 거기부터 바꾼다.
KAIROS_L1_INDUSTRIES: tuple[str, ...] = (
    "AI", "반도체", "전력인프라", "바이오", "화장품_미용기기", "엔터", "우주항공방산",
    "조선", "2차 전지", "자율주행차", "Robot", "IT", "헬스케어", "소비재", "여행",
    "금융", "건설", "양자컴퓨터",
)
#: 기존 이름은 **입력 별칭**으로 남긴다. 별칭으로 들어와도 L1 이름으로 접수한다.
KAIROS_INDUSTRY_ALIASES: dict[str, str] = {
    "2차전지": "2차 전지", "배터리": "2차 전지",
    "로봇": "Robot", "로봇기계": "Robot",
    "우주방산": "우주항공방산",
    "화장품": "화장품_미용기기", "미용기기": "화장품_미용기기",
    "네트워크": "IT", "OLED": "IT",
    "음식료": "소비재", "의류": "소비재",
}
#: 하나의 L1로 접히지 않는 이름 — AI 반도체(= AI + 반도체), ETF(특수 라벨).
KAIROS_SPECIAL_INDUSTRIES: tuple[str, ...] = ("AI 반도체", "ETF")
SUPPORTED_INDUSTRIES = frozenset({
    *KAIROS_L1_INDUSTRIES, *KAIROS_INDUSTRY_ALIASES, *KAIROS_SPECIAL_INDUSTRIES,
})

CONFIRMATION_YES = frozenset({"예", "네", "예스", "yes", "y"})
CONFIRMATION_NO = frozenset({"아니오", "아니요", "아니", "no", "n"})


def normalize_drive_industry_folder(name: str) -> str:
    """Ignore only ordering prefixes and separators when comparing Drive folders.

    Semantic additions such as ``K-`` or a wider industry name are deliberately
    preserved so the analysis worker must ask the user before selecting them.
    """
    without_order = re.sub(r"^\s*\d+\s*[.)_-]\s*", "", name)
    return re.sub(r"[\s._-]+", "", without_order).upper()


def drive_industry_folder_matches(requested: str, folder_name: str) -> bool:
    return normalize_drive_industry_folder(requested) == normalize_drive_industry_folder(
        folder_name
    )


def _direct_private_text(message: dict, chats: set[str]) -> str | None:
    """인증된 개인 채팅의 한 줄 직접 입력만 반환한다."""
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
        return None
    return text


def direct_company_request(message: dict, match: Match, chats: set[str]) -> bool:
    """개인 채팅의 본인 입력이며 종목명·티커 단독 입력일 때만 참이다."""
    text = _direct_private_text(message, chats)
    if text is None:
        return False
    if match.how == "code":
        return bool(re.fullmatch(r"[0-9][0-9A-Z]{5}", text.upper()))
    if match.how == "exact":
        return text == match.name
    if match.how == "normalized":
        from src.notify.resolve import normalize

        return normalize(text) == normalize(match.name)
    return False


def resolve_industry(text: str, industries: set[str]) -> AnalysisTarget | None:
    """산업 카탈로그의 완전·정규화 일치만 허용한다.

    문장이나 부분 일치를 받으면 회사명과 산업명이 겹칠 때 엉뚱한 대상을 분석한다.
    """
    from src.notify.resolve import normalize

    target = normalize(text)
    if not target:
        return None
    matches = sorted({name.strip() for name in industries | set(SUPPORTED_INDUSTRIES)
                      if name and normalize(name) == target})
    if not matches:
        return None
    preferred = sorted(
        (name for name in SUPPORTED_INDUSTRIES if normalize(name) == target),
        key=lambda name: (len(name), name),
    )
    canonical = preferred[0] if preferred else min(matches, key=lambda name: (len(name), name))
    return AnalysisTarget(kind="industry", name=KAIROS_INDUSTRY_ALIASES.get(canonical, canonical))


def direct_industry_request(
    message: dict, target: AnalysisTarget, chats: set[str]
) -> bool:
    """인증된 개인 채팅에서 산업명만 단독 입력했는지 확인한다."""
    from src.notify.resolve import normalize

    text = _direct_private_text(message, chats)
    accepted = {target.name} | {
        alias for alias, name in KAIROS_INDUSTRY_ALIASES.items() if name == target.name
    }
    return bool(
        text is not None
        and target.kind == "industry"
        and normalize(text) in {normalize(name) for name in accepted}
    )


def enqueue(update_id: int, message: dict, target: Match | AnalysisTarget) -> bool:
    """Telegram update ID를 멱등 키로 저장한다. True는 신규 접수다."""
    if isinstance(target, Match):
        resolved = AnalysisTarget("company", target.name, target.code)
    else:
        resolved = target
    if resolved.kind not in {"company", "industry"}:
        raise ValueError("INVALID_REQUEST_KIND")
    payload = {
        "update_id": update_id,
        "chat_id": int(message["chat"]["id"]),
        "user_id": int(message["from"]["id"]),
        "request_kind": resolved.kind,
        "target_name": resolved.name,
        "code": resolved.code,
        "company_name": resolved.name if resolved.kind == "company" else None,
        "industry": resolved.name if resolved.kind == "industry" else None,
        "raw_text": message["text"].strip(),
        "status": "pending",
    }
    try:
        get_client().table("kairos_requests").insert(payload).execute()
    except Exception as exc:
        # 재전달된 update를 upsert하면 sent/working이 pending으로 되돌아간다.
        if str(getattr(exc, "code", "")) == "23505":
            return False
        # 기업 요청은 DDL 적용 전에도 기존 계약으로 계속 동작한다. 산업 요청은
        # code NOT NULL을 우회해 거짓 기업으로 저장하지 않고 사용자에게 원인을 알린다.
        if missing_column_of(exc) in {"request_kind", "target_name"}:
            if resolved.kind == "industry":
                raise RuntimeError("KAIROS_INDUSTRY_SCHEMA_REQUIRED") from exc
            legacy = {
                "update_id": update_id,
                "chat_id": int(message["chat"]["id"]),
                "user_id": int(message["from"]["id"]),
                "code": resolved.code,
                "company_name": resolved.name,
                "raw_text": message["text"].strip(),
                "status": "pending",
            }
            try:
                get_client().table("kairos_requests").insert(legacy).execute()
            except Exception as legacy_exc:
                if str(getattr(legacy_exc, "code", "")) == "23505":
                    return False
                raise
            return True
        raise
    return True


def record_receipt(update_id: int, message_id: int) -> None:
    """접수 메시지 ID를 보존해 분석 단계마다 같은 메시지를 갱신한다."""
    get_client().table("kairos_requests").update(
        {"telegram_message_id": message_id}
    ).eq("update_id", update_id).execute()


def receipt_message_id(update_id: int) -> int | None:
    rows = (
        get_client().table("kairos_requests").select("telegram_message_id")
        .eq("update_id", update_id).limit(1).execute().data or []
    )
    return rows[0].get("telegram_message_id") if rows else None


def answer_drive_folder_confirmation(
    message: dict, chats: set[str]
) -> FolderConfirmation | None:
    """Apply a force-reply answer to exactly one awaiting industry request.

    A bare ``예`` is never accepted: it must reply to the stored confirmation
    message, preventing an unrelated chat message from resuming the wrong job.
    """
    text = _direct_private_text(message, chats)
    reply = message.get("reply_to_message") or {}
    reply_id = reply.get("message_id")
    if text is None or not isinstance(reply_id, int):
        return None
    chat_id = int(message["chat"]["id"])
    rows = (
        get_client().table("kairos_requests")
        .select(
            "update_id,status,drive_folder_name,drive_folder_confirmed,"
            "confirmation_response"
        )
        .eq("chat_id", chat_id)
        .eq("user_id", chat_id)
        .eq("confirmation_message_id", reply_id)
        .limit(1).execute().data or []
    )
    if not rows:
        return None
    row = rows[0]
    normalized = text.casefold().strip()
    if (
        row.get("status") == "working"
        and row.get("drive_folder_confirmed")
        and normalized in CONFIRMATION_YES
    ):
        return FolderConfirmation(
            job_id=int(row["update_id"]), decision="confirmed",
            folder_name=str(row.get("drive_folder_name") or ""),
        )
    if (
        row.get("status") == "rejected"
        and row.get("confirmation_response")
        and normalized in CONFIRMATION_NO
    ):
        return FolderConfirmation(
            job_id=int(row["update_id"]), decision="declined",
            folder_name=str(row.get("drive_folder_name") or ""),
        )
    if row.get("status") != "awaiting_input":
        return None
    if normalized in CONFIRMATION_YES:
        decision, status, confirmed, error = "confirmed", "working", True, None
    elif normalized in CONFIRMATION_NO:
        decision, status, confirmed, error = (
            "declined", "rejected", False,
            "Drive 산업 폴더 선택을 사용자가 거절했습니다.",
        )
    else:
        return FolderConfirmation(
            job_id=int(row["update_id"]),
            decision="invalid",
            folder_name=str(row.get("drive_folder_name") or ""),
        )
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "status": status,
        "drive_folder_confirmed": confirmed,
        "confirmation_response": text,
        "confirmation_responded_at": now,
        "error": error,
    }
    result = (
        get_client().table("kairos_requests").update(payload)
        .eq("update_id", row["update_id"])
        .eq("status", "awaiting_input").execute()
    )
    if not result.data:
        return None
    return FolderConfirmation(
        job_id=int(row["update_id"]),
        decision=decision,
        folder_name=str(row.get("drive_folder_name") or ""),
    )
