# PRD Ref: §5 (데이터 아키텍처)
"""공용 HTTP 헬퍼. 일시적 오류만 재시도한다."""

from __future__ import annotations

import re
import time

import httpx

USER_AGENT = "Mozilla/5.0 (compatible; HeimdallrCall/1.0)"


_META_CHARSET_RE = re.compile(rb"charset=[\"']?([\w-]+)", re.IGNORECASE)


def decode_html(resp: httpx.Response, *, default: str = "utf-8") -> str:
    """응답 인코딩을 **추측하지 않고 응답에서 읽어** 디코딩한다.

    ★ 한국 사이트는 같은 도메인 안에서도 페이지마다 인코딩이 다르고, 바뀐다.
      실측 2026-08-13:
        · finance.naver.com/item/main.naver      → **UTF-8** (예전 관행은 euc-kr)
        · finance.naver.com/sise/management.naver → euc-kr
        · dart.fss.or.kr report/viewer.do         → MS949
      틀린 인코딩으로 읽으면 숫자는 ASCII라 멀쩡하고 **한글 라벨만 깨진다.**
      그러면 '매출액' 같은 계정을 못 찾아 "이 종목은 파싱 실패"로 조용히 집계된다
      — 원문에는 값이 멀쩡히 있는데도 그렇다.
    """
    charset = ""
    content_type = (resp.headers.get("content-type") or "").lower()
    if "charset=" in content_type:
        charset = content_type.split("charset=", 1)[1].split(";")[0].strip()
    if not charset:
        match = _META_CHARSET_RE.search(resp.content[:4096])
        if match:
            charset = match.group(1).decode("ascii", errors="ignore").lower()

    if charset in ("ms949", "x-windows-949", "windows-949", "ks_c_5601-1987"):
        charset = "cp949"
    for candidate in (charset, default, "cp949", "utf-8"):
        if not candidate:
            continue
        try:
            return resp.content.decode(candidate)
        except (UnicodeDecodeError, LookupError):
            continue
    return resp.content.decode(default, errors="replace")


def http_get(
    url: str,
    *,
    params: dict | None = None,
    timeout: float = 60.0,
    retries: int = 3,
    headers: dict | None = None,
) -> httpx.Response:
    last_exc: Exception | None = None
    merged = {"User-Agent": USER_AGENT, **(headers or {})}
    for attempt in range(retries):
        try:
            resp = httpx.get(
                url, params=params, timeout=timeout, follow_redirects=True, headers=merged
            )
            if resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"{resp.status_code}", request=resp.request, response=resp
                )
            resp.raise_for_status()
            return resp
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:  # 일시적 오류만
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"HTTP 조회 실패: {url}") from last_exc
