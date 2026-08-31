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
from src.db.supabase_client import (
    PostgrestReadBudget,
    ReadBudgetExceeded,
    select_all,
)
from src.finance.narrative_changes import select_quarter_window
from src.finance.valuation import (
    forward_per_annual,
    trailing_4q_per,
    ttm_net_income,
)
from src.screener.score import active_score
from src.utils.console import enable_utf8_stdout
from src.utils.cost_guard import ENV_DEV, ENV_PROD, check_budget

FUND_COLUMNS = (
    # ★ `np`(순이익)가 없으면 최근 4분기 PER이 **전 종목 계산 불가**가 된다 —
    #   에러 없이 "계산 불가"만 뜨므로 데이터가 없는 것처럼 보인다(2026-08-23 실측).
    "code,fiscal_year,fiscal_quarter,revenue,op,np,revenue_yoy,op_yoy,opm,opm_yoy_delta,"
    "ttm_revenue,ttm_op,ttm_opm,op_status_label,is_estimate,delta_from_preliminary"
)


def _latest_snapshot(rows: list[dict]) -> dict | None:
    """시점 이력에서 최신 한 행을 고른다. PostgREST 반환 순서는 계약이 아니다."""
    if not rows:
        return None
    return max(rows, key=lambda row: str(row.get("snapshot_at") or ""))


def load_excerpt(
    code: str,
    year: int,
    quarter: int,
    *,
    allow_fetch: bool = False,
    read_budget: PostgrestReadBudget | None = None,
) -> str | None:
    """저장된 정기보고서 발췌. 없으면 (허용 시) 그 자리에서 받는다.

    ★ 실패해도 **None을 주고 넘어간다.** 발췌가 없다고 분석을 막지 않는다 —
      숫자만으로도 실적 해석은 되고, 못 쓴 부분은 모델이 밝히게 돼 있다.
    ★ 테이블이 아직 없을 수 있다(마이그레이션 전). 그때도 죽지 않는다.
    """
    rows: list[dict] = []
    try:
        rows = [
            r for r in select_all(
                "disclosure_excerpts",
                "rcept_no,code,fiscal_year,fiscal_quarter,sections,full_chars",
                filters={"code": code},
                read_budget=read_budget,
            )
        ]
    except ReadBudgetExceeded:
        raise
    except Exception:
        rows = []  # 테이블 미생성 등 — 조용히 넘어간다

    def render(row: dict) -> str | None:
        """★★ **어느 분기 원문인지 반드시 머리에 붙인다**(T99).

        분기가 넘어가면 그 분기 발췌가 아직 없어 직전 것으로 물러서는데,
        라벨이 없으면 모델은 그것을 **이번 분기 사실로 읽는다** — 지난 분기
        수주잔고를 이번 분기 트리거로 쓰는 식으로 에러 없이 틀린다.
        """
        sections = row.get("sections") or {}
        if not sections:
            return None
        row_year, row_quarter = row.get("fiscal_year"), row.get("fiscal_quarter")
        if row_year is None or row_quarter is None:
            head = "기준 분기 미상 — 이번 분기 것이 아닐 수 있다"
        elif (row_year, row_quarter) == (year, quarter):
            head = f"{row_year}년 {row_quarter}분기 정기보고서"
        else:
            head = (f"★ {row_year}년 {row_quarter}분기 정기보고서 "
                    f"— **{year}년 {quarter}분기 것이 아니다.** "
                    f"여기 적힌 사실을 이번 분기 사건으로 쓰지 마라.")
        body = "\n\n".join(f"### {k}\n{v}" for k, v in sections.items())
        return f"[출처: {head}]\n\n{body}"

    # 그 분기 것이 있으면 우선, 없으면 가장 최근 것으로 물러선다.
    same = [r for r in rows
            if r.get("fiscal_year") == year and r.get("fiscal_quarter") == quarter]
    if same:
        return render(same[0])
    if rows:
        # ★ 분기 칸이 비어 있으면 `(0, 0)`이라 **순서가 사실상 무작위**가 된다.
        #   접수번호(YYYYMMDD######)로 마지막을 갈라 항상 같은 답이 나오게 한다.
        newest = max(rows, key=lambda r: (r.get("fiscal_year") or 0,
                                          r.get("fiscal_quarter") or 0,
                                          r.get("rcept_no") or ""))
        return render(newest)

    if not allow_fetch:
        return None

    # ── 즉시 수집 (단건 분석 전용) ──
    from src.collectors.dart_disclosure import period_of
    from src.collectors.dart_excerpt import excerpt_for
    from src.collectors.excerpt_run import is_periodic

    candidates = [
        d for d in select_all(
            "earnings_disclosures", "rcept_no,code,report_nm,disclosed_at",
            filters={"code": code},
            read_budget=read_budget,
        )
        if is_periodic(d.get("report_nm"))
    ]
    if not candidates:
        return None
    newest_disc = max(candidates, key=lambda d: d.get("disclosed_at") or "")
    result = excerpt_for(newest_disc["rcept_no"])
    if result is None:
        return None
    # 즉시 수집분도 **그 공시의 기간을 붙여서** 넘긴다 — 저장분과 같은 규칙이다.
    fetched_year, fetched_quarter = period_of(newest_disc.get("report_nm"))
    return render({"sections": result.sections,
                   "fiscal_year": fetched_year,
                   "fiscal_quarter": fetched_quarter,
                   "rcept_no": newest_disc["rcept_no"]})


def build_input(
    code: str,
    *,
    year: int,
    quarter: int,
    allow_fetch: bool = False,
    read_budget: PostgrestReadBudget | None = None,
) -> AnalysisInput:
    uni = {u["code"]: u for u in select_all(
        "krx_universe", "code,name,board,industry,products,market_cap_krw,listed_at,sector_caveat",
        filters={"code": code},
        read_budget=read_budget,
    )}
    row = uni.get(code)
    if row is None:
        raise SystemExit(f"{code}: krx_universe에 없다")

    funds = select_all(
        "quarterly_fundamentals", FUND_COLUMNS, filters={"code": code},
        read_budget=read_budget,
    )
    funds.sort(key=lambda f: (f["fiscal_year"], f["fiscal_quarter"]))
    # ★ 요청 분기 뒤의 실적을 넣으면 과거 replay가 미래를 본다(T112).
    # `최신 8개`가 아니라 **요청 분기까지의 8개**여야 한다.
    quarters = select_quarter_window(funds, year, quarter, limit=8)

    screens = [
        s for s in select_all(
            "screen_results",
            "code,fiscal_year,fiscal_quarter,gate_passed,gate_detail,base_effect_warning,"
            "turnaround,score_flash,score_final,score_a,score_b,has_consensus,pri,pri_detail,grade",
            filters={"code": code, "fiscal_year": year, "fiscal_quarter": quarter},
            read_budget=read_budget,
        )
    ]
    screen = screens[0] if screens else {}

    consensus_rows = [
        c for c in select_all(
            "consensus_snapshots",
            "code,fiscal_year,fiscal_quarter,revenue_est,op_est,n_estimates,source,snapshot_at",
            filters={"code": code, "fiscal_year": year, "fiscal_quarter": quarter},
            read_budget=read_budget,
        )
        if (c.get("n_estimates") or 0) >= 2
    ]
    consensus = _latest_snapshot(consensus_rows)

    price_rows = [p for p in select_all(
        "price_snapshots",
        "code,snap_date,close,chg_pct,high_52w,low_52w,pos_52w,per,pbr,"
        "market_cap_krw,rel_ret_3m,per_pctile_3y",
        filters={"code": code},
        read_budget=read_budget,
    )]
    price = max(price_rows, key=lambda p: p["snap_date"]) if price_rows else {}

    # ── 밸류에이션 재계산 ──────────────────────────────────────────
    # ★★ 후행 PER(`price_snapshots.per`)은 직전 사업연도 EPS 기준이라 가속 구간에서
    #   2~3배 과대평가된다 — 이 시스템이 겨냥하는 구간이 정확히 거기다.
    #   `src/finance/valuation.py`가 `dashboard/lib/valuation.ts`와 같은 규칙으로 다시 잰다.
    # ★ 선행 PER은 **연간 컨센서스**(`fiscal_quarter = 0`)로만 만든다.
    #   분기 컨센은 한 분기뿐이라 '향후 4분기'를 만들 수 없다.
    annual_rows = [
        c for c in select_all(
            "consensus_snapshots",
            "code,fiscal_year,fiscal_quarter,np_est,per,fwd_per,source,snapshot_at",
            filters={"code": code, "fiscal_quarter": 0},
            read_budget=read_budget,
        )
        if c["fiscal_year"] >= year
    ]
    nearest_annual_year = min(
        (c["fiscal_year"] for c in annual_rows),
        default=None,
    )
    annual_consensus = _latest_snapshot([
        c for c in annual_rows if c["fiscal_year"] == nearest_annual_year
    ])

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
        "per_naver": (annual_consensus or {}).get("per"),
        "per_forward_naver": (annual_consensus or {}).get("fwd_per"),
        "per_naver_source": (annual_consensus or {}).get("source"),
        "pbr": price.get("pbr"),
    }

    # ── 공시 원문 발췌 ────────────────────────────────────────────
    # ★★ 여기가 비어 있으면 모델은 **숫자만 보고** 증설·신제품·수주를 써야 한다.
    #   그러면 지어내거나 침묵한다(T93 실측: 트리거 0건). 원문을 넣어야 답이 나온다.
    # ★ 원문 1건 받는 데 ~30초다. 배치(269종목)에서 즉시 수집하면 2시간이 더 붙으므로
    #   **미리 받아 둔 것을 읽는다**(`python -m src.collectors.excerpt_run --save`).
    #   단건 분석에서는 없으면 그 자리에서 받는다 — 30초는 감당할 만하다.
    excerpt = load_excerpt(
        code, year, quarter, allow_fetch=allow_fetch, read_budget=read_budget
    )

    # ── 분기말 주가 시계열 · 최근 공시 목록 (T101) ──────────────────
    # ★★ 둘 다 DB에 있는데 입력에 넣은 적이 없었다. 그 결과
    #   `price_position.price_history`는 **주가 궤적 없이** 쓰였고,
    #   트리거의 `expected_date`는 **실적 발표일을 모른 채** 잡혔다.
    quarter_price_rows = [
        p for p in select_all(
            "quarter_prices",
            "code,fiscal_year,fiscal_quarter,close,trade_date",
            filters={"code": code},
            read_budget=read_budget,
        )
    ]
    disclosure_rows = [
        d for d in select_all(
            "earnings_disclosures",
            "code,report_nm,disclosed_at,doc_type",
            filters={"code": code},
            read_budget=read_budget,
        )
    ]
    # 기준일 — 가진 데이터 중 가장 최근 날짜를 쓴다. 오늘 날짜를 쓰면
    # 시세가 어제 것인데 "오늘 기준"이라고 말하는 셈이 된다.
    as_of = max(
        [p.get("snap_date") or "" for p in price_rows]
        + [str(q.get("trade_date") or "") for q in quarter_price_rows]
        + [""]
    ) or None

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
        preliminary_delta=latest.get("delta_from_preliminary"),
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
            "score_flash": active_score(screen),
            "score_a": screen.get("score_a"),
            "score_b": screen.get("score_b"),
            "has_consensus": screen.get("has_consensus"),
            "grade": screen.get("grade"),
            "note": "C축(컨센서스)·D축(회계품질)은 미측정이라 분모에서 제외 후 정규화됨",
        },
        consensus=consensus,
        price=price,
        valuation=valuation,
        # ★ `pri_detail`이 있으면 예전 코드는 최종 `pri`를 통째로 버렸다(T107).
        # 분해값과 결정론적으로 계산된 최종값을 함께 주고, 모델에게 재계산시키지 않는다.
        pri={**(screen.get("pri_detail") or {}), "pri": screen.get("pri")},
        excerpt=excerpt,
        peers=[],
        quarter_prices=quarter_price_rows,
        disclosures=disclosure_rows,
        as_of=as_of,
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
    data = build_input(args.code, year=year, quarter=quarter, allow_fetch=True)

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
