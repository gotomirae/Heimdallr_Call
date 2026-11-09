# PRD Ref: §8 (외부 연동) · JARVIS NEXUS NXD-7 — 세 저장소 공용 노션 클라이언트
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
  5. **본문(블록)은 분석 전체를 싣는다**(2026-11-08 사용자 지시 "투자 판단에 유용한
     내용 모두"). 본문 첫 줄에 내용 해시(🔖 내보내기 버전)를 두고, 분석이 바뀌면
     (예: 어닝콜 Q&A가 뒤늦게 붙음) 속성을 고치고 본문을 통째로 바꾼다. 같으면 건너뛴다.
"""

from __future__ import annotations

import hashlib
import json
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


# ── 본문 블록 (순수 함수) ──────────────────────────────────────────────

_BLOCK_TEXT_LIMIT = 1900
VERSION_PREFIX = "🔖 내보내기 버전 "


def _rich(text: str) -> list[dict]:
    """2,000자 제한을 넘는 글은 여러 rich_text 조각으로 나눈다(블록당 100조각까지)."""
    text = (text or "").strip()
    parts = [text[i:i + _BLOCK_TEXT_LIMIT] for i in range(0, len(text), _BLOCK_TEXT_LIMIT)] or [""]
    return [{"type": "text", "text": {"content": p}} for p in parts[:100]]


def b_heading(text: str, level: int = 2) -> dict:
    kind = f"heading_{max(1, min(3, level))}"
    return {"object": "block", "type": kind, kind: {"rich_text": _rich(text[:200])}}


def b_para(text: str) -> dict:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich(text)}}


def b_bullet(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": _rich(text)}}


def b_divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def content_hash(*parts: Any) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "예" if v else "아니오"
    if isinstance(v, float):
        return f"{v:,.4g}" if abs(v) < 1e6 else f"{v:,.0f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v).strip()


def _is_empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def render_value(value: Any, labels: dict[str, str] | None = None, *,
                 level: int = 3, max_depth: int = 4) -> list[dict]:
    """임의의 JSON(딕셔너리·목록·값)을 노션 블록으로. 빈 값은 건너뛴다.

    딕셔너리: 값이 짧은 스칼라면 '라벨: 값' 글머리, 길거나 중첩이면 소제목 + 하위.
    목록: 스칼라면 글머리, 딕셔너리면 항목마다 '· 요약' 글머리 + 나머지 필드 글머리.
    """
    labels = labels or {}
    out: list[dict] = []
    if _is_empty(value):
        return out
    if isinstance(value, dict):
        # 짧은 값(스칼라)을 먼저, 묶음(딕셔너리·목록)을 뒤에 — 소제목 아래에 스칼라가 섞여
        # 다른 묶음의 일부처럼 읽히지 않게
        items = [kv for kv in value.items() if not _is_empty(kv[1])]
        items.sort(key=lambda kv: isinstance(kv[1], (dict, list)))
        for k, v in items:
            label = labels.get(k, k)
            if not isinstance(v, (dict, list)):
                text = _scalar(v)
                out.append(b_bullet(f"{label}: {text}") if len(text) <= 160
                           else b_para(f"【{label}】 {text}"))
            elif max_depth <= 0:
                out.append(b_bullet(f"{label}: {json.dumps(v, ensure_ascii=False)[:1800]}"))
            else:
                out.append(b_heading(label, level) if level <= 3 else b_para(f"【{label}】"))
                out.extend(render_value(v, labels, level=level + 1, max_depth=max_depth - 1))
        return out
    if isinstance(value, list):
        for item in value:
            if _is_empty(item):
                continue
            if isinstance(item, dict):
                out.append(b_bullet(_item_line(item, labels)))
            elif isinstance(item, list):
                out.extend(render_value(item, labels, level=level, max_depth=max_depth - 1))
            else:
                out.append(b_bullet(_scalar(item)))
        return out
    out.append(b_para(_scalar(value)))
    return out


def _item_line(item: dict, labels: dict[str, str]) -> str:
    """목록 안 딕셔너리 한 항목을 한 줄로: '라벨: 값 · 라벨: 값'."""
    bits = []
    for k, v in item.items():
        if _is_empty(v):
            continue
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        bits.append(f"{labels.get(k, k)}: {_scalar(v)}")
    return " · ".join(bits)


# ── 클라이언트 ─────────────────────────────────────────────────────────

class NotionSink:
    def __init__(self, token: str | None, *, dry_run: bool = False, timeout: float = 30.0):
        self.token = (token or "").strip()
        self.dry_run = dry_run
        self._last = 0.0
        self._options: dict[tuple[str, str], set[str]] = {}
        self._client = httpx.Client(timeout=timeout) if self.token else None
        self.created = 0
        self.updated = 0
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


    # ── 본문까지 쓰는 upsert ──────────────────────────────────────────

    def find(self, data_source: str, flt: dict) -> str | None:
        if not self.can_read:
            return None
        data = self._call("POST", f"/data_sources/{data_source}/query",
                          {"filter": flt, "page_size": 1})
        res = data.get("results") or []
        return res[0]["id"] if res else None

    def _children(self, block_id: str) -> list[dict]:
        out, cursor = [], None
        while True:
            q = f"/blocks/{block_id}/children?page_size=100"
            if cursor:
                q += f"&start_cursor={cursor}"
            data = self._call("GET", q)
            out.extend(data.get("results") or [])
            if not data.get("has_more"):
                return out
            cursor = data.get("next_cursor")

    def _append(self, block_id: str, blocks: list[dict]) -> None:
        for i in range(0, len(blocks), 100):
            self._call("PATCH", f"/blocks/{block_id}/children", {"children": blocks[i:i + 100]})

    def _page_version(self, page_id: str) -> str | None:
        data = self._call("GET", f"/blocks/{page_id}/children?page_size=1")
        res = data.get("results") or []
        if not res or res[0].get("type") != "paragraph":
            return None
        text = "".join(t.get("plain_text", "") for t in res[0]["paragraph"].get("rich_text", []))
        return text[len(VERSION_PREFIX):].strip() if text.startswith(VERSION_PREFIX) else None

    def upsert(self, data_source: str, properties: dict[str, dict], children: list[dict], *,
               dedup: dict, version: str) -> str:
        """행 1개를 본문까지 맞춘다. 반환: 'created' | 'updated' | 'unchanged' | 'dry-run'.

        본문 맨 앞에 버전 문단을 넣는다. 같은 버전이면 아무것도 안 한다(매일 같은 기간을
        다시 훑어도 노션 호출이 조회 2회로 끝난다).
        """
        blocks = [b_para(f"{VERSION_PREFIX}{version}"), *children]
        page_id = self.find(data_source, dedup)
        if page_id and self._page_version(page_id) == version:
            self.skipped += 1
            return "unchanged"
        if self.dry_run:
            title = next((v["title"][0]["text"]["content"] for v in properties.values()
                          if "title" in v), "?")
            logger.info("[dry-run] 노션 %s: %s (본문 %d블록)",
                        "갱신" if page_id else "생성", title, len(blocks))
            return "dry-run"
        if page_id:
            self._call("PATCH", f"/pages/{page_id}", {"properties": properties})
            for blk in self._children(page_id):
                self._call("DELETE", f"/blocks/{blk['id']}")
            self._append(page_id, blocks)
            self.updated += 1
            return "updated"
        page = self._call("POST", "/pages", {
            "parent": {"type": "data_source_id", "data_source_id": data_source},
            "properties": properties,
            "children": blocks[:100],
        })
        if len(blocks) > 100:
            self._append(page["id"], blocks[100:])
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
