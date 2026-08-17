# PRD Ref: §8 전체 · traps.md T13
"""텔레그램 — 발송(sendMessage) + 수신(getUpdates 폴링).

★★ `setWebhook`은 **영구 차단**이다. 봇을 분리한 뒤에도 풀지 않는다.
   텔레그램은 봇당 웹훅을 1개만 허용하고 새로 등록하면 이전 것이 **에러 없이
   덮어써진다.** 이 프로젝트는 웹훅이 필요 없다(getUpdates 폴링을 쓴다) —
   있지도 않은 필요 때문에 남의 봇을 죽일 위험을 열어둘 이유가 없다.
   호출부의 실수로도 닿지 않도록 **화이트리스트를 클라이언트 안에서 강제**한다.

★★ **봇 분리 강제.** `HERMESCALL_BOT_ID`와 같은 봇으로는 `getUpdates`를 하지 않는다.
   공유 봇에서 폴링하면 HermesCall 앞으로 온 메시지를 **가로채 소비**한다.
   getUpdates는 읽은 업데이트를 확인(offset)하는 순간 상대에게 다시 오지 않는다 —
   HermesCall 명령어가 "가끔 씹히는" 형태로 조용히 망가진다. 재현도 어렵다.

★ 발송은 공유 봇으로도 안전하다(sendMessage는 상태를 소비하지 않는다).
  그래서 분리 전에도 알림은 계속 나간다 — 수신만 막는다.

★ rate limit: 연속 발송 사이 1초, 429의 `retry_after`를 존중해 3회까지 백오프.

★ 발송 실패가 파이프라인을 죽이면 안 된다. 이미 DB에 저장되어 대시보드로 볼 수 있다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from src.utils.env import optional_env, require_env

API_BASE = "https://api.telegram.org/bot{token}/{method}"

#: ★ 이 목록 밖의 메서드는 호출하지 않는다. `setWebhook`이 여기 없는 것이 요점이다.
#:   `getUpdates`는 들어 있지만, 아래 봇 분리 검사를 통과해야 실제로 호출된다.
ALLOWED_METHODS = frozenset({"sendMessage", "getMe", "getUpdates"})

#: 수신(폴링)에만 해당하는 메서드. 공유 봇에서는 이것들을 막는다.
RECEIVING_METHODS = frozenset({"getUpdates"})

#: HermesCall이 쓰는 봇 ID. 토큰 앞의 숫자이며 **시크릿이 아니다**(공개해도 무해).
#: 이 봇으로 폴링하면 HermesCall 메시지를 가로챈다.
HERMESCALL_BOT_ID = "8605695587"


class SharedBotPollingBlocked(RuntimeError):
    """공유 봇에서 수신을 시도했다. **HermesCall 메시지 가로채기 방어선이다.**"""


def bot_id_of(token: str) -> str:
    """토큰에서 봇 ID를 뽑는다. `<봇ID>:<시크릿>` 형식이다."""
    return token.split(":", 1)[0].strip()

#: 텔레그램 메시지 상한. 넘으면 잘라 보내야 한다.
MAX_MESSAGE_CHARS = 4096
SEND_INTERVAL_SEC = 1.0
RATE_LIMIT_RETRIES = 3
PREFIX = "🛡️"  # HermesCall의 ⚡/🔬와 구분


class TelegramMethodNotAllowed(RuntimeError):
    """화이트리스트 밖 메서드 호출 시도. **HermesCall 웹훅 방어선이다.**"""


class TelegramError(RuntimeError):
    """텔레그램이 실패를 돌려줬다. 호출부가 파이프라인을 죽이지 않도록 잡는다."""


@dataclass
class SendStats:
    sent: int = 0
    failed: int = 0
    blocked_duplicate: int = 0
    truncated: int = 0
    rate_limit_hits: int = 0
    errors: dict[str, int] = field(default_factory=dict)


class TelegramClient:
    def __init__(self, *, token: str | None = None, chat_id: str | None = None):
        self._token = token
        self._chat_id = chat_id
        self._last_send_at = 0.0
        self.stats = SendStats()

    @property
    def token(self) -> str:
        """Heimdallr 전용 토큰을 **우선** 쓰고, 없으면 공유 토큰으로 떨어진다.

        공유 토큰으로도 발송은 안전하므로 알림이 끊기지는 않는다. 수신만 막힌다.
        """
        if self._token:
            return self._token
        dedicated = optional_env("HEIMDALLR_TELEGRAM_BOT_TOKEN")
        return dedicated or require_env("TELEGRAM_BOT_TOKEN")

    @property
    def chat_id(self) -> str:
        if self._chat_id:
            return self._chat_id
        dedicated = optional_env("HEIMDALLR_TELEGRAM_CHAT_ID")
        return dedicated or require_env("TELEGRAM_CHAT_ID")

    @property
    def is_dedicated_bot(self) -> bool:
        """HermesCall과 다른 봇인가. 수신을 허용할지의 유일한 기준이다."""
        return bot_id_of(self.token) != HERMESCALL_BOT_ID

    def _ensure_allowed(self, method: str) -> None:
        if method not in ALLOWED_METHODS:
            raise TelegramMethodNotAllowed(
                f"허용되지 않은 텔레그램 메서드: {method}. "
                "setWebhook은 봇을 분리한 뒤에도 영구 차단이다 — 이 프로젝트는 "
                "웹훅이 필요 없고(getUpdates 폴링), 잘못 부르면 남의 봇이 "
                "에러 없이 죽는다(traps.md T13)."
            )
        if method in RECEIVING_METHODS and not self.is_dedicated_bot:
            raise SharedBotPollingBlocked(
                f"봇 {HERMESCALL_BOT_ID}는 HermesCall과 공유 중이라 수신({method})을 막았다. "
                "폴링하면 HermesCall 앞으로 온 메시지를 가로채 소비한다 — "
                "명령어가 '가끔 씹히는' 형태로 조용히 망가지고 재현도 어렵다. "
                "@BotFather로 새 봇을 만들어 HEIMDALLR_TELEGRAM_BOT_TOKEN에 넣어라. "
                "(발송은 공유 봇으로도 계속 동작한다.)"
            )

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_send_at
        if elapsed < SEND_INTERVAL_SEC:
            time.sleep(SEND_INTERVAL_SEC - elapsed)
        self._last_send_at = time.monotonic()

    def call(self, method: str, payload: dict) -> dict:
        self._ensure_allowed(method)
        url = API_BASE.format(token=self.token, method=method)

        for attempt in range(RATE_LIMIT_RETRIES + 1):
            self._throttle()
            # ★ 롱폴링은 텔레그램이 `timeout`초까지 응답을 **붙들고 있는다.**
            #   HTTP 타임아웃이 그보다 짧거나 비슷하면 정상 대기를 실패로 오인해
            #   매 주기 예외가 나고 로그가 경고로 뒤덮인다(실측: 25초 폴링 + 30초 제한).
            #   읽기 제한은 롱폴링 대기보다 넉넉히 길어야 한다.
            wait = float(payload.get("timeout") or 0)
            resp = httpx.post(
                url,
                json=payload,
                timeout=httpx.Timeout(wait + 30.0, connect=15.0),
            )
            try:
                body = resp.json()
            except ValueError as exc:
                raise TelegramError(f"JSON 아님: {resp.status_code}") from exc

            if body.get("ok"):
                return body

            # 429는 retry_after를 존중해 백오프한다(봇 토큰을 HermesCall과 나눠 쓴다).
            if resp.status_code == 429 and attempt < RATE_LIMIT_RETRIES:
                retry_after = int(
                    (body.get("parameters") or {}).get("retry_after", 1)
                )
                self.stats.rate_limit_hits += 1
                time.sleep(retry_after + 0.5)
                continue

            raise TelegramError(
                f"{body.get('error_code')} {body.get('description')}"
            )
        raise TelegramError("429 재시도 소진")

    def send_message(
        self,
        text: str,
        *,
        disable_preview: bool = True,
        parse_mode: str | None = "HTML",
    ) -> dict:
        """메시지 1건 발송.

        ★ 기본 `parse_mode="HTML"`. **모바일 가독성의 핵심이다.**
          텔레그램 기본 폰트는 가변폭이라 공백으로 숫자를 정렬할 수 없다 —
          자릿수가 제각각으로 흩어져 표가 표로 안 보인다.
          `<pre>` 블록만 고정폭으로 렌더되므로, 숫자 표는 반드시 그 안에 넣는다.
        ★ HTML 모드에서는 `& < >`가 태그로 해석된다. 본문에 넣을 값은
          `esc()`로 이스케이프해야 발송이 400으로 실패하지 않는다.
        """
        text, truncated = truncate(text)
        if truncated:
            self.stats.truncated += 1
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": disable_preview,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        body = self.call("sendMessage", payload)
        self.stats.sent += 1
        return body


def esc(value) -> str:
    """HTML parse_mode에서 안전한 문자열로. 종목명·업종에 `&`가 실제로 들어온다."""
    if value is None:
        return "—"
    return (
        str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def truncate(text: str, limit: int = MAX_MESSAGE_CHARS) -> tuple[str, bool]:
    """4,096자 상한. 넘으면 **줄 단위로** 자르고 잘렸다는 사실을 남긴다."""
    if len(text) <= limit:
        return text, False
    marker = "\n…(이하 생략)"
    budget = limit - len(marker)
    cut = text[:budget]
    # 줄 중간에서 자르면 표가 깨진다. 마지막 개행까지만 남긴다.
    newline = cut.rfind("\n")
    if newline > budget * 0.5:
        cut = cut[:newline]
    return cut + marker, True


# ═══════════════════════════════════════════════════════════════════
# 중복 차단 — notifications UNIQUE(code, fiscal_year, fiscal_quarter, kind)
# ═══════════════════════════════════════════════════════════════════
def already_sent(code: str, fiscal_year: int, fiscal_quarter: int, kind: str) -> bool:
    """★ 텔레그램/Actions 재시도로 같은 알림이 두 번 나가는 건 실제로 자주 있다."""
    from src.db.supabase_client import get_client

    rows = (
        get_client()
        .table("notifications")
        .select("id")
        .eq("code", code)
        .eq("fiscal_year", fiscal_year)
        .eq("fiscal_quarter", fiscal_quarter)
        .eq("kind", kind)
        .limit(1)
        .execute()
        .data
        or []
    )
    return bool(rows)


def record_notification(
    code: str | None, fiscal_year: int | None, fiscal_quarter: int | None,
    kind: str, payload: dict,
) -> None:
    from src.db.supabase_client import get_client

    get_client().table("notifications").insert(
        {
            "code": code,
            "fiscal_year": fiscal_year,
            "fiscal_quarter": fiscal_quarter,
            "kind": kind,
            "payload": payload,
        }
    ).execute()


def send_once(
    client: TelegramClient,
    *,
    code: str | None,
    fiscal_year: int | None,
    fiscal_quarter: int | None,
    kind: str,
    text: str,
    payload: dict | None = None,
) -> bool:
    """중복을 차단하고 1건 발송한다. 발송 실패해도 예외를 올리지 않는다.

    반환값: 실제로 보냈으면 True, 중복이거나 실패했으면 False.
    """
    if code is not None and fiscal_year is not None and fiscal_quarter is not None:
        if already_sent(code, fiscal_year, fiscal_quarter, kind):
            client.stats.blocked_duplicate += 1
            return False

    try:
        client.send_message(text)
    except Exception as exc:
        # ★ 발송 실패가 파이프라인을 죽이면 안 된다(PRD §8.2).
        client.stats.failed += 1
        key = type(exc).__name__
        client.stats.errors[key] = client.stats.errors.get(key, 0) + 1
        return False

    try:
        record_notification(
            code, fiscal_year, fiscal_quarter, kind, payload or {"text": text}
        )
    except Exception:
        # 기록 실패는 발송 성공을 되돌리지 못한다. 다음 실행에서 중복이 날 수 있다.
        client.stats.errors["record_failed"] = (
            client.stats.errors.get("record_failed", 0) + 1
        )
    return True
