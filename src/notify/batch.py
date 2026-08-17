# PRD Ref: §8.3, §8.4, §10 · traps.md T40
"""일괄 발송 — ⚡즉시 알림(★/○)과 📊일일 요약.

    python -m src.notify.batch --flash            # 대상만 출력
    python -m src.notify.batch --flash --send     # 실제 발송
    python -m src.notify.batch --digest --send

★ `screen_results`는 분기 이력이 쌓이므로 **종목별 최신 1행으로 접어서** 읽는다(T40).
  전체를 그대로 집계하면 같은 종목이 여러 번 세어지고 구 로직 값이 섞인다.

★ 중복 발송은 `send_once`가 `notifications` 테이블로 막는다.
  같은 (종목, 분기, 종류)는 두 번 나가지 않는다 — 워크플로가 하루 38회 돌아도 안전하다.
"""

from __future__ import annotations

import argparse
from datetime import date

from src.config.constants import FLASH_DAILY_MAX, NOTIFY_GRADES
from src.db.supabase_client import select_all
from src.notify.run import build_flash_context
from src.notify.telegram import TelegramClient, TelegramError, already_sent, send_once
from src.notify.templates import KIND_DAILY, KIND_FLASH, daily_digest, flash_message
from src.utils.console import enable_utf8_stdout
from src.utils.env import optional_env

SCREEN_COLUMNS = (
    "code,fiscal_year,fiscal_quarter,gate_passed,grade,score_flash,pri,"
    "has_consensus,base_effect_warning"
)


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
    rows.sort(key=lambda r: -(r.get("score_flash") or 0))
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
            print(f"  [미발송] {label} 점수 {row.get('score_flash'):.1f}")
            continue

        try:
            ctx = build_flash_context(code, year, quarter)
            ok = send_once(
                client, code=code, fiscal_year=year, fiscal_quarter=quarter,
                kind=KIND_FLASH, text=flash_message(ctx),
                payload={"grade": row.get("grade"), "score": row.get("score_flash")},
            )
            sent += ok
            print(f"  {'✓' if ok else '✗'} {label}")
        except (TelegramError, Exception) as exc:  # 한 종목 실패가 나머지를 막지 않는다
            failed += 1
            print(f"  ⚠ {label}: {type(exc).__name__}: {str(exc)[:80]}")

    print(f"\n발송 {sent} · 중복 건너뜀 {skipped} · 실패 {failed}")
    return 0


def run_digest(send: bool) -> int:
    names = {u["code"]: u["name"] for u in select_all("krx_universe", "code,name")}
    rows = latest_screens()
    targets = notify_targets()

    counts = {
        "gate_passed": sum(1 for r in rows if r.get("gate_passed") is True),
        "disclosures": len(
            [d for d in select_all("earnings_disclosures", "rcept_no,disclosed_at")
             if d.get("disclosed_at") == date.today().isoformat()]
        ),
    }
    for grade in ("★", "○", "△"):
        counts[grade] = sum(1 for r in rows if r.get("grade") == grade)

    yoy = revenue_yoy_map(targets[:FLASH_DAILY_MAX])
    ctx = {
        "date": date.today().isoformat(),
        "counts": counts,
        "rows": [
            {
                "grade": r.get("grade"), "name": names.get(r["code"], r["code"]),
                "score": r.get("score_flash"), "pri": r.get("pri"),
                "revenue_yoy": yoy.get(r["code"]),
                "has_consensus": r.get("has_consensus"),
                "base_effect_warning": r.get("base_effect_warning"),
            }
            for r in targets[:FLASH_DAILY_MAX]
        ],
        "url": optional_env("DASHBOARD_BASE_URL", "https://heimdallr-call.vercel.app"),
    }
    text = daily_digest(ctx)
    print(text)

    if not send:
        print("\n(--send 미지정 — 발송하지 않았다)")
        return 0

    client = TelegramClient()
    ok = send_once(
        client, code=None, fiscal_year=None, fiscal_quarter=None,
        kind=KIND_DAILY, text=text, payload=counts,
    )
    print(f"\n{'✓ 발송' if ok else '✗ 발송 안 됨(중복이거나 실패)'}")
    return 0


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="일괄 발송")
    parser.add_argument("--flash", action="store_true", help="★/○ 즉시 알림")
    parser.add_argument("--digest", action="store_true", help="일일 요약")
    parser.add_argument("--send", action="store_true", help="실제 발송")
    parser.add_argument("--limit", type=int, default=FLASH_DAILY_MAX,
                        help="한 실행에서 보낼 즉시 알림 상한")
    args = parser.parse_args()

    line = "═" * 72
    print(line)
    if args.digest:
        result = run_digest(args.send)
    else:
        result = run_flash(args.send, args.limit)
    print(line)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
