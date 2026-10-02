# PRD Ref: §8.3, §8.4, §10 · traps.md T40
"""일괄 발송 — ⚡즉시 알림(★/○)과 📊일일 요약.

    python -m src.notify.batch --flash            # 대상만 출력
    python -m src.notify.batch --flash --send     # 실제 발송
    python -m src.notify.batch --digest --send
    python -m src.notify.batch --digest-gate --gate-output "$GITHUB_OUTPUT"   # 오늘 몫이 끝났으면 skip=true
    python -m src.notify.batch --suppress         # 억제 대상만 출력
    python -m src.notify.batch --suppress --save  # 이력에만 남기고 발송은 안 함

★ `screen_results`는 분기 이력이 쌓이므로 **종목별 최신 1행으로 접어서** 읽는다(T40).
  전체를 그대로 집계하면 같은 종목이 여러 번 세어지고 구 로직 값이 섞인다.

★ 중복 발송은 `send_once`가 `notifications` 테이블로 막는다.
  같은 (종목, 분기, 종류)는 두 번 나가지 않는다 — 워크플로가 하루 38회 돌아도 안전하다.
  ★★ 단, 📊일일 요약은 code가 NULL이라 그 검사를 **건너뛴다**(T228 — UNIQUE도 NULL끼리는
  서로 다르다). 요약은 `payload.digest_date`(KR 날짜)로 따로 막는다(`find_daily`).

★★ 억제(`--suppress`)는 그 중복 차단을 **의도적으로 미리 채우는** 장치다.
  이미 발표가 끝난 분기의 backlog가 알림으로 한꺼번에 쏟아지는 것을 막는다.
  발송 이력에 남되 `payload.suppressed=true`로 **실제 발송과 반드시 구분**한다 —
  같은 표시로 남기면 `/settings`의 "발송 이력"이 보내지도 않은 건수를 세어
  **에러 없이 거짓말을 한다.** 대시보드는 이 표식을 읽어 따로 센다.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config.constants import (
    DASHBOARD_URL_DEFAULT,
    FLASH_DAILY_MAX,
    KOREA_MARKET_COMPLETED_HOUR_KST,
    NOTIFY_GRADES,
)
from src.db.supabase_client import get_client, select_all
from src.notify.run import build_flash_context
from src.notify.telegram import (
    TelegramClient,
    TelegramError,
    already_sent,
    record_notification,
    send_once,
)
from src.notify.templates import KIND_DAILY, KIND_FLASH, daily_digest, flash_message
from src.screener.score import active_score
from src.utils.console import enable_utf8_stdout
from src.utils.env import optional_env

SCREEN_COLUMNS = (
    "code,fiscal_year,fiscal_quarter,gate_passed,grade,score_flash,score_final,pri,"
    "has_consensus,base_effect_warning"
)
KST = ZoneInfo("Asia/Seoul")


# ═══ 일일 요약 1일 1회 (T228) ══════════════════════════════════════
def digest_day(now: datetime) -> date:
    """요약이 속한 KR 날짜 = 확정 종가 시각(16:00 KST)이 가장 최근에 지난 날.

    ★ 실행 시각의 날짜를 쓰면 GitHub 지연으로 자정을 넘긴 실행(10/1분이 00:37 시작)이
      **다음 날 요약**이 되어 그날 정시 요약까지 막는다. `confirmed_bars`와 같은 16시 경계다.
    손계산: 10/1 17:37 → 10/1 · 10/2 00:37 → 10/1 · 10/2 15:59 → 10/1 · 10/2 16:00 → 10/2
    """
    return (now.astimezone(KST) - timedelta(hours=KOREA_MARKET_COMPLETED_HOUR_KST)).date()


def entry_checks_state(summary: dict | None, run_day: str) -> dict:
    """같은 잡의 entry_checks 요약 → 요약 이력에 남길 상태. 이번 실행 것이 아니면 'missing'."""
    if not summary or summary.get("date") != run_day:
        return {"status": "missing"}
    return {
        "status": summary.get("status") or "missing",
        "check_date": summary.get("check_date"),
        "saved": int(summary.get("saved") or 0),
    }


def day_complete(row: dict | None) -> bool:
    """오늘 몫(요약 발송 + entry_checks 저장 완료)이 끝났는가. 판정 불가는 False(= 다시 돈다)."""
    state = ((row or {}).get("payload") or {}).get("entry_checks") or {}
    return state.get("status") == "complete" and int(state.get("saved") or 0) > 0


def find_daily(day: date) -> dict | None:
    rows = (
        get_client().table("notifications").select("id,payload,sent_at")
        .eq("kind", KIND_DAILY).eq("payload->>digest_date", day.isoformat())
        .order("id").limit(1).execute().data
        or []
    )
    return rows[0] if rows else None


def run_digest_gate(output: str | None) -> int:
    """pg_cron 정시 실행과 예비 schedule이 같은 날 둘 다 돌 때 뒤의 것을 즉시 끝낸다.

    ★ 판정에 실패하면 skip=false(= 그냥 돈다). 중복 발송은 뒤 단계의 키가 막는다 —
      게이트는 비용 절감이지 중복 방어의 유일한 선이 아니다. 그래서 여기서는 실패를 삼킨다.
    """
    day = digest_day(datetime.now(KST))
    try:
        row = find_daily(day)
    except Exception as exc:
        print(f"⚠ 오늘 요약 이력 조회 실패({type(exc).__name__}) — 게이트 없이 진행")
        row = None
    skip = day_complete(row)
    state = ((row or {}).get("payload") or {}).get("entry_checks")
    print(f"digest_day {day} · 요약 {'발송됨' if row else '없음'} · entry_checks {state} → skip={str(skip).lower()}")
    if output:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write(f"skip={str(skip).lower()}\n")
    return 0


def _read_summary(env_name: str) -> dict | None:
    path = optional_env(env_name)
    if not path:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _qi(row: dict) -> int:
    return row["fiscal_year"] * 4 + (row["fiscal_quarter"] - 1)


def latest_screens() -> list[dict]:
    """종목별 최신 스크리닝 결과 1행씩 (T40)."""
    latest: dict[str, dict] = {}
    for row in select_all("screen_results", SCREEN_COLUMNS):
        prev = latest.get(row["code"])
        if prev is None or _qi(row) > _qi(prev):
            latest[row["code"]] = row
    return list(latest.values())


def revenue_yoy_map(targets: list[dict]) -> dict[str, float | None]:
    """대상 종목의 해당 분기 매출 YoY. 요약 표의 마지막 열이다.

    ★ 분기를 맞춰서 읽는다 — 종목마다 평가 분기가 다르다(T36).
    """
    wanted = {(r["code"], r["fiscal_year"], r["fiscal_quarter"]) for r in targets}
    out: dict[str, float | None] = {}
    for f in select_all(
        "quarterly_fundamentals", "code,fiscal_year,fiscal_quarter,revenue_yoy"
    ):
        key = (f["code"], f["fiscal_year"], f["fiscal_quarter"])
        if key in wanted:
            out[f["code"]] = f.get("revenue_yoy")
    return out


def notify_targets() -> list[dict]:
    """발송 대상 — **★/○ 만**(constants.NOTIFY_GRADES).

    △·는 대시보드에만 남긴다. 발송 대상이 넓어지면 알림이 소음이 되고,
    소음이 되면 진짜 신호도 안 읽힌다.
    """
    rows = [r for r in latest_screens() if r.get("grade") in NOTIFY_GRADES]
    rows.sort(key=lambda r: -(active_score(r) or 0))
    return rows


def run_flash(send: bool, limit: int) -> int:
    names = {u["code"]: u["name"] for u in select_all("krx_universe", "code,name")}
    targets = notify_targets()
    print(f"발송 대상(★/○) {len(targets)}종목 · 상한 {limit}")

    client = TelegramClient()
    sent = skipped = failed = 0
    for row in targets[:limit]:
        code, year, quarter = row["code"], row["fiscal_year"], row["fiscal_quarter"]
        label = f"{row['grade']} {names.get(code, code)}({code}) {year}.{quarter}Q"

        if already_sent(code, year, quarter, KIND_FLASH):
            skipped += 1
            continue
        if not send:
            print(f"  [미발송] {label} 점수 {(active_score(row) or 0):.1f}")
            continue

        try:
            ctx = build_flash_context(code, year, quarter)
            ok = send_once(
                client, code=code, fiscal_year=year, fiscal_quarter=quarter,
                kind=KIND_FLASH, text=flash_message(ctx),
                payload={"grade": row.get("grade"), "score": active_score(row)},
            )
            sent += ok
            print(f"  {'✓' if ok else '✗'} {label}")
        except (TelegramError, Exception) as exc:  # 한 종목 실패가 나머지를 막지 않는다
            failed += 1
            print(f"  ⚠ {label}: {type(exc).__name__}: {str(exc)[:80]}")

    print(f"\n발송 {sent} · 중복 건너뜀 {skipped} · 실패 {failed}")
    return 0


def run_suppress(save: bool, reason: str) -> int:
    """이미 발표가 끝난 분기의 즉시 알림을 **보내지 않고 이력에만** 남긴다.

    왜 필요한가: T79로 발송 스텝이 오래 skipped였던 탓에 한 번도 안 나간 backlog가
    쌓였다. 고친 채로 그냥 켜면 **이미 몇 주 전에 발표된 실적**이 알림으로
    한꺼번에 쏟아진다. 발굴 결과는 대시보드에 이미 다 있으므로 알림만 건너뛴다.

    ★ 상한(`--limit`)을 적용하지 않는다 — 일부만 억제하면 **나머지가 다음 실행에
      그대로 나간다.** 그러면 "억제했다"는 기록만 남고 실제로는 절반이 발송된다.
    ★ `already_sent`가 이미 막고 있는 건은 건너뛴다. 실제 발송 이력을
      억제 표식으로 덮으면 과거에 진짜 보낸 사실이 사라진다.
    """
    names = {u["code"]: u["name"] for u in select_all("krx_universe", "code,name")}
    targets = notify_targets()

    by_quarter: dict[str, int] = {}
    for row in targets:
        key = f"{row['fiscal_year']}.{row['fiscal_quarter']}Q"
        by_quarter[key] = by_quarter.get(key, 0) + 1

    print(f"억제 대상(★/○) {len(targets)}종목 — 발송하지 않고 이력에만 남긴다")
    for key in sorted(by_quarter):
        print(f"  {key}: {by_quarter[key]}종목")
    print(f"사유: {reason}\n")

    marked = skipped = failed = 0
    for row in targets:
        code, year, quarter = row["code"], row["fiscal_year"], row["fiscal_quarter"]
        label = f"{row['grade']} {names.get(code, code)}({code}) {year}.{quarter}Q"

        if already_sent(code, year, quarter, KIND_FLASH):
            skipped += 1
            continue
        if not save:
            print(f"  [억제예정] {label}")
            continue

        try:
            record_notification(
                code, year, quarter, KIND_FLASH,
                {
                    # ★ 이 표식이 없으면 화면이 "발송 78건"으로 거짓말한다.
                    "suppressed": True,
                    "reason": reason,
                    "grade": row.get("grade"),
                    "score": active_score(row),
                },
            )
            marked += 1
            print(f"  ✓ {label}")
        except Exception as exc:  # 한 건 실패가 나머지를 막지 않는다
            failed += 1
            print(f"  ⚠ {label}: {type(exc).__name__}: {str(exc)[:80]}")

    if not save:
        print("\n(--save 미지정 — 아무것도 기록하지 않았다)")
    else:
        print(f"\n억제 기록 {marked} · 이미 이력 있음 {skipped} · 실패 {failed}")
    return 0


def run_digest(send: bool) -> int:
    now = datetime.now(KST)
    today = now.date()
    day = digest_day(now)
    names = {u["code"]: u["name"] for u in select_all("krx_universe", "code,name")}
    rows = latest_screens()
    targets = notify_targets()

    counts = {
        "gate_passed": sum(1 for r in rows if r.get("gate_passed") is True),
        "disclosures": len(
            [d for d in select_all("earnings_disclosures", "rcept_no,disclosed_at")
             if str(d.get("disclosed_at") or "")[:10] == day.isoformat()]
        ),
    }
    for grade in ("★", "○", "△"):
        counts[grade] = sum(1 for r in rows if r.get("grade") == grade)

    yoy = revenue_yoy_map(targets[:FLASH_DAILY_MAX])
    ctx = {
        "date": day.isoformat(),
        "counts": counts,
        "rows": [
            {
                "grade": r.get("grade"), "name": names.get(r["code"], r["code"]),
                "score": active_score(r), "pri": r.get("pri"),
                "revenue_yoy": yoy.get(r["code"]),
                "has_consensus": r.get("has_consensus"),
                "base_effect_warning": r.get("base_effect_warning"),
            }
            for r in targets[:FLASH_DAILY_MAX]
        ],
        "url": optional_env("DASHBOARD_BASE_URL", DASHBOARD_URL_DEFAULT),
    }
    if optional_env("TECHNICAL_SCAN_SUMMARY_PATH"):
        summary = _read_summary("TECHNICAL_SCAN_SUMMARY_PATH")
        ctx["technical_scan"] = (
            summary if summary and summary.get("date") == today.isoformat() else {"status": "scan_failed"}
        )
    entry_state = entry_checks_state(_read_summary("ENTRY_CHECKS_SUMMARY_PATH"), today.isoformat())
    text = daily_digest(ctx)
    print(text)

    if not send:
        print("\n(--send 미지정 — 발송하지 않았다)")
        return 0

    existing = find_daily(day)
    if existing is not None:
        # 이미 보냈다. 앞 실행의 entry_checks가 미완이었고 이번에 끝났으면 표식만 고쳐
        # 다음 재시도·예비 실행이 게이트에서 바로 끝나게 한다(텔레그램은 다시 안 보낸다).
        if not day_complete(existing) and day_complete({"payload": {"entry_checks": entry_state}}):
            get_client().table("notifications").update(
                {"payload": {**(existing.get("payload") or {}), "entry_checks": entry_state}}
            ).eq("id", existing["id"]).execute()
            print(f"\n· {day} 요약은 이미 발송됨(id {existing['id']}) — entry_checks 완료 표식만 갱신")
        else:
            print(f"\n· {day} 요약은 이미 발송됨(id {existing['id']}) — 재발송하지 않는다")
        return 0

    client = TelegramClient()
    ok = send_once(
        client, code=None, fiscal_year=None, fiscal_quarter=None,
        kind=KIND_DAILY, text=text,
        payload={**counts, "digest_date": day.isoformat(), "entry_checks": entry_state},
    )
    print(f"\n{'✓ 발송' if ok else '✗ 발송 안 됨(중복이거나 실패)'}")
    return 0


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="일괄 발송")
    parser.add_argument("--flash", action="store_true", help="★/○ 즉시 알림")
    parser.add_argument("--digest", action="store_true", help="일일 요약")
    parser.add_argument("--digest-gate", action="store_true",
                        help="오늘 요약·entry_checks가 이미 끝났으면 skip=true (워크플로 게이트)")
    parser.add_argument("--gate-output", help="게이트 결과를 덧붙일 파일($GITHUB_OUTPUT)")
    parser.add_argument("--suppress", action="store_true",
                        help="발송하지 않고 이력에만 남긴다(이미 발표된 backlog용)")
    parser.add_argument("--send", action="store_true", help="실제 발송")
    parser.add_argument("--save", action="store_true", help="억제를 실제로 기록")
    parser.add_argument("--reason", default="이미 발표가 끝난 분기 — 대시보드에만 반영",
                        help="억제 사유(이력에 함께 남는다)")
    parser.add_argument("--limit", type=int, default=FLASH_DAILY_MAX,
                        help="한 실행에서 보낼 즉시 알림 상한")
    args = parser.parse_args()

    line = "═" * 72
    print(line)
    if args.digest_gate:
        result = run_digest_gate(args.gate_output)
    elif args.suppress:
        result = run_suppress(args.save, args.reason)
    elif args.digest:
        result = run_digest(args.send)
    else:
        result = run_flash(args.send, args.limit)
    print(line)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
