# PRD Ref: §7 (LLM 해석) · ADR 3, ADR 4 · traps.md T18
"""LLM 분석 **배치** — 투자 매력도 상위 종목을 미리 분석해 둔다.

왜 배치인가 (실측 근거):
  기존에는 텔레그램 질의가 올 때만 분석했다. 그래서 호출이 하나씩 띄엄띄엄 일어나
  **프롬프트 캐시를 매번 놓쳤다**(실측 4건 중 3건이 캐시 미스).
  시스템 프롬프트 3,242토큰은 종목마다 동일한데, 캐시 TTL이 5분이라
  **연속 호출**해야 히트한다.

    캐시 미스 1건  $0.0363
    캐시 히트 1건  $0.0315   ← 13% 절감뿐이다(비용의 대부분이 출력 2,400~2,800토큰)
    (2026-08-17 cost_log 25건 실측)

선정 기준 (2026-08-17 확정 · A′+B):
  **게이트를 통과한 종목 전부**가 대상이다(B안 · 실측 238종목 · 분기 $7.51).
  그리고 **발송 등급(★/○)은 스코어 하한과 무관하게 항상 포함한다**(A′안) —
  등급은 스코어와 반영도의 교차 판정이라 하한을 걸면 "○인데 스코어 74.9"가 빠진다.
  실측: 발송 대상 70종목 중 22종목이 해석 없이 알림만 나가고 있었다.

  정렬은 **투자 매력도 순**이다. 시간·비용이 모자라 중간에 끊겨도
  중요한 종목이 먼저 처리되게 한다. 매력도는 스코어와 낮은 반영도를 함께 보되
  **합산하지 않는다**(ADR 5) — 정렬 키일 뿐이다.

★ 비용은 코드가 막는다. `analyze()`가 `check_budget()`으로 월 실링과 일 상한을
  확인하고, 걸리면 `BudgetExceeded`를 올린다. 여기서는 그걸 잡아 **남은 종목을
  건너뛰고 몇 건이 남았는지 밝힌다** — 조용히 멈추면 다음 사람이 다 됐다고 착각한다.

★ **이미 분석이 있으면 호출하지 않는다.** 재실행해도 비용이 늘지 않는다.
"""

from __future__ import annotations

import argparse
import time

from src.analysis.analyze import (
    AnalysisError,
    BudgetExceeded,
    analyze,
    save,
    validate_payload,
)
from src.analysis.eligibility import is_growth_acceleration
from src.analysis.run import FUND_COLUMNS, build_input
from src.analysis.freshness import facts_hash, render_excerpt, select_excerpt
from src.finance.narrative_changes import select_quarter_window
from src.config.constants import NOTIFY_GRADES, SCORE_HIGH
from src.db.supabase_client import select_all
from src.screener.score import active_score
from src.utils.console import enable_utf8_stdout
from src.utils.cost_guard import check_budget
from src.utils.env import optional_env

#: 기본 분석 종목 수. **게이트 통과 전부를 담을 만큼 크게** 둔다(B안, 2026-08-17).
#: 실측: 게이트 통과 238종목 · 분기 비용 $7.51 (캐시히트 $0.0315/건).
#: 분기 시즌이 한 달에 몰리므로 **분기 비용 ≈ 그 달 비용**이다 → 실링 $12.
DEFAULT_TOP = 2000

#: 스코어 하한. **발송 등급(★/○)은 이 하한과 무관하게 항상 포함된다**(A′안).
#: 0이면 게이트 통과 전부가 대상이다.
DEFAULT_MIN_SCORE = 0.0

#: 연속 호출 간격(초). 캐시 TTL 5분 안에 들어가려면 붙여서 불러야 한다.
#: ★ 실측 호출 자체가 36~56초 걸린다(출력 2,400~2,800토큰) — 이 간격은 사실상 무의미하다.
#:   레이트리밋 여유를 위해 남겨 둔다.
CALL_GAP_SEC = 1.0

#: 한 번 실행에서 쓸 최대 시간(초). **워크플로 timeout보다 작아야 한다.**
#: ★ 238종목 × 36~56초 = 2.4~3.7시간이라 한 번에 다 못 돈다.
#:   시간이 되면 **깨끗하게 멈추고 남은 건수를 밝힌다** — 강제 종료되면
#:   진행 상황이 로그에 안 남아 다음 사람이 어디까지 됐는지 모른다.
#:   배치는 멱등이라(이미 분석된 건 건너뜀) 여러 번 돌면 누적된다.
DEFAULT_MAX_SECONDS = 600


def attractiveness(screen: dict) -> float | None:
    """투자 매력도 정렬 키. **점수가 아니다** — 순서를 정하는 용도다.

    ★ 스코어와 반영도를 **합산하지 않는다**(ADR 5). 대신 정렬용으로만
      "스코어가 높고 반영도가 낮은" 순서를 만든다. 화면에는 둘을 따로 보여준다.
    ★ 둘 중 하나라도 없으면 None — 정렬에서 뒤로 보낸다. 0으로 채우면
      측정 못 한 종목이 '매력 없음'으로 바뀐다.
    """
    score = active_score(screen)
    pri = screen.get("pri")
    if score is None or pri is None:
        return None
    return float(score) - float(pri) * 0.5


def targets(top: int, *, min_score: float = DEFAULT_MIN_SCORE) -> list[dict]:
    """분석 대상. 게이트 통과 + 등급 있음, 매력도 순 상위 N.

    ★★ **발송 등급(★/○)은 스코어 하한과 무관하게 반드시 포함된다** (A′안).
       예전에는 `score >= 75`만 걸었는데, 등급은 스코어와 반영도의 **교차** 판정이라
       "○인데 스코어 74.9"인 종목이 사이로 빠졌다. 실측(2026-08-17):
       발송 대상 70종목 중 **22종목이 해석 없이 알림만 나갔다** —
       그중 롯데케미칼(반영도 2.7)·GKL(1.8)처럼 **반영도가 매우 낮은 종목**이 많았다.
       이 시스템이 찾는 바로 그 구간이 빠지고 있었다.
       두 기준(발송=등급 / 분석=스코어)이 갈라져 있던 것이 원인이다.

    ★ 종목별 **최신 분기 1행**으로 접는다(T40). 접지 않으면 같은 종목이
      과거 분기로 여러 번 뽑혀 예산을 태운다.
    """
    rows = select_all(
        "screen_results",
        "code,fiscal_year,fiscal_quarter,gate_passed,turnaround,grade,score_flash,score_final,pri",
    )
    latest: dict[str, dict] = {}
    for r in rows:
        key = r["code"]
        index = r["fiscal_year"] * 4 + r["fiscal_quarter"]
        prev = latest.get(key)
        if prev is None or index > prev["fiscal_year"] * 4 + prev["fiscal_quarter"]:
            latest[key] = r

    picked = [
        r for r in latest.values()
        if is_growth_acceleration(r)
        and r.get("grade") is not None
        and (
            # ★ 발송 대상은 하한을 적용하지 않는다 — 알림이 나가는 종목에
            #   해석이 없으면 안 된다.
            r["grade"] in NOTIFY_GRADES
            or (active_score(r) is not None and active_score(r) >= min_score)
        )
    ]
    # 매력도가 None인 종목은 뒤로.
    picked.sort(key=lambda r: (attractiveness(r) is None, -(attractiveness(r) or 0)))
    return picked[:top]


def write_job_summary(lines: list[str]) -> bool:
    """GitHub Actions 잡 요약에 진행 상황을 쓴다. 로컬에서는 조용히 건너뛴다.

    ★ 배치는 **DB에만 쓰므로 커밋할 파일이 없다.** 그래서 진행 상황이 남는 곳이
      워크플로 로그뿐인데, 로그는 90일 뒤 사라지고 찾아 들어가야 보인다.
      잡 요약은 Actions 화면 첫 페이지에 표로 남는다.
    """
    # 환경변수는 반드시 optional_env로 — 값에 개행이 섞여도 벗겨준다.
    path = optional_env("GITHUB_STEP_SUMMARY")
    if not path:
        return False
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        return True
    except OSError:
        # 요약을 못 써도 분석은 이미 끝났다 — 여기서 죽으면 안 된다.
        return False


def notify_progress(text: str) -> bool:
    """텔레그램으로 진행 통지. **매번 보내지 않는다** — 호출부가 조건을 정한다.

    ★ 실패해도 배치를 세우지 않는다. 통지는 부가 기능이고 분석은 이미 저장됐다.
    ★ 토큰이 없으면(로컬) 조용히 건너뛴다.
    """
    try:
        from src.notify.telegram import PREFIX, TelegramClient

        TelegramClient().send_message(f"{PREFIX}{text}")
        return True
    except Exception as exc:
        print(f"  (텔레그램 통지 실패 — 무시한다: {type(exc).__name__}: {exc})")
        return False


def needs_final_refresh(
    payload: object,
    current_is_estimate: bool | None,
    *,
    analysis_created_at: str | None = None,
    final_updated_at: str | None = None,
    preliminary_delta: object = None,
) -> bool:
    """잠정 분석 뒤 같은 분기의 DART 확정치가 들어온 경우에만 재호출한다."""
    if current_is_estimate is not False:
        return False
    node = payload if isinstance(payload, dict) else {}
    meta = node.get("_heimdallr") if isinstance(node, dict) else None
    stage = meta.get("analysis_stage") if isinstance(meta, dict) else None
    if stage == "preliminary":
        return True
    if stage == "final":
        return False
    # 메타 도입 전 분석은 `delta_from_preliminary`가 실제로 남았고 확정 재무가
    # 분석 뒤 갱신된 경우만 잠정 분석으로 판정한다. 단순히 메타가 없다는 이유로
    # 과거 분석 전체를 유료 재호출하지 않는다.
    return bool(
        preliminary_delta
        and analysis_created_at
        and final_updated_at
        and final_updated_at > analysis_created_at
    )


def already_analyzed(
    before: str | None = None,
    *,
    refresh_finalized: bool = False,
) -> set[tuple[str, int, int]]:
    """이미 분석된 (종목, 분기).

    ★ `before`(ISO 날짜)를 주면 **그 시점 이후에 분석된 것만** '완료'로 친다.
      그보다 오래된 분석은 대상에 다시 넣는다 — 프롬프트를 고쳤을 때
      옛 결과를 갈아엎기 위한 장치다.
    ★ `created_at`이 없는 행은 **오래된 것으로 본다**(안전한 쪽). 새 프롬프트로
      다시 도는 것은 비용이 들 뿐 틀린 결과를 만들지 않는다.
    """
    rows = select_all("analyses", "code,fiscal_year,fiscal_quarter,created_at,payload")
    final_state: dict[tuple[str, int, int], dict] = {}
    funds_by_code: dict[str, list[dict]] = {}
    excerpts_by_code: dict[str, list[dict]] = {}
    if refresh_finalized:
        for f in select_all(
            "quarterly_fundamentals",
            FUND_COLUMNS + ",updated_at",
        ):
            final_state[(f["code"], f["fiscal_year"], f["fiscal_quarter"])] = f
            funds_by_code.setdefault(f["code"], []).append(f)
        for ex in select_all(
            "disclosure_excerpts", "code,rcept_no,fiscal_year,fiscal_quarter,sections"
        ):
            excerpts_by_code.setdefault(ex["code"], []).append(ex)
    out = set()
    for a in rows:
        if before:
            created = (a.get("created_at") or "")[:10]
            if not created or created < before:
                continue  # 낡았다 — 다시 분석 대상
        key = (a["code"], a["fiscal_year"], a["fiscal_quarter"])
        if refresh_finalized:
            final = final_state.get(key, {})
            if not final:
                out.add(key)
                continue
            payload = a.get("payload")
            meta = payload.get("_heimdallr") if isinstance(payload, dict) else None
            meta = meta if isinstance(meta, dict) else {}
            quarters = select_quarter_window(funds_by_code.get(key[0], []), key[1], key[2], limit=8)
            ex = select_excerpt(excerpts_by_code.get(key[0], []), key[1], key[2])
            excerpt = render_excerpt(ex, key[1], key[2]) if ex else None
            if meta.get("facts_hash") and quarters:
                if meta["facts_hash"] != facts_hash(quarters, excerpt):
                    continue
            elif a.get("created_at"):
                # 레거시는 확인 가능한 신규 근거만으로 갱신한다(T132).
                created = a["created_at"]
                receipt_day = (ex or {}).get("rcept_no", "")[:8]
                if (final.get("updated_at") or "") > created or receipt_day > created[:10].replace("-", ""):
                    continue
            if needs_final_refresh(
                a.get("payload"),
                final.get("is_estimate"),
                analysis_created_at=a.get("created_at"),
                final_updated_at=final.get("updated_at"),
                preliminary_delta=final.get("delta_from_preliminary"),
            ):
                continue
        out.add(key)
    return out


def run(
    top: int,
    *,
    send: bool,
    min_score: float,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    refresh_before: str | None = None,
    refresh_finalized: bool = False,
) -> int:
    names = {u["code"]: u["name"] for u in select_all("krx_universe", "code,name")}
    picked = targets(top, min_score=min_score)
    done = already_analyzed(refresh_before, refresh_finalized=refresh_finalized)

    pending = [
        r for r in picked
        if (r["code"], r["fiscal_year"], r["fiscal_quarter"]) not in done
    ]

    line = "═" * 72
    print(line)
    print(f"LLM 배치 분석 — 대상 {len(picked)}종목 (스코어 {min_score:.0f}+ · 매력도 순)")
    print(line)

    status = check_budget()
    print(f"\n예산: 월 ${status.month_spent_usd:.2f}/${status.month_ceiling_usd} · "
          f"오늘 {status.today_count}/{status.daily_limit} · "
          f"{'호출 가능' if status.allowed else status.reason}")
    print(f"이미 분석됨 {len(picked) - len(pending)}종목 · 호출 대상 {len(pending)}종목")
    if refresh_before:
        # ★ 재분석은 **돈이 새로 나간다.** 몇 건이 왜 대상이 됐는지 반드시 밝힌다.
        print(f"  ↻ {refresh_before} 이전 분석은 낡은 것으로 보고 다시 돌린다 "
              f"(재분석분 포함 {len(pending)}건 · 건당 약 $0.05)")

    if not pending:
        print("\n새로 분석할 종목이 없다.")
        # ★ 요약은 남기되 **텔레그램은 보내지 않는다.** 따라잡기가 끝난 뒤에는
        #   매일 밤 이 경로로 들어오므로, 보내면 같은 메시지가 매일 온다.
        #   완료 통지는 **마지막 종목을 실제로 채운 그 실행**에서 한 번만 나간다.
        write_job_summary([
            "## LLM 배치 분석",
            "",
            f"**{len(picked)}/{len(picked)}종목 (100%) — 따라잡기 완료.** 새로 호출할 대상이 없다.",
            "",
            f"누적 비용 ${status.month_spent_usd:.4f} / ${status.month_ceiling_usd}",
        ])
        return 0

    print(f"\n{'#':>4} {'종목':<14}{'분기':<9}{'스코어':>7}{'반영도':>7}  결과")
    for i, r in enumerate(picked[:12], 1):
        mark = "대기" if (r["code"], r["fiscal_year"], r["fiscal_quarter"]) not in done else "완료"
        print(f"{i:>4} {names.get(r['code'], r['code'])[:12]:<14}"
              f"{r['fiscal_year']}.{r['fiscal_quarter']}Q  "
              f"{float(active_score(r) or 0):>6.1f}{float(r['pri'] or 0):>7.1f}  {mark}")
    if len(picked) > 12:
        print(f"     … 외 {len(picked) - 12}종목")

    if not send:
        print(f"\n(--send 미지정 — API를 호출하지 않았다)")
        return 0

    ok = failed = skipped = 0
    stopped_at: str | None = None
    timed_out = False
    started = time.monotonic()
    print(f"\n시간 예산 {max_seconds:.0f}초 · 실측 호출당 36~56초 → "
          f"이번 실행에서 약 {max(1, int(max_seconds / 46))}건 예상")

    for i, r in enumerate(pending, 1):
        # ★ 시간이 되면 **깨끗하게 멈춘다.** 워크플로가 강제 종료하면 진행 상황이
        #   로그에 안 남아 다음 사람이 어디까지 됐는지 모른다.
        #   배치는 멱등이라(이미 분석된 건 건너뜀) 여러 번 돌면 누적된다.
        if time.monotonic() - started >= max_seconds:
            timed_out = True
            skipped = len(pending) - i + 1
            break

        code, year, quarter = r["code"], r["fiscal_year"], r["fiscal_quarter"]
        label = f"{names.get(code, code)}({code}) {year}.{quarter}Q"
        try:
            data = build_input(code, year=year, quarter=quarter)
            result = analyze(data, env="prod")
        except BudgetExceeded as exc:
            # ★ 예산 소진은 실패가 아니다. 남은 건수를 반드시 밝힌다.
            stopped_at = str(exc)
            skipped = len(pending) - i + 1
            break
        except AnalysisError as exc:
            failed += 1
            print(f"  ✗ {label} — {exc}")
            continue
        except Exception as exc:  # 개별 종목 실패가 배치를 세우지 않는다
            failed += 1
            print(f"  ✗ {label} — {type(exc).__name__}: {exc}")
            continue

        problems = validate_payload(result.payload)
        if problems:
            # 스키마는 통과했지만 내용이 빈 경우. 저장하되 화면에 밝힌다.
            print(f"  ⚠ {label} — 필드 미흡: {', '.join(problems[:3])}")
        save(result)
        ok += 1
        cached = result.cache_read_tokens > 0
        print(f"  ✓ {label} ${result.cost_usd:.4f} "
              f"{'(캐시 히트)' if cached else '(캐시 미스)'}")
        time.sleep(CALL_GAP_SEC)

    elapsed = time.monotonic() - started
    final = check_budget()
    print(f"\n✓ 분석 {ok}건 · 실패 {failed}건 · 남김 {skipped}건 · {elapsed:.0f}초"
          f"{f' ({elapsed / ok:.0f}초/건)' if ok else ''}")
    print(f"  누적 월 비용 ${final.month_spent_usd:.4f}/${final.month_ceiling_usd}")
    if timed_out:
        print(f"  ⏱ 시간 예산({max_seconds:.0f}초)에 걸려 멈췄다 — **실패가 아니다.**")
        print(f"    남은 {skipped}종목은 다음 실행에서 이어서 한다(멱등: 된 건 재호출 안 함).")
    if stopped_at:
        # ★★ **일 상한과 월 실링을 구분해서 말한다.** 둘 다 "비용 상한"이지만
        #   해야 할 일이 정반대다 — 일 상한은 **내일이면 저절로 풀리고**,
        #   월 실링은 사람이 결정(상향/대기)해야 한다.
        #   실측(2026-08-21): 일 상한 80/80에 걸렸는데 "다음 달 또는 실링 상향 후에"라고
        #   찍었다. 그 달에 $8.57가 남아 있었고 다음 날 배치가 이어받을 상황이었는데도
        #   **실링을 또 올리거나 한 달을 기다리게 만드는 안내**였다.
        #   메시지가 틀리면 사람이 틀린 행동을 한다 — 조용히 틀리는 것보다 나쁠 수 있다.
        daily = "daily" in (stopped_at or "")
        print(f"  ⚠ {'일 상한' if daily else '월 실링'}에 걸려 중단했다: {stopped_at}")
        if daily:
            print(f"    남은 {skipped}종목은 **다음 배치(내일)가 이어서 한다** — "
                  f"실링은 아직 ${final.month_ceiling_usd - final.month_spent_usd:.2f} 남았다.")
        else:
            print(f"    남은 {skipped}종목은 다음 달 또는 실링 상향 후에 이어서 한다.")

    # ── 진행 리포트 ────────────────────────────────────────────────
    # ★ 배치는 DB에만 쓰므로 **커밋할 파일이 없다.** 진행 상황이 남는 곳을 따로 만든다.
    done_now = len(picked) - len(pending) + ok
    remaining = len(picked) - done_now
    progress = f"{done_now}/{len(picked)}종목 ({done_now / max(len(picked), 1) * 100:.0f}%)"

    write_job_summary([
        "## LLM 배치 분석",
        "",
        f"| 항목 | 값 |",
        f"|---|---|",
        f"| 진행 | **{progress}** |",
        f"| 이번 실행 | 분석 {ok} · 실패 {failed} · 남김 {skipped} |",
        f"| 소요 | {elapsed:.0f}초" + (f" ({elapsed / ok:.0f}초/건)" if ok else "") + " |",
        f"| 누적 비용 | ${final.month_spent_usd:.4f} / ${final.month_ceiling_usd} |",
        f"| 멈춘 이유 | "
        + (
            "시간 예산" if timed_out
            else "일 상한 (내일 이어서)" if stopped_at and "daily" in stopped_at
            else "월 실링 (상향 또는 다음 달)" if stopped_at
            else "대상 소진"
        )
        + " |",
        "",
        "배치는 멱등이라 다음 실행에서 이어서 한다(이미 분석된 건 재호출하지 않는다).",
    ])

    # ★ 텔레그램은 **매일 보내지 않는다.** 밤마다 같은 진행 메시지가 오면
    #   알림이 소음이 되고, 정작 중요한 종목 알림을 덮는다.
    #   보내는 경우: ① 전부 끝났다 ② 비용 상한에 걸렸다 ③ 실패가 많다.
    if ok and remaining == 0:
        notify_progress(
            f"🧠 <b>LLM 배치 완료</b>\n\n"
            f"성장 가속 {len(picked)}종목 해석을 전부 채웠다.\n"
            f"누적 비용 ${final.month_spent_usd:.2f}/${final.month_ceiling_usd}"
        )
    elif stopped_at and "daily" not in stopped_at:
        # ★★ **일 상한으로는 보내지 않는다.** 따라잡기 기간에는 일 상한이 **매일** 걸리므로
        #   보내면 밤마다 같은 💸 알림이 온다 — 바로 위에서 피하려던 그 소음이다.
        #   사람이 결정할 것이 있을 때만 알린다: 월 실링은 상향/대기를 골라야 하지만
        #   일 상한은 **내일이면 저절로 풀린다.**
        notify_progress(
            f"💸 <b>LLM 배치 — 월 실링 도달</b>\n\n"
            f"진행 {progress} · 남은 {remaining}종목\n"
            f"${final.month_spent_usd:.2f}/${final.month_ceiling_usd}에서 멈췄다.\n"
            f"다음 달을 기다리거나 실링을 올려야 이어진다."
        )
    elif failed >= 5:
        notify_progress(
            f"⚠️ <b>LLM 배치 — 실패 {failed}건</b>\n\n"
            f"진행 {progress}. 로그를 확인하라."
        )
    return 0


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="LLM 배치 분석")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP,
                        help=f"매력도 상위 N종목 (기본 {DEFAULT_TOP} = 성장 가속 전부)")
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE,
                        help=f"스코어 하한 (기본 {DEFAULT_MIN_SCORE:.0f}) — "
                             f"발송 등급 {'/'.join(NOTIFY_GRADES)}은 하한과 무관하게 항상 포함")
    parser.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS,
                        help=f"이번 실행 시간 예산(초, 기본 {DEFAULT_MAX_SECONDS:.0f}) — "
                             f"워크플로 timeout보다 작게 준다")
    parser.add_argument("--send", action="store_true", help="실제 API 호출")
    # ★ 프롬프트나 입력(공시 발췌)을 고친 뒤 옛 결과를 갈아엎기 위한 것이다.
    #   **비용이 새로 나가므로** 기본은 꺼져 있고 날짜를 명시해야 한다.
    parser.add_argument("--refresh-before", metavar="YYYY-MM-DD",
                        help="이 날짜 이전에 분석된 종목을 다시 분석한다(비용 발생)")
    parser.add_argument("--refresh-finalized", action="store_true",
                        help="잠정 분석 뒤 확정 재무가 들어온 같은 분기만 다시 분석한다")
    args = parser.parse_args()
    return run(args.top, send=args.send, min_score=args.min_score,
               max_seconds=args.max_seconds,
        refresh_before=args.refresh_before,
        refresh_finalized=args.refresh_finalized,
    )


if __name__ == "__main__":
    raise SystemExit(main())
