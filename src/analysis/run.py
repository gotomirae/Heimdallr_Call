# PRD Ref: §7, §13 (P7 검증)
"""P7 LLM 분석 실행.

    python -m src.analysis.run --dry-run          # 입력 조립 + 토큰 수 (호출 안 함)
    python -m src.analysis.run --code 005930 --call   # 실제 1회 호출 (승인 후)
    python -m src.analysis.run --code 005930 --call --twice  # 캐시 히트 확인
"""

from __future__ import annotations

import argparse
import json

from src.analysis.analyze import (
    AnalysisInput,
    analyze,
    build_user_message,
    count_input_tokens,
    save,
    validate_payload,
)
from src.config.constants import LLM_INPUT_TOKEN_BUDGET
from src.db.supabase_client import select_all
from src.finance.valuation import (
    forward_per_annual,
    trailing_4q_per,
    ttm_net_income,
)
from src.utils.console import enable_utf8_stdout
from src.utils.cost_guard import ENV_DEV, ENV_PROD, check_budget

FUND_COLUMNS = (
    # ★ `np`(순이익)가 없으면 최근 4분기 PER이 **전 종목 계산 불가**가 된다 —
    #   에러 없이 "계산 불가"만 뜨므로 데이터가 없는 것처럼 보인다(2026-08-23 실측).
    "code,fiscal_year,fiscal_quarter,revenue,op,np,revenue_yoy,op_yoy,opm,opm_yoy_delta,"
    "ttm_revenue,ttm_op,ttm_opm,op_status_label,is_estimate"
)


def build_input(code: str, *, year: int, quarter: int) -> AnalysisInput:
    uni = {u["code"]: u for u in select_all(
        "krx_universe", "code,name,board,industry,products,market_cap_krw,listed_at,sector_caveat"
    )}
    row = uni.get(code)
    if row is None:
        raise SystemExit(f"{code}: krx_universe에 없다")

    funds = [f for f in select_all("quarterly_fundamentals", FUND_COLUMNS) if f["code"] == code]
    funds.sort(key=lambda f: (f["fiscal_year"], f["fiscal_quarter"]))
    quarters = funds[-8:]

    screens = [
        s for s in select_all(
            "screen_results",
            "code,fiscal_year,fiscal_quarter,gate_passed,gate_detail,base_effect_warning,"
            "turnaround,score_flash,score_a,score_b,has_consensus,pri,pri_detail,grade",
        )
        if s["code"] == code and s["fiscal_year"] == year and s["fiscal_quarter"] == quarter
    ]
    screen = screens[0] if screens else {}

    consensus = None
    for c in select_all(
        "consensus_snapshots",
        "code,fiscal_year,fiscal_quarter,revenue_est,op_est,n_estimates",
    ):
        if c["code"] == code and c["fiscal_year"] == year and c["fiscal_quarter"] == quarter:
            if (c.get("n_estimates") or 0) >= 2:
                consensus = c
            break

    price_rows = [p for p in select_all(
        "price_snapshots",
        "code,snap_date,close,chg_pct,high_52w,low_52w,pos_52w,per,pbr,"
        "market_cap_krw,rel_ret_3m,per_pctile_3y"
    ) if p["code"] == code]
    price = max(price_rows, key=lambda p: p["snap_date"]) if price_rows else {}

    # ── 밸류에이션 재계산 ──────────────────────────────────────────
    # ★★ 후행 PER(`price_snapshots.per`)은 직전 사업연도 EPS 기준이라 가속 구간에서
    #   2~3배 과대평가된다 — 이 시스템이 겨냥하는 구간이 정확히 거기다.
    #   `src/finance/valuation.py`가 `dashboard/lib/valuation.ts`와 같은 규칙으로 다시 잰다.
    # ★ 선행 PER은 **연간 컨센서스**(`fiscal_quarter = 0`)로만 만든다.
    #   분기 컨센은 한 분기뿐이라 '향후 4분기'를 만들 수 없다.
    annual_consensus = None
    for c in select_all(
        "consensus_snapshots", "code,fiscal_year,fiscal_quarter,np_est,n_estimates"
    ):
        if c["code"] == code and c.get("fiscal_quarter") == 0 and c["fiscal_year"] >= year:
            if annual_consensus is None or c["fiscal_year"] < annual_consensus["fiscal_year"]:
                annual_consensus = c

    cap = price.get("market_cap_krw") or row.get("market_cap_krw")
    ttm_np = ttm_net_income(funds, year, quarter)
    fwd_per, fwd_basis = forward_per_annual(
        (annual_consensus or {}).get("np_est"),
        (annual_consensus or {}).get("fiscal_year"),
        funds,
        cap,
    )
    valuation = {
        "market_cap_krw": cap,
        "ttm_np": ttm_np,
        "per_trailing_4q": trailing_4q_per(cap, ttm_np),
        "per_trailing_reason": (
            None if ttm_np and ttm_np > 0
            else ("4개 분기 순이익이 다 모이지 않았다" if ttm_np is None
                  else "누적 순이익이 0 이하다")
        ),
        "per_forward": fwd_per,
        "per_forward_basis": fwd_basis,
        "pbr": price.get("pbr"),
    }

    latest = quarters[-1] if quarters else {}
    return AnalysisInput(
        code=code,
        name=row["name"],
        board=row["board"],
        industry=row.get("industry"),
        products=row.get("products"),
        market_cap_krw=row.get("market_cap_krw"),
        listed_at=row.get("listed_at"),
        fiscal_year=year,
        fiscal_quarter=quarter,
        is_estimate=bool(latest.get("is_estimate")),
        quarters=quarters,
        gate={
            "passed": screen.get("gate_passed"),
            "base_effect_warning": screen.get("base_effect_warning"),
            "turnaround": screen.get("turnaround"),
            "detail": (screen.get("gate_detail") or {}).get("detail"),
            "base_effect_checks": (screen.get("gate_detail") or {}).get("base_effect_checks"),
            "sector_caveat": row.get("sector_caveat"),
        },
        score={
            "score_flash": screen.get("score_flash"),
            "score_a": screen.get("score_a"),
            "score_b": screen.get("score_b"),
            "has_consensus": screen.get("has_consensus"),
            "grade": screen.get("grade"),
            "note": "C축(컨센서스)·D축(회계품질)은 미측정이라 분모에서 제외 후 정규화됨",
        },
        consensus=consensus,
        price=price,
        valuation=valuation,
        pri=screen.get("pri_detail") or {"pri": screen.get("pri")},
        excerpt=None,
        peers=[],
    )


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="P7 LLM 분석")
    parser.add_argument("--code", default="005930")
    parser.add_argument("--quarter", default="2026.1")
    parser.add_argument("--dry-run", action="store_true", help="토큰 수만 보고 호출하지 않는다")
    parser.add_argument("--call", action="store_true", help="실제 API 호출")
    parser.add_argument("--twice", action="store_true", help="두 번 호출해 캐시 히트 확인")
    parser.add_argument("--env", default=ENV_PROD, choices=[ENV_PROD, ENV_DEV])
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    year, quarter = (int(x) for x in args.quarter.split("."))
    data = build_input(args.code, year=year, quarter=quarter)

    line = "═" * 72
    print(line)
    print(f"P7 LLM 분석 — {data.name}({data.code}) {year}.{quarter}Q")
    print(line)

    message = build_user_message(data)
    print(f"\n[1] 입력 조립 · 유저 메시지 {len(message):,}자")
    print(f"    분기 표 {len(data.quarters)}행 · 컨센서스 "
          f"{'있음' if data.consensus else '없음(커버리지 공백)'} · "
          f"시세 {'있음' if data.price else '없음'}")

    tokens = count_input_tokens(data)
    print(f"\n[2] 입력 토큰 {tokens:,} / 예산 {LLM_INPUT_TOKEN_BUDGET:,} "
          f"{'✓' if tokens <= LLM_INPUT_TOKEN_BUDGET else '✗ 초과'}")

    status = check_budget(env=args.env)
    print(f"\n[3] 예산: 월 ${status.month_spent_usd:.4f}/${status.month_ceiling_usd} · "
          f"오늘 {status.today_count}/{status.daily_limit} · "
          f"{'호출 가능' if status.allowed else '차단: ' + str(status.reason)}")

    if not args.call:
        print(f"\n(--call 미지정 — API를 호출하지 않았다)")
        print("\n--- 유저 메시지 미리보기 (앞 1,200자) ---")
        print(message[:1200])
        print(line)
        return 0

    runs = 2 if args.twice else 1
    for i in range(1, runs + 1):
        print(f"\n[4-{i}] 실제 호출...")
        result = analyze(data, env=args.env)
        print(f"    비용 ${result.cost_usd:.4f} "
              f"{'✓ $0.05 이하' if result.cost_usd <= 0.05 else '✗ $0.05 초과'}")
        print(f"    토큰: 입력 {result.input_tokens:,} · "
              f"캐시쓰기 {result.cache_write_tokens:,} · "
              f"캐시읽기 {result.cache_read_tokens:,} · 출력 {result.output_tokens:,}")
        if i == 2:
            print(f"    ★ 캐시 히트 {'✓ 확인' if result.cache_read_tokens > 0 else '✗ 안 잡힘'}")

        problems = validate_payload(result.payload)
        print(f"    필드 검증: {'✓ 전부 채워짐' if not problems else '✗ ' + ', '.join(problems)}")

        payload = result.payload
        print(f"\n    한 줄 아이디어: {payload.get('one_line_thesis')}")
        sc = payload.get("scenarios") or {}
        probs = {k: (sc.get(k) or {}).get("probability") for k in ("bull", "base", "bear")}
        total = sum(v for v in probs.values() if v is not None)
        print(f"    시나리오 확률: {probs} 합={total:.2f}")
        ag = payload.get("acceleration_quality") or {}
        print(f"    가속의 진위: is_genuine={ag.get('is_genuine')} · "
              f"지속 전망 {ag.get('sustainability_quarters')}분기")
        tg = payload.get("triggers") or {}
        print(f"    트리거: 3개월 {len(tg.get('within_3m') or [])}건 · "
              f"6개월 {len(tg.get('within_6m') or [])}건")
        pp = payload.get("price_position") or {}
        print(f"    주가 위치: {pp.get('verdict')} · 미반영 {len(pp.get('not_priced_in') or [])}건")

        if args.save:
            save(result)
            print("    ✓ analyses 저장")

    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
