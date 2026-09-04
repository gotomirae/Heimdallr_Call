# PRD Ref: §4 전체, §13 (P3) · traps.md T7
"""P3 스크리너 실행 — 순수 함수들을 실제 데이터에 적용한다.

    python -m src.screener.run                    # 최신 분기 리포트
    python -m src.screener.run --quarter 2026.1   # 분기 지정
    python -m src.screener.run --save             # screen_results 저장

★ 이 모듈만 I/O를 한다. gate/score/pri/matrix는 순수 함수로 남긴다.
"""

from __future__ import annotations

import argparse
import collections
import statistics
from datetime import date

from src.db.supabase_client import (
    get_client,
    select_all,
    upsert_tolerating_missing_columns,
)
from src.screener.gate import GateInput, evaluate_gate
from src.screener.matrix import classify
from src.finance.derive import op_surprise_label, op_surprise_pct, revenue_surprise_pct
from src.screener.pri import PriInput, compute_pri
from src.screener.score import ScoreInput, compute_score
from src.utils.console import enable_utf8_stdout

FUND_COLUMNS = (
    "code,fiscal_year,fiscal_quarter,revenue,op,revenue_yoy,op_yoy,op_status_label,"
    "opm,opm_yoy_delta,ttm_revenue,ttm_op,ttm_opm_delta,rev_2y_stack,"
    "ttm_cfo,receivables,inventory,shares_yoy,is_estimate"
)
UNI_COLUMNS = "code,name,board,industry,is_excluded,exclude_reason,sector_caveat,listed_at,market_cap_krw"
PRICE_COLUMNS = (
    "code,snap_date,close,high_52w,low_52w,high_52w_drawdown_pct,"
    "announcement_return_pct,per_vs_9q_avg_pct,foreign_net_ratio_5d,rsi_14,"
    "per,pbr,avg_value_20d"
)
CONSENSUS_COLUMNS = (
    "code,fiscal_year,fiscal_quarter,n_estimates,revenue_est,op_est,snapshot_at"
)


def _qi(year: int, quarter: int) -> int:
    return year * 4 + (quarter - 1)


def load() -> tuple[dict, dict, dict, dict]:
    funds = select_all("quarterly_fundamentals", FUND_COLUMNS)  # range() 페이징 (T7)
    universe = {u["code"]: u for u in select_all("krx_universe", UNI_COLUMNS)}
    by_code: dict[str, dict[int, dict]] = collections.defaultdict(dict)
    for row in funds:
        by_code[row["code"]][_qi(row["fiscal_year"], row["fiscal_quarter"])] = row

    # 종목별 **최신** 시세 스냅샷 1건. PRI의 입력이다.
    prices: dict[str, dict] = {}
    for row in select_all("price_snapshots", PRICE_COLUMNS):
        prev = prices.get(row["code"])
        if prev is None or row["snap_date"] > prev["snap_date"]:
            prices[row["code"]] = row

    # 컨센서스는 **(종목, 분기)** 단위다. 스코어 C축의 입력이 된다.
    # ★ 분기를 안 맞추면 다른 분기 추정치로 서프라이즈를 계산하게 된다 — 조용히 틀린다.
    consensus: dict[tuple[str, int], dict] = {}
    for row in select_all("consensus_snapshots", CONSENSUS_COLUMNS, filters={"source": "naver"}):
        key = (row["code"], _qi(row["fiscal_year"], row["fiscal_quarter"]))
        prev = consensus.get(key)
        if prev is None or (row.get("snapshot_at") or "") > (prev.get("snapshot_at") or ""):
            consensus[key] = row
    return by_code, universe, prices, consensus


def build_pri_input(price: dict | None) -> PriInput:
    """시세 스냅샷 → PRI 입력.

    ★ 없는 값은 None으로 둔다 — 0으로 채우면 '미반영'으로 잘못 읽혀 ★로 승격된다(T31).
    """
    if not price:
        return PriInput()
    return PriInput(
        high_52w_drawdown_pct=_f(price, "high_52w_drawdown_pct"),
        announcement_return_pct=_f(price, "announcement_return_pct"),
        per_vs_9q_avg_pct=_f(price, "per_vs_9q_avg_pct"),
        foreign_net_ratio_5d_pct=_f(price, "foreign_net_ratio_5d"),
        rsi_14=_f(price, "rsi_14"),
    )


def _f(row: dict | None, key: str) -> float | None:
    if row is None or row.get(key) is None:
        return None
    return float(row[key])


def sector_percentiles(
    by_code: dict, universe: dict, index: int
) -> dict[str, float]:
    """업종 내 OPM 백분위(상위 %). B4에 쓴다. 같은 업종 5종목 미만이면 판정하지 않는다."""
    by_industry: dict[str, list[tuple[str, float]]] = collections.defaultdict(list)
    for code, series in by_code.items():
        opm = _f(series.get(index), "opm")
        industry = (universe.get(code) or {}).get("industry")
        if opm is not None and industry:
            by_industry[industry].append((code, opm))

    out: dict[str, float] = {}
    for members in by_industry.values():
        if len(members) < 5:
            continue
        ordered = sorted(members, key=lambda x: x[1], reverse=True)
        for rank, (code, _) in enumerate(ordered):
            out[code] = (rank + 1) / len(ordered) * 100  # 작을수록 상위
    return out


def build_consensus_fields(t: dict | None, cons: dict | None) -> dict:
    """컨센서스 대비 서프라이즈 → 스코어 C축 입력.

    ★ 추정기관 2곳 미만은 컨센서스가 아니다(`MIN_ESTIMATES`) — `has_consensus()`가 막는다.
      여기서 `n_estimates`를 넘기지 않으면 C축이 통째로 분모에서 빠진다(ADR 2).
      **그게 정상 경로다.** 코스닥 1,089사가 리포트 0건이라, 컨센서스 없음이 다수다.
    ★ 부호가 바뀌는 구간에서는 %를 만들지 않는다 — `op_surprise_pct`가 None을 준다.
      적자 예상(−100) → 흑자(+50)에서 %를 내면 −150%가 되어 최고의 서프라이즈가
      0점으로 뒤집힌다.
    """
    if not cons or not t:
        return {
            "n_estimates": None, "op_surprise_pct": None,
            "revenue_surprise_pct": None, "op_surprise_label": None,
        }
    op, op_est = _f(t, "op"), _f(cons, "op_est")
    return {
        "n_estimates": cons.get("n_estimates"),
        "op_surprise_pct": op_surprise_pct(op, op_est),
        # %를 못 만드는 구간은 라벨이 대신 점수를 만든다 — 안 넘기면 9점을 조용히 잃는다.
        "op_surprise_label": op_surprise_label(op, op_est),
        "revenue_surprise_pct": revenue_surprise_pct(
            _f(t, "revenue"), _f(cons, "revenue_est")
        ),
    }


def build_inputs(
    series: dict,
    universe_row: dict,
    index: int,
    pct: float | None,
    cons: dict | None = None,
    price: dict | None = None,
):
    t, t1, t4, t5 = (series.get(index - o) for o in (0, 1, 4, 5))

    ttm_history = tuple(
        v for v in (_f(series.get(index - o), "ttm_revenue") for o in range(8)) if v is not None
    )
    last4 = tuple(
        v for v in (_f(series.get(index - o), "revenue") for o in (1, 2, 3, 4)) if v is not None
    )

    gate_in = GateInput(
        revenue_t=_f(t, "revenue"), revenue_t1=_f(t1, "revenue"), revenue_t4=_f(t4, "revenue"),
        op_t=_f(t, "op"), op_t1=_f(t1, "op"), op_t4=_f(t4, "op"),
        revenue_yoy_t=_f(t, "revenue_yoy"), revenue_yoy_t1=_f(t1, "revenue_yoy"),
        # ★ op_yoy_t1을 빼먹으면 G2가 **전 종목 None(판정 불가)**이 된다 —
        #   에러 없이 발굴 결과가 통째로 비는 형태다.
        op_yoy_t=_f(t, "op_yoy"), op_yoy_t1=_f(t1, "op_yoy"),
        op_status_label=(t or {}).get("op_status_label"),
        rev_2y_t=_f(t, "rev_2y_stack"), rev_2y_t1=_f(t1, "rev_2y_stack"),
        ttm_revenue_t=_f(t, "ttm_revenue"), ttm_revenue_history=ttm_history,
        revenue_last4=last4,
        # ★ G4(OPM YoY 상승). 안 넘기면 **전 종목이 판정 불가**가 되어 게이트 통과가
        #   0이 된다 — op_yoy_t1을 빠뜨렸을 때와 같은 모양의 사고다.
        opm_yoy_delta=_f(t, "opm_yoy_delta"),
        is_excluded=bool(universe_row.get("is_excluded")),
        exclude_reason=universe_row.get("exclude_reason"),
        fiscal_quarter=(t or {}).get("fiscal_quarter"),
    )

    gate_t1 = evaluate_gate(
        GateInput(
            revenue_t=_f(t1, "revenue"), revenue_t1=_f(series.get(index - 2), "revenue"),
            revenue_t4=_f(t5, "revenue"),
            op_t=_f(t1, "op"), op_t1=_f(series.get(index - 2), "op"), op_t4=_f(t5, "op"),
            revenue_yoy_t=_f(t1, "revenue_yoy"),
            revenue_yoy_t1=_f(series.get(index - 2), "revenue_yoy"),
        )
    )

    score_in = ScoreInput(
        revenue_yoy_t=_f(t, "revenue_yoy"), revenue_yoy_t1=_f(t1, "revenue_yoy"),
        op_yoy_t=_f(t, "op_yoy"), op_yoy_t1=_f(t1, "op_yoy"),
        ttm_revenue_t=_f(t, "ttm_revenue"), ttm_revenue_t1=_f(t1, "ttm_revenue"),
        # ★ A3는 2026-08-22부터 **TTM 영업이익**을 본다. 빠뜨리면 A3가 전 종목 None이
        #   되고, A축은 나머지 항목으로 '측정됨'이라 분모에서 빠지지도 않는다 —
        #   에러 없이 4점씩 조용히 감점된다.
        ttm_op_t=_f(t, "ttm_op"), ttm_op_t1=_f(t1, "ttm_op"),
        g1_t=None, g1_t1=gate_t1.g1,  # g1_t는 아래에서 채운다
        opm_yoy_delta=_f(t, "opm_yoy_delta"), ttm_opm_delta=_f(t, "ttm_opm_delta"),
        opm=_f(t, "opm"), sector_opm_percentile=pct,
        # 정기보고서 확정행만 D축을 연다(T4). 잠정행에서 유동성 하나만 있다고
        # D축을 열면 없는 회계품질 항목이 조용히 0점 처리된다.
        is_final=bool(t) and not bool(t.get("is_estimate")),
        ttm_cfo=_f(t, "ttm_cfo"),
        ttm_op=_f(t, "ttm_op"),
        shares_yoy=_f(t, "shares_yoy"),
        receivables_inventory_yoy=_combined_yoy(t, t4, "receivables", "inventory"),
        avg_value_20d=_f(price, "avg_value_20d"),
        **build_consensus_fields(t, cons),
    )
    return gate_in, score_in


def _combined_yoy(
    current: dict | None,
    previous: dict | None,
    *fields: str,
) -> float | None:
    """여러 계정 합계의 YoY(%). 하나라도 결측이면 추측해 더하지 않는다."""
    if current is None or previous is None:
        return None
    current_values = [_f(current, field) for field in fields]
    previous_values = [_f(previous, field) for field in fields]
    if any(value is None for value in (*current_values, *previous_values)):
        return None
    current_sum = sum(value for value in current_values if value is not None)
    previous_sum = sum(value for value in previous_values if value is not None)
    if previous_sum <= 0:
        return None
    return (current_sum / previous_sum - 1) * 100


def _yq(index: int) -> tuple[int, int]:
    return index // 4, index % 4 + 1


def last_reportable_index(today: date | None = None) -> int:
    """오늘 기준으로 **끝났을 수 있는** 마지막 분기.

    분기가 끝나지 않았으면 실적도 있을 수 없다.
    """
    today = today or date.today()
    return _qi(today.year, (today.month - 1) // 3 + 1) - 1


def target_index(series: dict, fixed: int | None, ceiling: int | None = None) -> int | None:
    """이 종목을 어느 분기로 평가할 것인가.

    ★ 분기를 전 종목 공통으로 고정하면 **먼저 발표한 종목의 최신 실적이 통째로 무시된다.**
      실측: 2026.2Q 잠정 357종목이 들어왔는데 고정 인덱스가 2026.1Q면 한 종목도 반영되지 않는다.
      대상이 '등록된 종목'이 아니라 '시총 하한을 넘는 전 종목'이므로(ADR 6),
      평가 시점도 종목마다 다른 게 맞다 — 발표 시기가 제각각이기 때문이다.
    ★ 매출이 없는 행(빈 껍데기)은 최신으로 치지 않는다.
    ★ **아직 끝나지 않은 분기는 고르지 않는다.** 비12월 결산 등으로 미래 분기 행이 섞여
      들어온다(실측: 한스바이오메드 042520이 2026-08 시점에 2026.3Q 행을 갖고 있다).
      그냥 최신을 고르면 존재할 수 없는 분기로 평가되고, 비교 대상(t−4)도 없어
      조용히 '판정 불가'로 빠진다.
    """
    if fixed is not None:
        return fixed
    ceiling = ceiling if ceiling is not None else last_reportable_index()
    reported = [
        i for i, row in series.items()
        if row.get("revenue") is not None and i <= ceiling
    ]
    return max(reported) if reported else None


def run(fixed: int | None, save: bool) -> int:
    by_code, universe, prices, consensus = load()
    print(f"시세 스냅샷 {len(prices)}종목 로드 · "
          f"상대수익률 측정 {sum(1 for p in prices.values() if p.get('rel_ret_3m') is not None)}")
    print(f"컨센서스 {len(consensus)}건 로드 · "
          f"추정기관 2곳 이상 {sum(1 for c in consensus.values() if (c.get('n_estimates') or 0) >= 2)}")

    index_of = {
        code: target_index(series, fixed)
        for code, series in by_code.items()
        if code in universe
    }
    index_of = {c: i for c, i in index_of.items() if i is not None}
    latest = max(index_of.values()) if index_of else None

    # 업종 백분위(B4)는 **같은 분기끼리** 비교해야 한다. 분기가 섞이면 비교가 아니다.
    pcts: dict[str, float] = {}
    for idx in set(index_of.values()):
        cohort = {c: s for c, s in by_code.items() if index_of.get(c) == idx}
        pcts.update(sector_percentiles(cohort, universe, idx))

    rows = []
    for code, index in index_of.items():
        uni = universe[code]
        gate_in, score_in = build_inputs(
            by_code[code], uni, index, pcts.get(code), consensus.get((code, index)),
            prices.get(code),
        )
        gate = evaluate_gate(gate_in)
        score_in = ScoreInput(**{**score_in.__dict__, "g1_t": gate.g1})
        score = compute_score(score_in)
        pri = compute_pri(build_pri_input(prices.get(code)))
        grade = classify(
            score.score_norm, pri.pri,
            base_effect_warning=gate.base_effect_warning,
            gate_passed=gate.passed,
        )
        rows.append((code, uni, gate, score, pri, grade, index, score_in.is_final))

    _report(rows, latest)
    if save:
        return _save(rows, fixed_mode=fixed is not None)
    print("\n(--save 미지정 — DB에 기록하지 않았다)")
    return 0


def _report(rows: list, latest: int | None) -> None:
    line = "═" * 72
    print(line)
    print(f"P3 스크리너 — 대상 {len(rows)}종목 · 종목별 최신 발표 분기 기준")
    print(line)

    print("\n[0] 평가 분기 분포")
    quarters = collections.Counter(r[6] for r in rows)
    for index, n in sorted(quarters.items(), reverse=True):
        year, quarter = _yq(index)
        lag = (latest - index) if latest is not None else 0
        # ★ 뒤처진 분기로 평가된 종목은 '실적이 나쁜' 게 아니라 '아직 발표 전'이다.
        note = "" if lag == 0 else f"  ← {lag}분기 뒤 (미발표 또는 수집 누락)"
        print(f"    {year}.{quarter}Q  {n:>5}종목{note}")
    stale = sum(n for i, n in quarters.items() if latest is not None and latest - i >= 3)
    if stale:
        print(f"    ⚠ 3분기 이상 뒤처진 종목 {stale}개 — 수집 누락일 수 있다. 점수를 믿지 말 것.")

    verdicts = collections.Counter(
        "통과" if r[2].passed is True else ("탈락" if r[2].passed is False else "판정불가")
        for r in rows
    )
    print("\n[1] 게이트")
    for k in ("통과", "탈락", "판정불가"):
        print(f"    {k:6} {verdicts[k]:>5}종목")

    fails = collections.Counter()
    for g in (r[2] for r in rows):
        if g.passed is False:
            for name, v in (("G1 매출가속", g.g1), ("G2 이익가속", g.g2),
                            ("G3 업종/상장", g.g3), ("G4 OPM상승", g.g4)):
                if v is False:
                    fails[name] += 1
    print("    탈락 사유(중복 가능):")
    for name, n in fails.most_common():
        print(f"      {name:14} {n:>5}")
    print(f"    turnaround(흑전·적자축소) {sum(1 for r in rows if r[2].turnaround)}종목")

    passed = [r for r in rows if r[2].passed is True]
    print("\n[2] 기저효과 경고 (게이트 통과분)")
    warned = sum(1 for r in passed if r[2].base_effect_warning)
    unmeasurable = sum(1 for r in passed if not r[2].base_effect_measurable)
    print(f"    경고 {warned} / 통과 {len(passed)}")
    print(f"    ⚠ 3조건 전부 판정 불가 {unmeasurable}종목 — 경고를 붙이지 않았다")
    checks = collections.Counter()
    for r in passed:
        for k, v in r[2].base_effect_checks.items():
            if v is not None:
                checks[k] += 1
    print(f"    조건별 판정 가능 건수: {dict(checks)}")

    print("\n[3] 스코어 (게이트 통과분)")
    stage_counts = collections.Counter(
        "확정" if row[7] else "잠정" for row in rows
    )
    percentile_preview = percentile_by_period([
        (code, *_yq(index), score.score_norm)
        for code, _u, _g, score, _p, _gr, index, _final in rows
    ])
    print(
        f"    시점 분포 {dict(stage_counts)} · 분기 백분위 산출 "
        f"{sum(value is not None for value in percentile_preview.values())}/{len(rows)}종목"
    )
    scored = [r[3] for r in passed if r[3].score_norm is not None]
    if scored:
        values = sorted(s.score_norm for s in scored)
        print(f"    측정 {len(values)}종목 · 중앙값 {statistics.median(values):.1f} · "
              f"상위10% {values[int(len(values) * 0.9)]:.1f} · 최고 {values[-1]:.1f}")
        denoms = collections.Counter(s.denominator for s in scored)
        print(f"    정규화 분모 분포: {dict(denoms)}")
        print(f"    has_consensus=True: {sum(1 for s in scored if s.has_consensus)}종목")
        miss = collections.Counter()
        for s in scored:
            for item in s.missing_items:
                miss[item] += 1
        print(f"    축 내부 결측(조용한 감점) 항목별: {dict(miss)}")
        avg_lost = statistics.mean(s.missing_item_points for s in scored)
        print(f"    종목당 평균 조용한 감점 {avg_lost:.1f}점")

        # SC6: 컨센서스 없는 종목이 상위에서 밀려나면 이 시스템의 존재 이유가 사라진다(ADR 2).
        top20 = sorted(scored, key=lambda s: s.score_norm, reverse=True)[:20]
        no_cons = sum(1 for s in top20 if not s.has_consensus)
        print(f"    ★ SC6 — 상위 20 중 컨센서스 없음 {no_cons}종목 "
              f"({no_cons / len(top20) * 100:.0f}%) "
              f"{'✓ 30% 이상' if no_cons / len(top20) >= 0.3 else '⚠ 30% 미만 — 편향 점검'}")
        with_cons = [s for s in scored if s.has_consensus]
        if with_cons:
            cv = sorted(s.score_norm for s in with_cons)
            wo = sorted(s.score_norm for s in scored if not s.has_consensus)
            print(f"    컨센 있음 {len(cv)}종목 중앙값 {statistics.median(cv):.1f} · "
                  f"없음 {len(wo)}종목 중앙값 {statistics.median(wo):.1f}")

    print("\n[4] PRI · 등급")
    pris = [r[4] for r in rows if r[4].pri is not None]
    if pris:
        values = sorted(p.pri for p in pris)
        print(f"    PRI 측정 {len(pris)}/{len(rows)}종목 · 중앙값 {values[len(values) // 2]:.1f}")
        print(f"    정규화 분모 분포: "
              f"{dict(collections.Counter(p.denominator for p in pris))}")
    else:
        print("    ⚠ PRI 측정 0종목 — price_snapshots가 비었거나 rel_ret_3m이 전부 없다.")
    grades = collections.Counter(r[5].grade for r in rows)
    print(f"    등급: {dict(grades)}")
    print(f"    발송 대상(★/○) {sum(1 for r in rows if r[5].notify)}종목 "
          f"· 기저효과 강등 {sum(1 for r in rows if r[5].demoted)}종목")

    saturated = sum(1 for s in scored if s.score_norm is not None and s.score_norm >= 99.99)
    print(f"    ★ 만점(100.0) 종목 {saturated}개")
    print("      위 축 내부 결측은 실제 수집값이 채워질수록 줄어야 한다. 0점으로 추정하지 않는다.")

    print("\n[5] 스코어 상위 10 (게이트 통과 · 참고용)")
    top = sorted(passed, key=lambda r: r[3].score_norm or -1, reverse=True)[:10]
    print(f"    {'종목':>16} {'코드':8} {'분기':7}{'스코어':>8}{'A':>6}{'B':>6}"
          f"{'YoYΔ%p':>9}  등급  경고")
    for code, uni, gate, score, pri, grade, index, _is_final in top:
        warn = "기저효과" if gate.base_effect_warning else ""
        delta = gate.detail.get("rev_yoy_delta_pp")
        delta_txt = f"{delta:>9.1f}" if delta is not None else f"{'—':>9}"
        year, quarter = _yq(index)
        print(f"    {uni['name'][:14]:>16} {code:8} {year}.{quarter}Q{score.score_norm:>8.1f}"
              f"{score.score_a or 0:>6.1f}{score.score_b or 0:>6.1f}{delta_txt}"
              f"  {grade.grade or '—'}  {warn}")
    print(line)


def score_stage_fields(
    score: float | None,
    is_final: bool,
    previous: dict | None,
) -> dict[str, float | None]:
    """잠정·확정 점수를 같은 행에 보존하고 확정−잠정 차이를 만든다(T4)."""
    previous = previous or {}
    detail = previous.get("gate_detail")
    valid_flash = isinstance(detail, dict) and (
        detail.get("score_stage") == "flash"
        or detail.get("flash_baseline_valid") is True
    )
    flash = _f(previous, "score_flash") if valid_flash else None
    final = _f(previous, "score_final")
    if is_final:
        final = score
    else:
        flash = score
    delta = final - flash if final is not None and flash is not None else None
    return {"score_flash": flash, "score_final": final, "score_delta": delta}


def percentile_by_period(
    rows: list[tuple[str, int, int, float | None]],
) -> dict[tuple[str, int, int], float | None]:
    """분기 안에서 높은 점수가 100에 가까운 tie-aware 백분위를 만든다.

    결측은 모집단에서도 제외하고 결과도 None이다. 방향을 뒤집는 정렬 트릭으로
    결측을 처리하면 최하위 대신 1등이 되는 T104와 같은 오류가 난다.
    """
    cohorts: dict[tuple[int, int], list[float]] = collections.defaultdict(list)
    for _code, year, quarter, score in rows:
        if score is not None:
            cohorts[(year, quarter)].append(score)

    out: dict[tuple[str, int, int], float | None] = {}
    for code, year, quarter, score in rows:
        values = cohorts[(year, quarter)]
        if score is None or not values:
            out[(code, year, quarter)] = None
            continue
        lower = sum(value < score for value in values)
        equal = sum(value == score for value in values)
        out[(code, year, quarter)] = (lower + equal) / len(values) * 100
    return out


def _save(rows: list, fixed_mode: bool = False) -> int:
    db = get_client()
    existing_rows = select_all(
        "screen_results",
        "code,fiscal_year,fiscal_quarter,score_flash,score_final,gate_detail",
    )
    existing = {
        (row["code"], row["fiscal_year"], row["fiscal_quarter"]): row
        for row in existing_rows
    }
    active_scores = []
    for code, _uni, _gate, score, _pri, _grade, index, _is_final in rows:
        year, quarter = _yq(index)
        active_scores.append((code, year, quarter, score.score_norm))
    percentiles = percentile_by_period(active_scores)

    payload = []
    for code, _uni, gate, score, pri, grade, index, is_final in rows:
        year, quarter = _yq(index)
        key = (code, year, quarter)
        previous = existing.get(key) or {}
        previous_detail = previous.get("gate_detail")
        previous_flash_valid = isinstance(previous_detail, dict) and (
            previous_detail.get("score_stage") == "flash"
            or previous_detail.get("flash_baseline_valid") is True
        )
        row = {
            "code": code,
            "fiscal_year": year,
            "fiscal_quarter": quarter,
            "gate_passed": gate.passed,
            "gate_detail": {
                "g0": gate.g0, "g1": gate.g1, "g2": gate.g2, "g3": gate.g3,
                "g4": gate.g4,
                "detail": gate.detail,
                "base_effect_checks": gate.base_effect_checks,
                "base_effect_measurable": gate.base_effect_measurable,
                "score_stage": "final" if is_final else "flash",
                "flash_baseline_valid": (not is_final) or previous_flash_valid,
            },
            "base_effect_warning": gate.base_effect_warning,
            "turnaround": gate.turnaround,
            **score_stage_fields(score.score_norm, is_final, previous),
            "pctile_in_quarter": percentiles[key],
            "pri": pri.pri,
            "pri_detail": pri.detail,
            "grade": grade.grade,
        }
        row.update(score.as_db_row())
        payload.append(row)

    saved, dropped = upsert_tolerating_missing_columns(
        db,
        "screen_results",
        payload,
        on_conflict="code,fiscal_year,fiscal_quarter",
    )
    print(f"\n✓ screen_results upsert {saved}행")
    if dropped:
        print(f"  ⚠ DB에 없는 컬럼을 빼고 저장했다: {', '.join(dropped)}")

    # ★ 평가 분기보다 **미래**에 있는 행은 지운다.
    #   비12월 결산 등으로 미래 분기 행이 섞여 들어오던 시절(T36 이전)의 잔재다.
    #   존재할 수 없는 분기라 어떤 소비자도 읽으면 안 된다.
    #   과거 분기 행은 **남긴다** — P11(성과 추적)이 쓸 이력이다.
    #
    # ★★ 분기를 고정해 돌릴 때는 **절대 하지 않는다.**
    #    `--quarter 2026.1`로 과거 스냅샷을 다시 만드는 경우, 모든 종목의 평가 분기가
    #    2026.1Q가 되어 **정상적인 2026.2Q 행이 통째로 삭제된다.**
    #    되돌릴 수 없고, 삭제 카운터만 보면 "정리했다"로 읽힌다.
    if fixed_mode:
        print("  (분기 고정 모드 — 미래 분기 정리를 건너뛴다. 최신 결과를 지울 수 있다)")
        return 0

    evaluated = {
        code: index for code, _u, _g, _s, _p, _gr, index, _final in rows
    }
    doomed = [
        r for r in select_all("screen_results", "code,fiscal_year,fiscal_quarter")
        if code_index_is_future(r, evaluated)
    ]
    for r in doomed:
        (
            db.table("screen_results").delete()
            .eq("code", r["code"])
            .eq("fiscal_year", r["fiscal_year"])
            .eq("fiscal_quarter", r["fiscal_quarter"])
            .execute()
        )
    print(f"  미래 분기 잔재 정리: {len(doomed)}행 삭제")
    return 0


def code_index_is_future(row: dict, evaluated: dict[str, int]) -> bool:
    """이 행이 해당 종목의 평가 분기보다 뒤(미래)에 있는가."""
    target = evaluated.get(row["code"])
    if target is None:
        return False
    return _qi(row["fiscal_year"], row["fiscal_quarter"]) > target


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="P3 스크리너")
    parser.add_argument("--quarter", default="latest",
                        help="'latest'(기본, 종목별 최신 발표 분기) 또는 '2026.1' 고정")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    fixed = None
    if args.quarter != "latest":
        year, quarter = args.quarter.split(".")
        fixed = _qi(int(year), int(quarter))
    return run(fixed, args.save)


if __name__ == "__main__":
    raise SystemExit(main())
