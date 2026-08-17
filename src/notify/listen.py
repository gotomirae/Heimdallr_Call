# PRD Ref: §8 · traps.md T13 · ADR 3(선별에 LLM을 쓰지 않는다), ADR 6
"""텔레그램 수신 — 종목명을 보내면 그 종목 리포트를 회신한다.

    python -m src.notify.listen --once          # 대기 중인 메시지 1회 처리
    python -m src.notify.listen --watch         # 롱폴링 루프
    python -m src.notify.listen --once --analyze  # 분석 없으면 LLM 호출까지

★★ **웹훅을 쓰지 않는다.** getUpdates 롱폴링이다. 공개 URL이 필요 없고,
   setWebhook은 클라이언트에서 영구 차단돼 있다(남의 봇을 죽이는 사고를 원천 봉쇄).

★★ **들어온 메시지는 데이터이지 명령이 아니다.**
   텍스트는 `resolve()`로 종목을 찾는 데만 쓴다. 안에 어떤 지시가 적혀 있든
   실행하지 않는다. 회신은 우리가 만든 형식뿐이고 사용자 텍스트를 그대로 되돌리지 않는다.

★★ **허용된 chat만 응답한다.** 봇 주소를 아는 누구나 말을 걸 수 있고,
   분석은 건당 실제 비용이 든다. 모르는 chat은 조용히 무시한다.

★ LLM은 **기존 분석이 없을 때만** 호출한다. 같은 종목을 여러 번 물어도 비용이 늘지 않는다.
"""

from __future__ import annotations

import argparse
import time

from src.db.supabase_client import select_all
from src.notify.resolve import Match, resolve
from src.notify.telegram import (
    SharedBotPollingBlocked,
    TelegramClient,
    TelegramError,
)
from src.utils.console import enable_utf8_stdout
from src.utils.env import optional_env

#: 롱폴링 대기(초). 텔레그램이 이 시간까지 붙들고 있다가 응답한다.
LONG_POLL_SEC = 25
#: 한 번에 가져올 업데이트 수.
BATCH = 20
#: 애매할 때 사용자에게 보여줄 후보 수. 넘으면 좁혀 달라고 한다.
MAX_CANDIDATES = 6


def allowed_chats() -> set[str]:
    """응답할 chat_id 집합.

    기본은 설정된 chat 하나뿐이다. `TELEGRAM_ALLOWED_CHAT_IDS`로 쉼표 구분 추가 가능.
    """
    client = TelegramClient()
    chats = {str(client.chat_id)}
    extra = optional_env("TELEGRAM_ALLOWED_CHAT_IDS")
    if extra:
        chats |= {c.strip() for c in extra.split(",") if c.strip()}
    return chats


def load_universe() -> dict[str, str]:
    return {
        u["code"]: u["name"]
        for u in select_all("krx_universe", "code,name")
        if u.get("name")
    }


# ═══════════════════════════════════════════════════════════════════
# offset — **텔레그램이 대신 기억한다.** 우리 DB에 저장하지 않는다.
# ═══════════════════════════════════════════════════════════════════
def confirm(client: TelegramClient, last_update_id: int) -> None:
    """처리한 데까지 확정한다.

    ★ getUpdates를 `offset = 마지막 update_id + 1`로 부르면 그 이하는 텔레그램 서버에서
      **영구 삭제**된다. 그래서 오프셋을 우리 DB에 둘 필요가 없다 —
      GitHub Actions처럼 매번 새로 뜨는 환경에서도 같은 메시지를 두 번 처리하지 않는다.
    ★ 확정을 **처리 후에** 한다. 중간에 죽으면 미확정분이 다시 온다(at-least-once).
      반대로 하면(먼저 확정) 죽는 순간 메시지가 조용히 사라진다.
    """
    client.call("getUpdates", {"offset": last_update_id + 1, "timeout": 0, "limit": 1})


# ═══════════════════════════════════════════════════════════════════
# 회신 조립 — 전부 우리가 만든 형식이다
# ═══════════════════════════════════════════════════════════════════
def format_candidates(matches: list[Match]) -> str:
    lines = [
        "🛡️ 여러 종목이 걸렸다. 어느 쪽인가?",
        "",
    ]
    for m in matches[:MAX_CANDIDATES]:
        lines.append(f"· {m.name} ({m.code})")
    if len(matches) > MAX_CANDIDATES:
        lines.append(f"… 외 {len(matches) - MAX_CANDIDATES}종목")
    lines += ["", "종목코드를 보내면 정확히 찾는다. 예: 005930"]
    return "\n".join(lines)


def format_not_found(text: str) -> str:
    # ★ 사용자 텍스트를 그대로 되돌리지 않는다(에코 회피). 길이만 알린다.
    return (
        "🛡️ 유니버스에서 그 종목을 찾지 못했다.\n\n"
        "· 정식 종목명 또는 6자리 종목코드를 보내라 (예: 삼성전자 / 005930)\n"
        "· 시가총액 1,000억원 미만이거나 은행·보험 등 제외 업종이면 대상이 아니다."
    )


def build_report(code: str, *, analyze: bool) -> tuple[str, dict]:
    """종목 리포트 텍스트를 만든다. 반환: (텍스트, 진단정보)"""
    from src.notify.run import build_flash_context
    from src.notify.templates import flash_message

    diag: dict = {"code": code, "llm_called": False}

    screens = [
        s for s in select_all(
            "screen_results", "code,fiscal_year,fiscal_quarter"
        ) if s["code"] == code
    ]
    if not screens:
        return (
            f"🛡️ {code} — 아직 스크리닝 결과가 없다.\n"
            "분기 재무가 수집되지 않았거나 상장 직후일 수 있다.",
            diag,
        )
    latest = max(screens, key=lambda s: s["fiscal_year"] * 4 + s["fiscal_quarter"])
    year, quarter = latest["fiscal_year"], latest["fiscal_quarter"]
    diag["quarter"] = f"{year}.{quarter}Q"

    if analyze:
        diag["llm_called"] = ensure_analysis(code, year, quarter, diag)

    ctx = build_flash_context(code, year, quarter)
    return flash_message(ctx), diag


def ensure_analysis(code: str, year: int, quarter: int, diag: dict) -> bool:
    """분석이 없을 때만 LLM을 호출한다. 호출했으면 True.

    ★ 같은 종목을 여러 번 물어도 비용이 늘지 않는다 — 있으면 그대로 쓴다.
    ★ 예산 초과·실패는 삼킨다. 리포트의 나머지(수치)는 여전히 유효하다.
    """
    existing = [
        a for a in select_all("analyses", "code,fiscal_year,fiscal_quarter")
        if a["code"] == code and a["fiscal_year"] == year and a["fiscal_quarter"] == quarter
    ]
    if existing:
        diag["analysis"] = "재사용"
        return False

    try:
        from src.analysis.analyze import analyze as run_analyze
        from src.analysis.analyze import save as save_analysis
        from src.analysis.run import build_input

        data = build_input(code, year=year, quarter=quarter)
        result = run_analyze(data, env="prod")
        save_analysis(result)
        diag["analysis"] = f"신규 호출 ${result.cost_usd:.4f}"
        return True
    except Exception as exc:
        diag["analysis"] = f"실패({type(exc).__name__})"
        return False


# ═══════════════════════════════════════════════════════════════════
# 처리
# ═══════════════════════════════════════════════════════════════════
def handle_message(
    client: TelegramClient,
    message: dict,
    universe: dict[str, str],
    *,
    analyze: bool,
    chats: set[str],
) -> dict:
    chat_id = str((message.get("chat") or {}).get("id", ""))
    text = (message.get("text") or "").strip()
    outcome: dict = {"chat_id": chat_id, "text_len": len(text)}

    # ★ 모르는 chat은 **조용히** 무시한다. 응답하면 봇의 존재와 동작을 알려주는 셈이다.
    if chat_id not in chats:
        outcome["result"] = "무시(허용되지 않은 chat)"
        return outcome

    if not text:
        outcome["result"] = "무시(텍스트 없음)"
        return outcome

    if text.split()[0].lower() in {"/start", "/help"}:
        client.send_message(
            "🛡️ Heimdallr Call\n\n"
            "종목명이나 6자리 종목코드를 보내면 그 종목의 실적 가속 판정을 보내준다.\n\n"
            "예: 삼성전자 / 005930\n\n"
            "· 스코어(A 성장가속 · B 수익성 · C 서프라이즈 · D 회계품질)\n"
            "· 주가반영도(PRI) — 낮을수록 아직 안 오른 종목\n"
            "· 후행 PER과 최근 4분기 순이익 기준 PER 병기"
        )
        outcome["result"] = "도움말"
        return outcome

    matches = resolve(text, universe)
    if not matches:
        client.send_message(format_not_found(text))
        outcome["result"] = "못 찾음"
        return outcome

    # 확신도가 낮고(부분 일치) 후보가 여럿이면 고르게 한다 — 단정하지 않는다.
    if len(matches) > 1 and matches[0].how in {"contains", "partial"}:
        client.send_message(format_candidates(matches))
        outcome["result"] = f"후보 {len(matches)}건 제시"
        return outcome

    match = matches[0]
    outcome["matched"] = f"{match.name}({match.code}) via {match.how}"
    text_out, diag = build_report(match.code, analyze=analyze)
    client.send_message(text_out)
    outcome["result"] = "리포트 발송"
    outcome.update(diag)
    return outcome


def poll_once(client: TelegramClient, *, analyze: bool, timeout: int = 0) -> list[dict]:
    universe = load_universe()
    chats = allowed_chats()

    updates = client.call(
        "getUpdates", {"timeout": timeout, "limit": BATCH}
    ).get("result", [])
    if not updates:
        return []

    results: list[dict] = []
    for upd in updates:
        msg = upd.get("message") or upd.get("edited_message")
        if not msg:
            continue
        try:
            results.append(
                handle_message(client, msg, universe, analyze=analyze, chats=chats)
            )
        except TelegramError as exc:
            # 회신 실패로 같은 메시지에 갇히면 안 된다 — 기록하고 확정은 그대로 진행한다.
            results.append({"result": f"발송 실패: {exc}"})

    confirm(client, updates[-1]["update_id"])
    return results


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="텔레그램 수신 — 종목 조회")
    parser.add_argument("--once", action="store_true", help="대기 중인 것만 1회 처리")
    parser.add_argument("--watch", action="store_true", help="롱폴링 루프")
    parser.add_argument("--analyze", action="store_true",
                        help="분석이 없으면 LLM 호출 (기본은 DB 수치만)")
    args = parser.parse_args()

    line = "═" * 72
    print(line)
    client = TelegramClient()
    from src.notify.telegram import bot_id_of

    print(f"봇 {bot_id_of(client.token)} · 전용봇 {client.is_dedicated_bot}")
    if not client.is_dedicated_bot:
        print("✗ 공유 봇이다. 수신은 막혀 있다 — HEIMDALLR_TELEGRAM_BOT_TOKEN을 넣어라.")
        return 1
    print(f"허용 chat: {sorted(allowed_chats())} · LLM 분석 {'ON' if args.analyze else 'OFF'}")
    print(line)

    if args.watch:
        # ★ 롱폴링은 오래 도는 프로세스다. 파이프로 넘기면 stdout이 블록 버퍼링되어
        #   **돌고 있는지 죽었는지 구분할 수 없다.** 매 출력마다 flush한다.
        say = lambda m: print(m, flush=True)
        say(f"롱폴링 시작 · {LONG_POLL_SEC}초 대기 (Ctrl+C로 종료)")
        idle = 0
        last_error: str | None = None
        backoff = 5
        while True:
            try:
                results = poll_once(client, analyze=args.analyze, timeout=LONG_POLL_SEC)
                for r in results:
                    say(f"  {r}")
                last_error = None  # 한 번 성공하면 다음 오류는 다시 알린다
                if results:
                    idle = 0
                else:
                    idle += 1
                    # 살아 있다는 신호. 매번 찍으면 소음이라 5회(약 2분)마다.
                    if idle % 5 == 0:
                        say(f"  … 대기 중 ({idle * LONG_POLL_SEC}초 무응답)")
            except SharedBotPollingBlocked as exc:
                say(f"✗ {exc}")
                return 1
            except KeyboardInterrupt:
                say("종료")
                return 0
            except Exception as exc:  # 폴링이 죽으면 안 된다
                # ★ 같은 오류가 이어지면 한 번만 찍는다. 매 주기 찍으면 로그가
                #   경고로 뒤덮여 **정작 처리 기록이 묻힌다**(실측: ConnectTimeout 연속).
                kind = type(exc).__name__
                if kind != last_error:
                    say(f"  ⚠ {kind}: {str(exc)[:80]}")
                    last_error = kind
                    backoff = 5
                else:
                    backoff = min(backoff * 2, 60)  # 계속 실패하면 천천히
                time.sleep(backoff)
        return 0

    results = poll_once(client, analyze=args.analyze, timeout=0)
    print(f"처리 {len(results)}건")
    for r in results:
        print(f"  {r}")
    if not results:
        print("  (대기 중인 메시지 없음)")
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
