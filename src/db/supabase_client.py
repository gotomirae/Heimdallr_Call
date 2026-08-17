# PRD Ref: §6, §9.2 · traps.md T7, T9, T16
"""Supabase 클라이언트 단일 진입점.

여기서 방어하는 것 3가지:
  1. SUPABASE_URL에 /rest/v1이 붙는 사고 (참고 프로젝트에서 3회 재발)
  2. PostgREST max-rows 1,000 절단 (T7) — select_all()이 range() 페이징을 강제
  3. 서비스 키/publishable 키 혼동 (T16)
"""

from __future__ import annotations

import re
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


#: PostgREST가 "쓰려는 컬럼이 없다"고 알릴 때의 코드 (T18).
UNDEFINED_COLUMN_WRITE = "PGRST204"
_MISSING_COLUMN_RE = re.compile(r"Could not find the '([^']+)' column")


def missing_column_of(exc: Exception) -> str | None:
    """PGRST204 예외에서 없는 컬럼 이름을 뽑는다. 아니면 None."""
    if str(getattr(exc, "code", "") or "") != UNDEFINED_COLUMN_WRITE:
        return None
    match = _MISSING_COLUMN_RE.search(str(getattr(exc, "message", "") or exc))
    return match.group(1) if match else None


def upsert_tolerating_missing_columns(
    client: Client,
    table: str,
    rows: list[dict[str, Any]],
    *,
    on_conflict: str,
    chunk: int = 500,
) -> tuple[int, list[str]]:
    """없는 컬럼을 하나씩 걷어내며 upsert한다. (저장행수, 걷어낸컬럼) 반환.

    ★ **왜 필요한가 (T18):** DDL은 REST로 실행할 수 없어 사람이 SQL Editor에
      적용하기 전까지 공백이 생긴다. 그 사이 새 컬럼 **하나** 때문에 수집기가
      통째로 죽으면, 같은 잡의 뒷 단계(스크리닝)까지 함께 멈춘다.
      실측(2026-08-17): `ret_5d`를 추가하자 `price_run --save`가 PGRST204로
      크래시했고, `universe_daily`가 시세·스크리너를 통째로 잃을 뻔했다.

    ★ PostgREST는 **한 번에 하나씩만** 알려준다 → 반드시 루프여야 한다.
      한 번만 폴백하는 패턴은 컬럼이 둘 이상 빠지면 여전히 죽는다.

    ★ 걷어낸 컬럼을 **반드시 호출부가 화면에 밝혀야 한다.** 조용히 삼키면
      "저장은 됐는데 그 값만 영영 비어 있는" 상태를 아무도 모른다.
    """
    if not rows:
        return 0, []

    payload = [dict(r) for r in rows]
    dropped: list[str] = []
    all_keys = {k for r in payload for k in r}

    for _ in range(len(all_keys) + 1):
        try:
            for i in range(0, len(payload), chunk):
                client.table(table).upsert(
                    payload[i : i + chunk], on_conflict=on_conflict
                ).execute()
            return len(payload), dropped
        except Exception as exc:
            missing = missing_column_of(exc)
            if missing is None:
                raise
            dropped.append(missing)
            payload = [{k: v for k, v in r.items() if k != missing} for r in payload]
            if not any(payload):
                return 0, dropped
    return 0, dropped
