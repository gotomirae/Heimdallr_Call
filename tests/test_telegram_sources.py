# PRD Ref: §8.7 · Telegram 원문 수집기는 Bot API를 쓰지 않고 개별 게시물을 남긴다.
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.collectors.telegram_sources import (
    ChannelSpec,
    build_search_terms,
    collect_channel,
    is_relevant,
    message_url,
    safe_attachment_name,
)


class FakeClient:
    def __init__(self, messages):
        self.messages = messages
        self.downloaded = []

    async def iter_messages(self, handle, **kwargs):
        for message in self.messages:
            yield message

    async def download_media(self, message, file):
        self.downloaded.append((message.id, file))
        return None


def _message(message_id, date, text, filename=None, document=False):
    return SimpleNamespace(
        id=message_id,
        date=date,
        message=text,
        file=SimpleNamespace(name=filename) if filename else None,
        document=object() if document else None,
    )


def test_terms_are_normalized_and_deduplicated():
    assert build_search_terms("SK 하이닉스", ["SK하이닉스", "000660", "000660"]) == (
        "SK 하이닉스",
        "000660",
    )


def test_relevance_uses_body_or_attachment_name():
    terms = ("반도체", "HBM")
    assert is_relevant("HBM 투자 확대", None, terms)
    assert is_relevant("첨부 자료", "2026_반도체_전망.pdf", terms)
    assert not is_relevant("자동차 수요", "완성차.pdf", terms)


def test_message_link_targets_exact_post():
    assert message_url("@DOC_POOL", 193287) == "https://t.me/DOC_POOL/193287"


def test_attachment_name_cannot_escape_request_directory():
    assert safe_attachment_name(7, "../../기업 분석?.pdf") == "7-기업_분석_.pdf"


def test_sungwoo_scan_keeps_only_relevant_posts_inside_72_hours():
    now = datetime(2026, 9, 26, 0, 0, tzinfo=timezone.utc)
    messages = [
        _message(3, now - timedelta(hours=2), "반도체 HBM 전망"),
        _message(2, now - timedelta(hours=3), "자동차 전망"),
        _message(1, now - timedelta(hours=73), "반도체 과거 글"),
    ]
    result = asyncio.run(
        collect_channel(
            FakeClient(messages),
            ChannelSpec("SungwooInsight", "SungwooInsight", 72),
            ("반도체",),
            now=now,
            download_dir=None,
        )
    )
    assert result["status"] == "ok"
    assert result["scanned"] == 2
    assert result["relevant_count"] == 1
    assert result["posts"][0]["url"] == "https://t.me/SungwooInsight/3"


def test_report_channel_downloads_relevant_document(tmp_path):
    now = datetime(2026, 9, 26, 0, 0, tzinfo=timezone.utc)
    client = FakeClient([
        _message(
            8,
            now - timedelta(days=5),
            "첨부",
            filename="반도체_산업전망.pdf",
            document=True,
        )
    ])
    result = asyncio.run(
        collect_channel(
            client,
            ChannelSpec("DOC_POOL", "DOC_POOL", 24 * 92),
            ("반도체",),
            now=now,
            download_dir=tmp_path,
        )
    )
    assert result["relevant_count"] == 1
    assert client.downloaded == [(
        8,
        str(tmp_path / "DOC_POOL" / "8-반도체_산업전망.pdf"),
    )]


@pytest.mark.parametrize('command', ['status', 'search', 'auth'])
def test_excluded_sources_stop_before_config_or_network(monkeypatch, command):
    import asyncio
    from src.collectors import telegram_sources as sources
    def forbidden():
        raise AssertionError('Excluded source must not load credentials or connect')
    monkeypatch.setattr(sources, 'load_config', forbidden)
    if command == 'status':
        result = asyncio.run(sources.status())
    elif command == 'search':
        result = asyncio.run(sources.search_sources('삼성전자', []))
    else:
        result = asyncio.run(sources.authorize())
    assert result == {'status': 'disabled', 'reason': 'EXCLUDED_FROM_ANALYSIS_SOURCES', 'channels': []}
