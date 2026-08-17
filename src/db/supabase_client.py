# PRD Ref: §6, §9.2 · traps.md T7, T9, T16
"""Supabase 클라이언트 단일 진입점.

여기서 방어하는 것 3가지:
  1. SUPABASE_URL에 /rest/v1이 붙는 사고 (참고 프로젝트에서 3회 재발)
  2. PostgREST max-rows 1,000 절단 (T7) — select_all()이 range() 페이징을 강제
  3. 서비스 키/publishable 키 혼동 (T16)
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from supabase import Client, create_client

from src.config.constants import POSTGREST_PAGE_SIZE
from src.utils.env import require_env


def _normalized_url() -> str:
    """SUPABASE_URL을 정규화한다.

    supabase-py가 /rest/v1을 스스로 붙이므로 .env에 붙이면 /rest/v1/rest/v1이 된다.
    조용히 잘라 주면 같은 실수가 반복되므로, 붙어 있으면 명시적으로 실패시킨다.
    """
    url = require_env("SUPABASE_URL").rstrip("/")
    if url.endswith("/rest/v1"):
        raise ValueError(
            "SUPABASE_URL에 /rest/v1을 붙이지 마라. supabase-py가 스스로 붙인다. "
            f"현재 값: {url}"
        )
    if not url.startswith("https://"):
        raise ValueError(f"SUPABASE_URL 형식이 이상하다: {url}")
    return url


def project_ref() -> str:
    """https://<ref>.supabase.co 의 <ref>. HermesCall과 다른지 눈으로 대조할 때 쓴다."""
    return _normalized_url().removeprefix("https://").split(".", 1)[0]


@lru_cache(maxsize=1)
def get_client() -> Client:
    """service key 클라이언트 (RLS 우회 · 서버사이드 전용)."""
    return create_client(_normalized_url(), require_env("SUPABASE_SERVICE_KEY"))


@lru_cache(maxsize=1)
def get_anon_client() -> Client:
    """publishable/anon 키 클라이언트. RLS 정책이 실제로 먹는지 검증할 때 쓴다.

    ★ 이 클라이언트로 쓰기를 시도하지 마라. 읽기 검증 전용이다.
    """
    return create_client(_normalized_url(), require_env("NEXT_PUBLIC_SUPABASE_ANON_KEY"))


def select_all(
    table: str,
    columns: str = "*",
    *,
    client: Client | None = None,
    order: str | None = None,
    desc: bool = False,
    page_size: int = POSTGREST_PAGE_SIZE,
) -> list[dict[str, Any]]:
    """range() 페이징으로 전체 행을 읽는다.

    ★ .limit(5000)을 줘도 PostgREST는 1,000행만 준다(T7).
    시총 내림차순으로 읽으면 잘려나가는 건 하위 소형주 — 이 시스템이
    발굴하려는 대상이 정확히 그 구간이다. 에러 없이 품질만 나빠진다.
    1,000행을 넘길 수 있는 테이블은 반드시 이 함수를 쓴다.
    """
    db = client or get_client()
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        query = db.table(table).select(columns)
        if order:
            query = query.order(order, desc=desc)
        chunk = query.range(offset, offset + page_size - 1).execute().data or []
        rows.extend(chunk)
        if len(chunk) < page_size:
            return rows
        offset += page_size
