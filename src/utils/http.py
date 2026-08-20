# PRD Ref: §5 (데이터 아키텍처)
"""공용 HTTP 헬퍼. 일시적 오류만 재시도한다."""

from __future__ import annotations

import random
import re
import time

import httpx

USER_AGENT = "Mozilla/5.0 (compatible; HeimdallrCall/1.0)"

#: 재시도해도 소용없는 상태코드는 **즉시 포기**한다.
#: 404·403에 세 번 매달리면 실패를 늦게 알 뿐이고, 상대 서버만 더 때린다.
#: 429(과요청)는 예외 — 기다리면 풀린다.
_RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504, 509, 520, 522, 524})


def _sleep_seconds(attempt: int, resp: httpx.Response | None) -> float:
    """지수 백오프 + 지터. `Retry-After`를 주면 그 값을 존중한다.

    ★ 지터가 없으면 같은 순간에 재시도가 몰린다 — 상대가 흔들리는 그 순간에
      정확히 같은 간격으로 다시 때리는 꼴이라 회복을 방해한다.
    """
    if resp is not None:
        raw = resp.headers.get("retry-after", "").strip()
        if raw.isdigit():
            return min(float(raw), 30.0)
    return min(1.5 * (2**attempt), 20.0) + random.uniform(0, 0.75)


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
    retries: int = 5,
    headers: dict | None = None,
) -> httpx.Response:
    """GET. **일시적 오류만** 재시도한다.

    ★ 재시도가 부족하면 남의 서버가 몇 초 흔들린 것으로 **우리 잡 전체가 죽는다.**
      실측 2026-08-19: KIND(kind.krx.co.kr)가 잠깐 응답하지 않아 `universe_daily`가
      통째로 실패했다. 그때는 3회 · 1.5s/3.0s여서 **총 4.5초만 버티고 포기**했다.
      지금은 5회 · 지수 백오프(1.5→3→6→12s, 지터 포함)로 **약 25초**를 버틴다.
      상대 서버의 짧은 딸꾹질과 진짜 장애를 구분하려면 이 정도는 필요하다.

    ★ 4xx는 재시도하지 않는다(429 제외). 404에 다섯 번 매달려 봐야 실패를 늦출 뿐이다.
    """
    last_exc: Exception | None = None
    merged = {"User-Agent": USER_AGENT, **(headers or {})}
    for attempt in range(retries):
        resp: httpx.Response | None = None
        try:
            resp = httpx.get(
                url, params=params, timeout=timeout, follow_redirects=True, headers=merged
            )
            if resp.status_code in _RETRYABLE_STATUSES or resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"{resp.status_code}", request=resp.request, response=resp
                )
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            status = exc.response.status_code
            # ★ 되돌릴 수 없는 4xx는 즉시 끝낸다.
            if status < 500 and status not in _RETRYABLE_STATUSES:
                raise RuntimeError(f"HTTP {status}: {url}") from exc
        except httpx.TransportError as exc:  # 연결·타임아웃 — 전형적인 일시 오류
            last_exc = exc
            resp = None

        if attempt < retries - 1:
            time.sleep(_sleep_seconds(attempt, resp))

    raise RuntimeError(f"HTTP 조회 실패({retries}회 재시도): {url}") from last_exc
