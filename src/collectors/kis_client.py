# PRD Ref: §5.4 · traps.md T15
"""한국투자증권 KIS Open API 클라이언트 — **시세 조회 전용.**

★★ 이 프로젝트는 매매를 하지 않는다.
   `KIS_ALLOWED_PATHS` 화이트리스트 밖의 경로는 **클라이언트 내부에서 차단**한다.
   호출부의 실수로도 주문 API에 닿지 않게 하는 것이 이 강제의 목적이다.

★ 접근토큰을 매 실행마다 새로 받으면 **발급 자체가 막힌다**(T15).
  `.cache/kis_token.json`에 만료시각과 함께 캐시하고 만료 전까지 재사용한다.
  GitHub Actions 러너는 매번 초기화되므로 actions/cache 또는 DB 보존이 필요하다(P10).

★ 유량 실전계좌 **초당 20건**. 1,300종목을 순회하면 스로틀러 없이는
  중간에 `EGW00201`로 죽는다. 안전 마진 18/초 토큰버킷을 강제한다.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from src.config.constants import (
    KIS_ALLOWED_PATHS,
    KIS_BASE_URL,
    KIS_RATE_LIMIT_PER_SEC,
    KIS_TOKEN_CACHE_PATH,
)
from src.utils.env import optional_env_bool, require_env

TOKEN_PATH = "/oauth2/tokenP"
#: 유량 초과 코드. **문서상 초당 20건인데 실측 1.8건/초에서도 발생한다**(T32).
RATE_LIMIT_CODE = "EGW00201"
RATE_LIMIT_RETRIES = 3
RATE_LIMIT_BACKOFF_SEC = 0.6
#: 만료 직전 갱신 여유. 경계에서 401이 나면 배치가 통째로 흔들린다.
TOKEN_REFRESH_MARGIN_SEC = 600


class KisPathNotAllowed(RuntimeError):
    """화이트리스트 밖 경로 호출 시도. **주문 API 방어선이다.**"""


class KisError(RuntimeError):
    """KIS가 실패를 돌려줬다. 폴백은 호출부가 결정한다."""


@dataclass
class TokenBucket:
    """초당 `rate`건으로 제한한다. 스레드 안전."""

    rate: int
    _allowance: float = 0.0
    _last: float = 0.0

    def __post_init__(self) -> None:
        self._allowance = float(self.rate)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            self._allowance = min(
                self.rate, self._allowance + (now - self._last) * self.rate
            )
            self._last = now
            if self._allowance < 1.0:
                sleep_for = (1.0 - self._allowance) / self.rate
                time.sleep(sleep_for)
                self._allowance = 0.0
                self._last = time.monotonic()
            else:
                self._allowance -= 1.0


class KisClient:
    def __init__(self, *, base_url: str | None = None, rate: int | None = None):
        self.base_url = (base_url or KIS_BASE_URL).rstrip("/")
        self.bucket = TokenBucket(rate or KIS_RATE_LIMIT_PER_SEC)
        self.cache_path = Path(KIS_TOKEN_CACHE_PATH)
        self._token: str | None = None
        self._expires_at: datetime | None = None
        self.token_issue_count = 0  # 검증용 — 재실행 시 0이어야 캐시가 먹은 것이다
        self.rate_limit_hits = 0  # EGW00201 재시도 횟수(폴백으로 새지 않는지 감시)

    # ── 화이트리스트 ────────────────────────────────────────────────
    @staticmethod
    def _ensure_allowed(path: str) -> None:
        if path not in KIS_ALLOWED_PATHS:
            raise KisPathNotAllowed(
                f"허용되지 않은 KIS 경로: {path}. "
                "이 프로젝트는 시세 조회만 한다(주문 API 호출 금지)."
            )

    # ── 토큰 ────────────────────────────────────────────────────────
    def _load_cached_token(self) -> tuple[str, datetime] | None:
        if not self.cache_path.exists():
            return None
        try:
            body = json.loads(self.cache_path.read_text(encoding="utf-8"))
            token = body["access_token"]
            expires_at = datetime.fromisoformat(body["expires_at"])
        except (json.JSONDecodeError, KeyError, ValueError, OSError):
            return None  # 캐시가 깨졌으면 조용히 재발급한다
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return token, expires_at

    def _store_token(self, token: str, expires_at: datetime) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(
                {"access_token": token, "expires_at": expires_at.isoformat()},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def token(self) -> str:
        now = datetime.now(timezone.utc)
        margin = timedelta(seconds=TOKEN_REFRESH_MARGIN_SEC)

        if self._token and self._expires_at and self._expires_at - margin > now:
            return self._token

        cached = self._load_cached_token()
        if cached and cached[1] - margin > now:
            self._token, self._expires_at = cached
            return self._token

        # ★ 여기까지 왔을 때만 발급한다.
        self._ensure_allowed(TOKEN_PATH)
        resp = httpx.post(
            f"{self.base_url}{TOKEN_PATH}",
            json={
                "grant_type": "client_credentials",
                "appkey": require_env("KIS_APP_KEY"),
                "appsecret": require_env("KIS_APP_SECRET"),
            },
            headers={"content-type": "application/json"},
            timeout=30.0,
        )
        body = resp.json()
        token = body.get("access_token")
        if not token:
            raise KisError(f"토큰 발급 실패: {body}")
        expires_in = int(body.get("expires_in") or 86400)
        self._token = token
        self._expires_at = now + timedelta(seconds=expires_in)
        self._store_token(token, self._expires_at)
        self.token_issue_count += 1
        return token

    # ── 조회 ────────────────────────────────────────────────────────
    def get(self, path: str, *, tr_id: str, params: dict, timeout: float = 20.0) -> dict:
        """시세 조회. 화이트리스트·스로틀을 반드시 통과한다."""
        self._ensure_allowed(path)
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.token()}",
            "appkey": require_env("KIS_APP_KEY"),
            "appsecret": require_env("KIS_APP_SECRET"),
            "tr_id": tr_id,
            "custtype": "P",
        }

        # ★ EGW00201은 재시도로 회복된다(T32). 바로 폴백하면 KIS에만 있는
        #   per·시가총액·거래대금·상장주식수를 통째로 잃는다 —
        #   실측 1,112종목 중 111종목(10%)이 그렇게 빠졌었다.
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            self.bucket.acquire()
            resp = httpx.get(
                f"{self.base_url}{path}", params=params, headers=headers, timeout=timeout
            )
            try:
                body = resp.json()
            except ValueError as exc:
                raise KisError(f"JSON 아님: {resp.status_code} {resp.text[:200]}") from exc

            if body.get("rt_cd") in ("0", None):
                return body
            if body.get("msg_cd") == RATE_LIMIT_CODE and attempt < RATE_LIMIT_RETRIES:
                self.rate_limit_hits += 1
                time.sleep(RATE_LIMIT_BACKOFF_SEC * (attempt + 1))
                continue
            raise KisError(f"{body.get('msg_cd')} {body.get('msg1')}")
        raise KisError(f"{RATE_LIMIT_CODE} 재시도 소진")


def is_paper_trading() -> bool:
    return optional_env_bool("KIS_PAPER_TRADING", False)
