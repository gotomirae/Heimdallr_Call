# PRD Ref: §2 검토⑥, §6, §10 · traps.md T32, T40
"""P11 결과 추적 실행 — 발표일 기준 수익률을 모아 `outcome_tracking`에 넣는다.

    python -m src.analysis.outcome_run                  # 리포트만
    python -m src.analysis.outcome_run --save           # DB 저장
    python -m src.analysis.outcome_run --quarter 2026.2 # 분기 지정

★ 이 모듈만 I/O를 한다. `outcome.py`는 순수 함수로 남긴다.
★ KIS 일봉을 종목당 1콜 쓴다. 유량 초과(T32)를 재시도로 흡수한다.
"""

from __future__ import annotations

import argparse
import collections
import statistics
import time
from datetime import date, timedelta

from src.analysis.outcome import (
    HORIZONS,
    horizon_column,
    horizon_label,
    Outcome,
    group_stats,
    measure,
    spearman,
)
from src.collectors.kis_client import KisClient
from src.collectors.kis_prices import fetch_daily_closes, fetch_index_closes
from src.db.supabase_client import (
    get_client,
    select_all,
    upsert_tolerating_missing_columns,
)
from src.screener.score import active_score
from src.utils.console import enable_utf8_stdout

#: 발표일로부터 이만큼 전후의 일봉을 받는다. D+60을 담으려면 넉넉해야 한다.
LOOKBACK_DAYS = 10
LOOKFORWARD_DAYS = 120
INDEX_OF_BOARD = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ"}
REQUEST_INTERVAL_SEC = 0.15

SCREEN_COLUMNS = (
    "code,fiscal_year,fiscal_quarter,grade,score_flash,score_final,pri,"
    "raw_a1,raw_a2,raw_a3,raw_a4,raw_b1,raw_b2,raw_b3,raw_b4,"
    "raw_c1,raw_c2,has_consensus,base_effect_warning"
)


def _ymd(value: str) -> str:
    """'2026-07-15T00:00:00+00:00' 또는 '2026-07-15' → '20260715'."""
    return value[:10].replace("-", "")


def announce_dates() -> dict[tuple[str, int, int], str]:
    """(종목, 연, 분기) → 최초 발표일.

    ★ 같은 분기에 공시가 여러 건이면 **가장 이른 것**이 발표일이다.
      정정·상세 공시를 발표일로 잡으면 시장이 이미 반응한 뒤부터 재기 시작해
      초과수익이 통째로 사라진다.
    """
    funds = {
        (f["code"], f["fiscal_year"], f["fiscal_quarter"])
        for f in select_all("quarterly_fundamentals", "code,fiscal_year,fiscal_quarter")
    }
    out: dict[tuple[str, int, int], str] = {}
    rows = [
        d for d in select_all(
            "earnings_disclosures", "code,disclosed_at,doc_type"
        ) if d.get("code") and d.get("disclosed_at")
    ]
    rows.sort(key=lambda d: d["disclosed_at"])

    # 공시에는 분기가 없다 — 발표일이 속한 분기 직전 분기의 실적으로 본다.
    for row in rows:
        day = _ymd(row["disclosed_at"])
        year, month = int(day[:4]), int(day[4:6])
        quarter = (month - 1) // 3 + 1
        # 발표는 해당 분기가 끝난 뒤에 나온다 → 직전 분기 실적이다.
        quarter -= 1
        if quarter == 0:
            year, quarter = year - 1, 4
        key = (row["code"], year, quarter)
        if key in funds and key not in out:
            out[key] = day
    return out


def latest_screens() -> dict[tuple[str, int, int], dict]:
    return {
        (s["code"], s["fiscal_year"], s["fiscal_quarter"]): s
        for s in select_all("screen_results", SCREEN_COLUMNS)
    }


def collect(quarter_filter: tuple[int, int] | None, limit: int | None) -> list[Outcome]:
    universe = {u["code"]: u for u in select_all("krx_universe", "code,name,board")}
    dates = announce_dates()
    screens = latest_screens()

    keys = sorted(dates)
    if quarter_filter:
        keys = [k for k in keys if (k[1], k[2]) == quarter_filter]
    if limit:
        keys = keys[:limit]

    if not keys:
        return []

    begin = min(dates[k] for k in keys)
    end = (date.today() + timedelta(days=1)).strftime("%Y%m%d")
    lookback = (
        date(int(begin[:4]), int(begin[4:6]), int(begin[6:])) - timedelta(days=LOOKBACK_DAYS)
    ).strftime("%Y%m%d")

    print(f"대상 {len(keys)}건 · 일봉 구간 {lookback}~{end}")
    indexes = {
        name: fetch_index_closes(name, lookback, end) for name in ("KOSPI", "KOSDAQ")
    }
    print(f"지수 종가 KOSPI {len(indexes['KOSPI'])}일 · KOSDAQ {len(indexes['KOSDAQ'])}일")

    client = KisClient()
    results: list[Outcome] = []
    failures: collections.Counter = collections.Counter()

    for i, key in enumerate(keys, 1):
        code, year, quarter = key
        uni = universe.get(code) or {}
        screen = screens.get(key) or {}

        try:
            closes = fetch_daily_closes(client, code, lookback, end)
        except Exception as exc:
            failures[type(exc).__name__] += 1
            closes = {}  # 거래정지·상폐로 취급 — 조용히 빼지 않는다
        time.sleep(REQUEST_INTERVAL_SEC)

        index_closes = indexes.get(INDEX_OF_BOARD.get(uni.get("board"), "KOSPI"), {})
        results.append(
            Outcome(
                code=code, fiscal_year=year, fiscal_quarter=quarter,
                announce_date=f"{dates[key][:4]}-{dates[key][4:6]}-{dates[key][6:]}",
                grade_at_announce=screen.get("grade"),
                score_at_announce=active_score(screen),
                pri_at_announce=screen.get("pri"),
                horizons=measure(closes, index_closes, dates[key]),
            )
        )
        if i % 100 == 0:
            print(f"    {i}/{len(keys)}")

    if failures:
        print(f"  일봉 조회 실패: {dict(failures)}")
    return results


def report(results: list[Outcome], screens: dict) -> None:
    line = "═" * 74
    print(line)
    print(f"P11 결과 추적 — {len(results)}건")
    print(line)

    rows = [o.as_db_row() for o in results]

    print("\n[1] 시점별 측정 가능 건수")
    print("    ★ '측정 불가'는 0%가 아니다 — 아직 그만큼의 거래일이 안 지났다는 뜻이다.")
    for days in HORIZONS:
        measured = sum(1 for o in results if o.horizons.get(days, None) and o.horizons[days].measured)
        reasons = collections.Counter(
            o.horizons[days].reason for o in results
            if days in o.horizons and not o.horizons[days].measured
        )
        print(f"    {horizon_label(days):<11} 측정 {measured:>4}/{len(results)}  "
              f"미측정 사유 {dict(reasons)}")

    print("\n[2] 등급별 초과수익 중앙값 (%p)")
    print(f"    {'등급':6}{'대상':>6}{'측정':>6}", end="")
    for days in HORIZONS:
        # ★ 'D+-5'가 아니라 'D-5'. 부호를 두 번 쓰면 표가 안 읽힌다.
        head = f"D{days:+d}" if days != 0 else "D0"
        print(f"{head:>12}", end="")
    print()
    for grade in ("★", "○", "△", "·", "✕", None):
        subset = [r for r in rows if r["grade_at_announce"] == grade]
        if not subset:
            continue
        label = grade or "판정불가"
        print(f"    {label:6}{len(subset):>6}", end="")
        for days in HORIZONS:
            field = f"excess_d{horizon_column(days)}"
            values = [r[field] for r in subset if r[field] is not None]
            # 값과 표본 수를 함께 낸다 — n=1짜리 중앙값을 신호로 읽으면 안 된다.
            cell = f"{statistics.median(values):+.2f}({len(values)})" if values else "—"
            print(f"{cell:>12}", end="")
        print()

    print("\n[3] 축별 정보계수(IC) — 어느 축이 실제로 작동하는가")
    print("    ★ 표본이 작으면 통계적 유의성은 없다. 방향만 본다.")
    # ★ D+20/D+60이 목표지만 시즌이 막 끝난 시점에는 거래일이 모자란다.
    #   측정 가능한 시점 **전부**에서 계산하고 어느 시점인지 명시한다 —
    #   D+1 IC를 D+20 IC로 읽으면 완전히 다른 결론이 나온다.
    for days in HORIZONS:
        excess = [r[f"excess_d{horizon_column(days)}"] for r in rows]
        n_measured = sum(1 for v in excess if v is not None)
        if n_measured < 3:
            print(f"    {horizon_label(days)}: 측정 {n_measured}건 — 3건 미만이라 계산하지 않는다")
            continue
        print(f"    {horizon_label(days)} (측정 {n_measured}건):")
        for axis, items in (
            ("A 성장가속", ("raw_a1", "raw_a2", "raw_a3", "raw_a4")),
            ("B 수익성", ("raw_b1", "raw_b2", "raw_b3", "raw_b4")),
            ("C 서프라이즈", ("raw_c1", "raw_c2")),
        ):
            values = []
            for r in rows:
                s = screens.get((r["code"], r["fiscal_year"], r["fiscal_quarter"])) or {}
                parts = [s.get(k) for k in items]
                values.append(
                    sum(v for v in parts if v is not None) if any(v is not None for v in parts)
                    else None
                )
            ic = spearman(values, excess)
            print(f"      {axis:12} IC {f'{ic:+.3f}' if ic is not None else '—(표본 부족)'}")
        score_ic = spearman([r["score_at_announce"] for r in rows], excess)
        pri_ic = spearman([r["pri_at_announce"] for r in rows], excess)
        print(f"      {'스코어 총점':12} IC {f'{score_ic:+.3f}' if score_ic is not None else '—'}")
        print(f"      {'PRI':12} IC {f'{pri_ic:+.3f}' if pri_ic is not None else '—'}"
              f"   (음수여야 정상 — 미반영일수록 초과수익이 커야 한다)")

    # ★ 측정 건수가 가장 많은 시점으로 비교한다 — D+20이 비면 D+5로 내려간다.
    #   비어 있는 시점으로 비교하면 "n=1 vs n=1"을 근거로 SC6를 판정하게 된다.
    best = max(
        HORIZONS,
        key=lambda d: sum(
            1 for r in rows if r[f"excess_d{horizon_column(d)}"] is not None
        ),
    )
    print(f"\n[4] SC6 · SC8 검증 그룹 비교 ({horizon_label(best)})")
    print("    ★ SC6: 컨센서스 없는 종목이 구조적으로 불리하지 않아야 한다(ADR 2).")
    for key, label in (("has_consensus", "컨센서스"), ("base_effect_warning", "기저효과 경고")):
        merged = []
        for r in rows:
            s = screens.get((r["code"], r["fiscal_year"], r["fiscal_quarter"])) or {}
            merged.append({**r, key: s.get(key)})
        stats = group_stats(merged, key, f"excess_d{horizon_column(best)}")
        parts = []
        for k, v in sorted(stats.items(), key=lambda x: str(x[0])):
            med = v["median"]
            parts.append(
                f"{k}: n={v['n']} 중앙값 "
                + (f"{med:+.2f}" if med is not None else "—")
            )
        print(f"    {label}: {' · '.join(parts)}")
    print(line)


def save(results: list[Outcome]) -> int:
    payload = [o.as_db_row() for o in results]
    db = get_client()
    for i in range(0, len(payload), 500):
        db.table("outcome_tracking").upsert(
            payload[i : i + 500], on_conflict="code,fiscal_year,fiscal_quarter"
        ).execute()
    print(f"\n✓ outcome_tracking upsert {len(payload)}행")
    return 0


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="P11 결과 추적")
    parser.add_argument("--quarter", default=None, help="예: 2026.2")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    qf = None
    if args.quarter:
        y, q = args.quarter.split(".")
        qf = (int(y), int(q))

    results = collect(qf, args.limit)
    if not results:
        print("대상이 없다 — 발표일과 매칭되는 분기 재무가 없다.")
        return 0

    # ★★ **저장을 리포트보다 먼저** 한다.
    #   실측(2026-08-17): 리포트가 KeyError로 죽어 **481건 수집분이 통째로 버려졌다.**
    #   collect()는 종목당 KIS 일봉을 한 번씩 읽으므로(수 분) 값비싼 작업인데,
    #   그 뒤에 오는 **출력용 코드**의 버그가 그걸 다 날린다.
    #   비싼 것을 먼저 확정하고, 리포트는 실패해도 데이터는 남게 한다.
    saved = 0
    if args.save:
        saved = save(results)
    else:
        print("\n(--save 미지정 — DB에 기록하지 않는다)")

    try:
        report(results, latest_screens())
    except Exception as exc:
        # 리포트는 사람이 읽는 요약일 뿐이다. 여기서 죽어도 수집·저장은 이미 끝났다.
        print(f"\n⚠ 리포트 생성 실패({type(exc).__name__}: {exc}) — "
              f"수집·저장은 완료됐다{'(저장 ' + str(saved) + '행)' if args.save else ''}.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
