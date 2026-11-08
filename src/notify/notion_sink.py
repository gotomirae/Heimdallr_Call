# PRD Ref: §8 (외부 연동) · JARVIS NEXUS NXD-7
"""노션(원장 #1) 쓰기 — 공용 최소 클라이언트.

JARVIS NEXUS 결정 NXD-7(2026-11-08): HermesCall·Heimdallr Call·Sage는 각자 노션
「2. 주식 자본」에 직접 기록한다. 이 파일은 세 저장소에 **같은 내용으로** 들어간다
(HermesCall `src/notify/notion_sink.py` · Heimdallr `src/notify/notion_sink.py` ·
Sage `collector/notion_sink.py`). 한쪽을 고치면 나머지도 같이 고칠 것.

지키는 것
  1. **토큰은 호출 측이 넘긴다.** 이 모듈은 환경변수를 읽지 않는다(저장소마다 시크릿
     읽는 규칙이 달라서 — HermesCall·Heimdallr은 `src/utils/env.py`만 쓴다).
  2. **중복은 노션에서 확인한다.** 같은 원문 링크(또는 같은 키 칸 값)가 이미 있으면
     만들지 않는다 — 매일 같은 기간을 다시 훑어도 행이 늘지 않는다(멱등).
  3. **선택지(select·multi_select)는 이미 있는 이름만 넣는다.** 노션 API는 모르는
     이름을 받으면 선택지를 **새로 만든다** — 관심종목 32개 칸에 아무 기업이나 섞이면
     아티팩트가 그 칸으로 종목을 고르는 규칙이 조용히 깨진다. 시작할 때 스키마를
     읽어 거른다.
  4. dry-run이면 노션을 읽기만 하고 쓰지 않는다(토큰이 없으면 읽지도 않는다).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Iterable

import httpx

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"   # data_sources 엔드포인트가 있는 버전

#: 노션 「2_5. 소스 DB」 — 모든 수집 도구가 쓰는 색인(아티팩트·옵시디언이 읽는다)
SOURCE_DB = "22b61272-8609-459d-b9e4-61397e274b74"
#: 노션 「2_6-1. 미국 분기 실적 DB」 — 미국 기업 분석 아티팩트(⑥)가 읽는다(백만달러)
US_EARNINGS_DB = "6e65ba6b-8d61-4951-8772-e0468d0fcfc0"

RICH_TEXT_LIMIT = 1900          # 노션 rich_text 한 덩어리 2,000자 제한 아래로
_MIN_INTERVAL_S = 0.36          # 노션 평균 3 req/s


class NotionError(RuntimeError):
    pass


# ── 속성 값 만들기 (순수 함수) ──────────────────────────────────────────

def _clip(text: str | None, limit: int = RICH_TEXT_LIMIT) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def p_title(text: str) -> dict:
    return {"title": [{"text": {"content": _clip(text, 300)}}]}


def p_text(text: str | None) -> dict | None:
    text = _clip(text)
    return {"rich_text": [{"text": {"content": text}}]} if text else None


def p_select(name: str | None, allowed: set[str] | None = None) -> dict | None:
    if not name:
        return None
    if allowed is not None and name not in allowed:
        return None
    return {"select": {"name": name}}


def p_multi(names: Iterable[str], allowed: set[str] | None = None) -> dict | None:
    seen: list[str] = []
    for n in names:
        if n and n not in seen and (allowed is None or n in allowed):
            seen.append(n)
    return {"multi_select": [{"name": n} for n in seen]} if seen else None


def p_url(url: str | None) -> dict | None:
    return {"url": url} if url else None


def p_date(day: str | None) -> dict | None:
    return {"date": {"start": day[:10]}} if day else None


def p_number(value: float | None) -> dict | None:
    if value is None:
        return None
    try:
        return {"number": round(float(value), 4)}
    except (TypeError, ValueError):
        return None


def compact(props: dict[str, dict | None]) -> dict[str, dict]:
    """값이 없는 속성은 보내지 않는다(빈 값으로 덮지 않게)."""
    return {k: v for k, v in props.items() if v is not None}


# ── 클라이언트 ─────────────────────────────────────────────────────────

class NotionSink:
    def __init__(self, token: str | None, *, dry_run: bool = False, timeout: float = 30.0):
        self.token = (token or "").strip()
        self.dry_run = dry_run
        self._last = 0.0
        self._options: dict[tuple[str, str], set[str]] = {}
        self._client = httpx.Client(timeout=timeout) if self.token else None
        self.created = 0
        self.skipped = 0

    @property
    def can_read(self) -> bool:
        return self._client is not None

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        if self._client is None:
            raise NotionError("NOTION_TOKEN이 없다")
        for attempt in range(5):
            wait = _MIN_INTERVAL_S - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            resp = self._client.request(
                method, f"{NOTION_API}{path}", json=body,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Notion-Version": NOTION_VERSION,
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                delay = float(resp.headers.get("Retry-After") or 2 ** attempt)
                logger.warning("노션 %s %s → %s, %.0f초 뒤 재시도", method, path, resp.status_code, delay)
                time.sleep(min(delay, 30))
                continue
            if resp.status_code >= 400:
                # 404 = 통합이 그 DB에 연결되지 않음(노션 '연결 추가' 누락)이 가장 흔하다
                raise NotionError(f"노션 {method} {path} → {resp.status_code}: {resp.text[:300]}")
            return resp.json()
        raise NotionError(f"노션 {method} {path} 재시도 초과")

    def options(self, data_source: str, prop: str) -> set[str] | None:
        """select·multi_select 칸의 현재 선택지. 읽지 못하면 None(그 칸은 비워 둔다)."""
        key = (data_source, prop)
        if key not in self._options:
            if not self.can_read:
                return None
            schema = self._call("GET", f"/data_sources/{data_source}").get("properties", {})
            for name, spec in schema.items():
                kind = spec.get("type")
                if kind in ("select", "multi_select"):
                    self._options[(data_source, name)] = {
                        o.get("name") for o in spec.get(kind, {}).get("options", [])
                    }
            self._options.setdefault(key, set())
        return self._options[key]

    def exists(self, data_source: str, flt: dict) -> bool:
        if not self.can_read:
            return False
        data = self._call("POST", f"/data_sources/{data_source}/query",
                          {"filter": flt, "page_size": 1})
        return bool(data.get("results"))

    def create(self, data_source: str, properties: dict[str, dict], *, dedup: dict | None) -> str:
        """행 1개를 만든다. 반환: 'created' | 'exists' | 'dry-run'."""
        if dedup is not None and self.exists(data_source, dedup):
            self.skipped += 1
            return "exists"
        if self.dry_run:
            title = next((v["title"][0]["text"]["content"] for v in properties.values()
                          if "title" in v), "?")
            logger.info("[dry-run] 노션 행: %s", title)
            return "dry-run"
        self._call("POST", "/pages", {
            "parent": {"type": "data_source_id", "data_source_id": data_source},
            "properties": properties,
        })
        self.created += 1
        return "created"


def url_equals(prop: str, url: str) -> dict:
    return {"property": prop, "url": {"equals": url}}


def text_equals(prop: str, value: str) -> dict:
    return {"property": prop, "rich_text": {"equals": value}}


def title_starts_with(prop: str, prefix: str) -> dict:
    return {"property": prop, "title": {"starts_with": prefix}}


def all_of(*filters: dict) -> dict:
    return {"and": list(filters)}


def signal_from_strength(strength: Any, scale: int = 10) -> str | None:
    """1~scale 강도를 노션 신호강도 1~5로."""
    try:
        s = float(strength)
    except (TypeError, ValueError):
        return None
    level = max(1, min(5, round(s / scale * 5)))
    return str(level)
