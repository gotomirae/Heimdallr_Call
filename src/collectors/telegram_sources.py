# PRD Ref: §8.7 · SC: 세 지정 채널의 실제 게시물·첨부를 개별 영구링크로 수집한다.
"""Kairos 투자 분석용 Telegram 원문 수집기.

Bot API/getUpdates는 사용하지 않는다. 사용자가 직접 승인한 MTProto 사용자 세션으로
SungwooInsight, DOC_POOL, sunstudy1234를 읽기 전용 조회한다. 게시·전송·반응 메서드는
제공하지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from telethon import TelegramClient

from src.config.constants import (
    TELEGRAM_ATTACHMENT_FILENAME_MAX_CHARS,
    TELEGRAM_RESEARCH_CHANNELS,
)
from src.utils.env import DirtyEnvError, MissingEnvError, optional_env, require_env


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SESSION_PATH = PROJECT_ROOT / "telegram_bridge" / "state" / "telegram-research.session"


@dataclass(frozen=True)
class ChannelSpec:
    name: str
    handle: str
    lookback_hours: int


@dataclass(frozen=True)
class TelegramResearchConfig:
    api_id: int
    api_hash: str
    session_path: Path


@dataclass(frozen=True)
class SourcePost:
    channel: str
    handle: str
    message_id: int
    published_at: str
    url: str
    text: str
    document_name: str | None
    downloaded_path: str | None


def channel_specs() -> tuple[ChannelSpec, ...]:
    return tuple(ChannelSpec(*row) for row in TELEGRAM_RESEARCH_CHANNELS)


def normalize_search_text(value: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", value.casefold())


def build_search_terms(target: str, aliases: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    terms: list[str] = []
    seen: set[str] = set()
    for raw in (target, *aliases):
        term = " ".join(str(raw).split())
        normalized = normalize_search_text(term)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(term)
    if not terms:
        raise ValueError("검색 대상이나 별칭이 하나 이상 필요하다")
    return tuple(terms)


def message_url(handle: str, message_id: int) -> str:
    clean_handle = handle.strip().lstrip("@").strip("/")
    if not clean_handle or message_id < 1:
        raise ValueError("유효한 채널 handle과 message_id가 필요하다")
    return f"https://t.me/{clean_handle}/{message_id}"


def is_relevant(text: str, document_name: str | None, terms: tuple[str, ...]) -> bool:
    haystack = normalize_search_text(f"{text} {document_name or ''}")
    return any(normalize_search_text(term) in haystack for term in terms)


def load_config() -> TelegramResearchConfig:
    raw_api_id = require_env("TELEGRAM_RESEARCH_API_ID")
    try:
        api_id = int(raw_api_id)
    except ValueError as exc:
        raise DirtyEnvError("TELEGRAM_RESEARCH_API_ID는 정수여야 한다") from exc
    session_value = optional_env("TELEGRAM_RESEARCH_SESSION_PATH")
    session_path = Path(session_value).expanduser() if session_value else DEFAULT_SESSION_PATH
    return TelegramResearchConfig(
        api_id=api_id,
        api_hash=require_env("TELEGRAM_RESEARCH_API_HASH"),
        session_path=session_path.resolve(),
    )


def _message_date(message: Any) -> datetime:
    value = message.date
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _document_name(message: Any) -> str | None:
    value = getattr(getattr(message, "file", None), "name", None)
    return str(value) if value else None


def safe_attachment_name(message_id: int, document_name: str | None) -> str:
    """게시자가 지정한 파일명에서 경로·제어문자를 제거한다."""
    raw = Path(document_name or "attachment").name
    cleaned = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", raw).strip("._")
    cleaned = cleaned[:TELEGRAM_ATTACHMENT_FILENAME_MAX_CHARS] or "attachment"
    return f"{message_id}-{cleaned}"


async def _recent_messages(
    client: Any,
    spec: ChannelSpec,
    cutoff: datetime,
) -> AsyncIterator[Any]:
    async for message in client.iter_messages(
        spec.handle,
        limit=None,
    ):
        if _message_date(message) < cutoff:
            break
        yield message


async def _searched_messages(
    client: Any,
    spec: ChannelSpec,
    terms: tuple[str, ...],
    cutoff: datetime,
) -> AsyncIterator[Any]:
    seen: set[int] = set()
    for term in terms:
        async for message in client.iter_messages(
            spec.handle,
            search=term,
            limit=None,
        ):
            if _message_date(message) < cutoff:
                break
            if message.id in seen:
                continue
            seen.add(message.id)
            yield message


async def collect_channel(
    client: Any,
    spec: ChannelSpec,
    terms: tuple[str, ...],
    *,
    now: datetime,
    download_dir: Path | None,
) -> dict[str, object]:
    cutoff = now.astimezone(timezone.utc) - timedelta(hours=spec.lookback_hours)
    iterator = (
        _recent_messages(client, spec, cutoff)
        if spec.name == "SungwooInsight"
        else _searched_messages(client, spec, terms, cutoff)
    )
    scanned = 0
    posts: list[SourcePost] = []
    async for message in iterator:
        published_at = _message_date(message)
        scanned += 1
        text = str(getattr(message, "message", None) or "")
        document_name = _document_name(message)
        if not is_relevant(text, document_name, terms):
            continue

        downloaded_path: str | None = None
        if download_dir is not None and getattr(message, "document", None) is not None:
            target_dir = download_dir / spec.handle
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / safe_attachment_name(int(message.id), document_name)
            downloaded = await client.download_media(message, file=str(target_path))
            downloaded_path = str(Path(downloaded).resolve()) if downloaded else None

        posts.append(
            SourcePost(
                channel=spec.name,
                handle=spec.handle,
                message_id=int(message.id),
                published_at=published_at.isoformat(),
                url=message_url(spec.handle, int(message.id)),
                text=text,
                document_name=document_name,
                downloaded_path=downloaded_path,
            )
        )

    posts.sort(key=lambda post: post.published_at, reverse=True)
    return {
        "channel": spec.name,
        "handle": spec.handle,
        "lookback_hours": spec.lookback_hours,
        "cutoff": cutoff.isoformat(),
        "status": "ok",
        "scanned": scanned,
        "relevant_count": len(posts),
        "posts": [asdict(post) for post in posts],
    }


async def search_sources(
    target: str,
    aliases: list[str],
    *,
    download_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    config = load_config()
    if not config.session_path.exists():
        return {
            "status": "session_missing",
            "channels": [],
            "next_action": "python -m src.collectors.telegram_sources auth",
        }
    terms = build_search_terms(target, aliases)
    now = now or datetime.now(timezone.utc)
    client = TelegramClient(
        str(config.session_path),
        config.api_id,
        config.api_hash,
        receive_updates=False,
    )
    await client.connect()
    try:
        if not await client.is_user_authorized():
            return {
                "status": "unauthorized",
                "channels": [],
                "next_action": "python -m src.collectors.telegram_sources auth",
            }
        channels: list[dict[str, object]] = []
        for spec in channel_specs():
            try:
                channels.append(
                    await collect_channel(
                        client,
                        spec,
                        terms,
                        now=now,
                        download_dir=download_dir,
                    )
                )
            except Exception as exc:  # 채널별 실패를 나머지 채널 실패로 번지게 하지 않는다.
                channels.append({
                    "channel": spec.name,
                    "handle": spec.handle,
                    "lookback_hours": spec.lookback_hours,
                    "status": "unavailable",
                    "error_type": type(exc).__name__,
                    "posts": [],
                })
        return {
            "status": "ok",
            "target": target,
            "terms": list(terms),
            "collected_at": now.astimezone(timezone.utc).isoformat(),
            "channels": channels,
        }
    finally:
        await client.disconnect()


async def authorize() -> dict[str, object]:
    config = load_config()
    config.session_path.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(
        str(config.session_path),
        config.api_id,
        config.api_hash,
        receive_updates=False,
    )
    await client.start()
    try:
        me = await client.get_me()
        return {
            "status": "authorized",
            "user_id": int(me.id),
            "channels": [spec.handle for spec in channel_specs()],
        }
    finally:
        await client.disconnect()


async def status() -> dict[str, object]:
    try:
        config = load_config()
    except (MissingEnvError, DirtyEnvError) as exc:
        return {
            "status": "not_configured",
            "error_type": type(exc).__name__,
            "next_action": "TELEGRAM_RESEARCH_API_ID/HASH 설정 후 auth 실행",
        }
    if not config.session_path.exists():
        return {"status": "session_missing"}
    client = TelegramClient(
        str(config.session_path),
        config.api_id,
        config.api_hash,
        receive_updates=False,
    )
    await client.connect()
    try:
        if not await client.is_user_authorized():
            return {"status": "unauthorized"}
        available: list[str] = []
        unavailable: list[dict[str, str]] = []
        for spec in channel_specs():
            try:
                await client.get_entity(spec.handle)
                available.append(spec.handle)
            except Exception as exc:
                unavailable.append({"handle": spec.handle, "error_type": type(exc).__name__})
        return {
            "status": "ready" if not unavailable else "partial",
            "available_channels": available,
            "unavailable_channels": unavailable,
        }
    finally:
        await client.disconnect()


def _aliases(values: list[str]) -> list[str]:
    return [part.strip() for value in values for part in value.split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kairos Telegram 원문 읽기")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("auth", help="최초 1회 사용자 로그인 세션 생성")
    subparsers.add_parser("status", help="세션과 세 채널 읽기 권한 확인")
    search = subparsers.add_parser("search", help="세 채널에서 대상 관련 원문 검색")
    search.add_argument("--target", required=True)
    search.add_argument("--alias", action="append", default=[])
    search.add_argument("--download-dir", type=Path)
    search.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "auth":
            result = asyncio.run(authorize())
        elif args.command == "status":
            result = asyncio.run(status())
        else:
            result = asyncio.run(
                search_sources(
                    args.target,
                    _aliases(args.alias),
                    download_dir=args.download_dir,
                )
            )
    except (MissingEnvError, DirtyEnvError) as exc:
        result = {"status": "not_configured", "error_type": type(exc).__name__}

    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if getattr(args, "output", None):
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result.get("status") in {"ok", "ready", "partial", "authorized"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
