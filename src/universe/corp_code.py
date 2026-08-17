# PRD Ref: §5.2, §5.3 · P2 배치 수집의 키
"""DART corpCode.xml(ZIP) → 종목코드 6자리 → corp_code 8자리 매핑.

실측(2026-08-13): ZIP 3.6MB → XML 28.6MB, <list> 118,706건.
그중 stock_code가 6자리 숫자인 것은 3,926건(폐지 종목 포함)이다.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

from src.config.constants import DART_BASE_URL
from src.utils.env import require_env
from src.utils.http import http_get

CORP_CODE_URL = f"{DART_BASE_URL}/corpCode.xml"
CACHE_PATH = Path(".cache/corpcode.zip")

# XML 28MB를 DOM으로 올리지 않고 <list> 블록 단위로 훑는다.
#
# ★ 하나의 정규식으로 corp_code와 stock_code를 한꺼번에 잡으면 안 된다.
#   `<list>.*?<corp_code>(\d{8})</corp_code>.*?<stock_code>(\S{6})</stock_code>.*?</list>`
#   같은 패턴은 DOTALL에서 **레코드 경계를 넘어간다**: stock_code가 비어 있는 레코드
#   (118,706건 중 대다수)에 걸리면 `.*?`가 다음 레코드들을 건너뛰어 **A사의 corp_code에
#   B사의 stock_code를 붙인다.** 예외도 경고도 없고, 매칭률만 높게 나온다.
#   2026-08-13 실측으로 이 오류를 확인했다 — 반드시 블록 단위로 파싱한다.
_LIST_RE = re.compile(r"<list>(.*?)</list>", re.DOTALL)
_CORP_RE = re.compile(r"<corp_code>\s*(\S+?)\s*</corp_code>")
_STOCK_RE = re.compile(r"<stock_code>\s*(\S+?)\s*</stock_code>")


def fetch_corp_code_map(*, use_cache: bool = True) -> dict[str, str]:
    """{종목코드6: corp_code8}. 주 1회 갱신이면 충분해 로컬 캐시를 쓴다."""
    payload: bytes | None = None
    if use_cache and CACHE_PATH.exists():
        payload = CACHE_PATH.read_bytes()

    if payload is None or payload[:2] != b"PK":
        resp = http_get(
            CORP_CODE_URL,
            params={"crtfc_key": require_env("OPENDART_API_KEY")},
            timeout=120.0,
        )
        payload = resp.content
        if payload[:2] != b"PK":
            # DART는 오류도 200 + XML로 준다. ZIP이 아니면 즉시 실패시킨다.
            raise RuntimeError(f"corpCode.xml이 ZIP이 아니다: {payload[:200]!r}")
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_bytes(payload)

    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        xml = zf.read(zf.namelist()[0]).decode("utf-8")

    mapping: dict[str, str] = {}
    for block in _LIST_RE.finditer(xml):
        body = block.group(1)
        stock = _STOCK_RE.search(body)
        if stock is None:
            continue  # 비상장 법인 — 대다수가 여기다
        code = stock.group(1)
        if len(code) != 6:
            continue
        corp = _CORP_RE.search(body)
        if corp is None:
            continue
        # 같은 종목코드가 여러 corp_code에 붙는 경우(합병 이력 등)는 마지막 것을 쓴다.
        mapping[code] = corp.group(1)
    return mapping
