# PRD Ref: §7 (LLM 해석) · ADR 3, ADR 4 · traps.md T18
"""LLM 분석 **배치** — 투자 매력도 상위 종목을 미리 분석해 둔다.

왜 배치인가 (실측 근거):
  기존에는 텔레그램 질의가 올 때만 분석했다. 그래서 호출이 하나씩 띄엄띄엄 일어나
  **프롬프트 캐시를 매번 놓쳤다**(실측 4건 중 3건이 캐시 미스).
  시스템 프롬프트 3,242토큰은 종목마다 동일한데, 캐시 TTL이 5분이라
  **연속 호출**해야 히트한다.

    캐시 미스 1건  $0.0346
    캐시 히트 1건  $0.0271   ← 22% 절감
    실측 평균      $0.0333   (대부분 미스였다)

선정 기준 (`--top N`):
  게이트 통과 + 등급이 있는 종목을 **투자 매력도 순**으로 정렬한다.
  매력도 = 스코어(펀더멘털 강도)와 낮은 반영도(아직 안 오름)를 함께 본다 —
  둘을 합산하지 않는다(ADR 5). 정렬 키만 만든다.

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
from src.analysis.run import build_input
from src.config.constants import SCORE_HIGH
from src.db.supabase_client import select_all
from src.utils.console import enable_utf8_stdout
from src.utils.cost_guard import check_budget

#: 기본 분석 종목 수. 실측 비용 기준으로 월 실링 $8의 약 34%(캐시 히트 시 $2.71).
#: 분기 시즌이 한 달에 몰리므로 **분기 비용 ≈ 그 달 비용**이다.
DEFAULT_TOP = 100

#: 연속 호출 간격(초). 캐시 TTL 5분 안에 들어가려면 붙여서 불러야 한다.
#: 0으로 두면 레이트리밋에 걸리고, 크게 두면 캐시가 식는다.
CALL_GAP_SEC = 1.0


def attractiveness(screen: dict) -> float | None:
    """투자 매력도 정렬 키. **점수가 아니다** — 순서를 정하는 용도다.

    ★ 스코어와 반영도를 **합산하지 않는다**(ADR 5). 대신 정렬용으로만
      "스코어가 높고 반영도가 낮은" 순서를 만든다. 화면에는 둘을 따로 보여준다.
    ★ 둘 중 하나라도 없으면 None — 정렬에서 뒤로 보낸다. 0으로 채우면
      측정 못 한 종목이 '매력 없음'으로 바뀐다.
    """
    score = screen.get("score_flash")
    pri = screen.get("pri")
    if score is None or pri is None:
        return None
    return float(score) - float(pri) * 0.5


def targets(top: int, *, min_score: float = SCORE_HIGH) -> list[dict]:
    """분석 대상. 게이트 통과 + 등급 있음 + 스코어 하한, 매력도 순 상위 N.

    ★ 종목별 **최신 분기 1행**으로 접는다(T40). 접지 않으면 같은 종목이
      과거 분기로 여러 번 뽑혀 예산을 태운다.
    """
    rows = select_all(
        "screen_results",
        "code,fiscal_year,fiscal_quarter,gate_passed,grade,score_flash,pri",
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
        if r.get("gate_passed") is True
        and r.get("grade") is not None
        and r.get("score_flash") is not None
        and float(r["score_flash"]) >= min_score
    ]
    # 매력도가 None인 종목은 뒤로.
    picked.sort(key=lambda r: (attractiveness(r) is None, -(attractiveness(r) or 0)))
    return picked[:top]


def already_analyzed() -> set[tuple[str, int, int]]:
    return {
        (a["code"], a["fiscal_year"], a["fiscal_quarter"])
        for a in select_all("analyses", "code,fiscal_year,fiscal_quarter")
    }


def run(top: int, *, send: bool, min_score: float) -> int:
    names = {u["code"]: u["name"] for u in select_all("krx_universe", "code,name")}
    picked = targets(top, min_score=min_score)
    done = already_analyzed()

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

    if not pending:
        print("\n새로 분석할 종목이 없다.")
        return 0

    print(f"\n{'#':>4} {'종목':<14}{'분기':<9}{'스코어':>7}{'반영도':>7}  결과")
    for i, r in enumerate(picked[:12], 1):
        mark = "대기" if (r["code"], r["fiscal_year"], r["fiscal_quarter"]) not in done else "완료"
        print(f"{i:>4} {names.get(r['code'], r['code'])[:12]:<14}"
              f"{r['fiscal_year']}.{r['fiscal_quarter']}Q  "
              f"{float(r['score_flash']):>6.1f}{float(r['pri'] or 0):>7.1f}  {mark}")
    if len(picked) > 12:
        print(f"     … 외 {len(picked) - 12}종목")

    if not send:
        print(f"\n(--send 미지정 — API를 호출하지 않았다)")
        return 0

    ok = failed = skipped = 0
    stopped_at: str | None = None
    started = time.monotonic()

    for i, r in enumerate(pending, 1):
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
    print(f"\n✓ 분석 {ok}건 · 실패 {failed}건 · 예산소진 건너뜀 {skipped}건 · {elapsed:.0f}초")
    print(f"  누적 월 비용 ${final.month_spent_usd:.4f}/${final.month_ceiling_usd}")
    if stopped_at:
        print(f"  ⚠ 예산 상한에 걸려 중단했다: {stopped_at}")
        print(f"    남은 {skipped}종목은 다음 실행에서 이어서 분석한다(이미 된 건 재호출하지 않는다).")
    return 0


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="LLM 배치 분석")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP,
                        help=f"매력도 상위 N종목 (기본 {DEFAULT_TOP})")
    parser.add_argument("--min-score", type=float, default=SCORE_HIGH,
                        help=f"스코어 하한 (기본 {SCORE_HIGH})")
    parser.add_argument("--send", action="store_true", help="실제 API 호출")
    args = parser.parse_args()
    return run(args.top, send=args.send, min_score=args.min_score)


if __name__ == "__main__":
    raise SystemExit(main())
