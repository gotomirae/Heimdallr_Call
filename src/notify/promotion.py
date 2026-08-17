# PRD Ref: §8.5, §10 · ADR 5 · traps.md T40
"""🔄 승격 확인 — △(고스코어·선반영)가 조정을 거쳐 ○/★로 내려왔는가.

    python -m src.notify.promotion            # 대상만 출력
    python -m src.notify.promotion --send     # 실제 발송

★★ **이 알림이 ADR 5의 실질적 쓸모다.**
   스코어와 PRI를 한 숫자로 뭉갰다면 △는 그냥 "중간 점수"로 묻힌다.
   따로 두었기에 "펀더멘털은 그대로인데 가격만 내려온 종목"을 집어낼 수 있다.

★ 비교 기준은 **발표 시점 등급**(`outcome_tracking.grade_at_announce`)이다.
  직전 실행과 비교하면 실행 간격에 따라 결과가 달라진다 — 재현되지 않는다.

★ 스코어가 함께 떨어졌으면 승격이 아니다. 그건 그냥 나빠진 것이다.
"""

from __future__ import annotations

import argparse

from src.config.constants import DASHBOARD_URL_DEFAULT, NOTIFY_GRADES
from src.db.supabase_client import select_all
from src.notify.telegram import TelegramClient, TelegramError, send_once
from src.notify.templates import KIND_UPGRADE, upgrade_message
from src.utils.console import enable_utf8_stdout
from src.utils.env import optional_env

#: 승격 출발점. 여기서 ★/○로 내려온 것만 알린다.
FROM_GRADES = ("△",)

#: 스코어가 이보다 많이 떨어졌으면 승격이 아니라 악화다(%p).
MAX_SCORE_DROP = 5.0

SCREEN_COLUMNS = "code,fiscal_year,fiscal_quarter,grade,score_flash,pri"
OUTCOME_COLUMNS = (
    "code,fiscal_year,fiscal_quarter,grade_at_announce,"
    "score_at_announce,pri_at_announce"
)


def _qi(row: dict) -> int:
    return row["fiscal_year"] * 4 + (row["fiscal_quarter"] - 1)


def latest_screens() -> dict[tuple[str, int, int], dict]:
    """종목별 최신 1행 (T40). 전체를 그냥 읽으면 빈티지가 섞인다."""
    latest: dict[str, dict] = {}
    for row in select_all("screen_results", SCREEN_COLUMNS):
        prev = latest.get(row["code"])
        if prev is None or _qi(row) > _qi(prev):
            latest[row["code"]] = row
    return {
        (r["code"], r["fiscal_year"], r["fiscal_quarter"]): r for r in latest.values()
    }


def find_promotions() -> list[dict]:
    """발표 시점 △ → 현재 ★/○ 인 종목."""
    screens = latest_screens()
    names = {u["code"]: u["name"] for u in select_all("krx_universe", "code,name")}

    out: list[dict] = []
    for o in select_all("outcome_tracking", OUTCOME_COLUMNS):
        key = (o["code"], o["fiscal_year"], o["fiscal_quarter"])
        now = screens.get(key)
        if not now:
            continue  # 그 분기의 최신 결과가 아니다 — 이미 다음 분기로 넘어갔다

        was, is_now = o.get("grade_at_announce"), now.get("grade")
        if was not in FROM_GRADES or is_now not in NOTIFY_GRADES:
            continue

        # ★ 스코어가 함께 떨어졌으면 승격이 아니다. 가격만 내려와야 한다.
        before, after = o.get("score_at_announce"), now.get("score_flash")
        if before is not None and after is not None and (before - after) > MAX_SCORE_DROP:
            continue

        out.append({
            "code": o["code"],
            "fiscal_year": o["fiscal_year"],
            "fiscal_quarter": o["fiscal_quarter"],
            "name": names.get(o["code"], o["code"]),
            "from_grade": was,
            "to_grade": is_now,
            "score": after,
            "pri": now.get("pri"),
            "pri_before": o.get("pri_at_announce"),
        })
    out.sort(key=lambda r: -(r.get("score") or 0))
    return out


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="승격 확인")
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()

    line = "═" * 72
    print(line)
    rows = find_promotions()
    print(f"승격 대상 {len(rows)}종목 (△ → ★/○)")
    for r in rows:
        print(
            f"  {r['from_grade']} → {r['to_grade']}  {r['name']}({r['code']}) "
            f"{r['fiscal_year']}.{r['fiscal_quarter']}Q "
            f"스코어 {r['score']:.1f} · PRI {r['pri_before']} → {r['pri']}"
        )

    if not rows:
        print("  (조정으로 담을 구간에 들어온 종목이 없다)")
        print(line)
        return 0

    if not args.send:
        print("\n(--send 미지정 — 발송하지 않았다)")
        print(line)
        return 0

    text = upgrade_message({
        "rows": rows,
        "url": optional_env("DASHBOARD_BASE_URL", DASHBOARD_URL_DEFAULT),
    })
    client = TelegramClient()
    try:
        # 승격은 종목별이 아니라 묶음 알림이다 — 같은 분기에 한 번만.
        ok = send_once(
            client, code=None,
            fiscal_year=rows[0]["fiscal_year"], fiscal_quarter=rows[0]["fiscal_quarter"],
            kind=KIND_UPGRADE, text=text,
            payload={"count": len(rows)},
        )
        print(f"\n{'✓ 발송' if ok else '✗ 발송 안 됨(중복이거나 실패)'}")
    except TelegramError as exc:
        print(f"\n✗ 발송 실패: {exc}")
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
