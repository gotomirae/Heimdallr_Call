# PRD Ref: §6(quarterly_fundamentals), §13 (P2.5) · traps.md T7, T12, T18
"""P2.5 파생지표 반영.

    python -m src.finance.enrich            # 계산 + 검증 리포트 (DB 미기록)
    python -m src.finance.enrich --save     # + quarterly_fundamentals 갱신
    python -m src.finance.enrich --code 058470   # 한 종목만 상세 출력
"""

from __future__ import annotations

import argparse
import collections
import statistics

from src.db.supabase_client import get_client, select_all
from src.finance.derive import QuarterPoint, derive_series
from src.utils.console import enable_utf8_stdout

#: derive.Derived의 필드 → quarterly_fundamentals 컬럼 (이름이 동일하다)
DERIVED_COLUMNS = (
    "revenue_yoy",
    "revenue_qoq",
    "op_yoy",
    "op_qoq",
    "np_yoy",
    "op_status_label",
    "opm",
    "opm_yoy_delta",
    "opm_qoq_delta",
    "npm",
    "ttm_revenue",
    "ttm_op",
    "ttm_opm",
    "ttm_revenue_qoq",
    "ttm_opm_delta",
    "rev_2y_stack",
)

BASE_COLUMNS = "code,fiscal_year,fiscal_quarter,fs_div,revenue,op,np"


def load_points() -> dict[str, dict[tuple[int, int], QuarterPoint]]:
    """종목별 분기 시계열. ★ select_all이 range() 페이징을 강제한다 (T7)."""
    rows = select_all("quarterly_fundamentals", BASE_COLUMNS)
    by_code: dict[str, dict[tuple[int, int], QuarterPoint]] = collections.defaultdict(dict)
    for row in rows:
        key = (row["fiscal_year"], row["fiscal_quarter"])
        by_code[row["code"]][key] = QuarterPoint(
            revenue=_num(row["revenue"]), op=_num(row["op"]), np=_num(row["np"])
        )
    return by_code


def _num(value) -> float | None:
    """NUMERIC은 문자열로 올 수 있다. 결측은 None으로 둔다(0이 아니다)."""
    if value is None:
        return None
    return float(value)


def compute_all() -> dict[str, dict]:
    """{종목: {(연,분기): Derived}}"""
    return {code: derive_series(points) for code, points in load_points().items()}


def _pct(part: int, total: int) -> str:
    return f"{part / total * 100:5.1f}%" if total else "    —"


def report(computed: dict[str, dict]) -> None:
    line = "═" * 74
    rows = [(c, k, d) for c, per in computed.items() for k, d in per.items()]
    print(line)
    print(f"P2.5 파생지표 — {len(computed)}종목 · {len(rows)}분기")
    print(line)

    print("\n[1] 지표별 측정률 (측정 불가는 None — 0으로 채우지 않았다)")
    for column in DERIVED_COLUMNS:
        measured = sum(1 for _, _, d in rows if getattr(d, column) is not None)
        print(f"    {column:20} {measured:>6} / {len(rows)}  {_pct(measured, len(rows))}")

    print("\n[2] 부호 전환 라벨 분포 (T12 — 이 구간은 % 대신 라벨을 쓴다)")
    labels = collections.Counter(
        d.op_status_label for _, _, d in rows if d.op_status_label
    )
    for label, n in labels.most_common():
        print(f"    {label:8} {n:>5}건")
    both = sum(
        1 for _, _, d in rows if d.op_status_label is not None and d.op_yoy is not None
    )
    print(f"    라벨과 op_yoy가 동시에 있는 행: {both}건 "
          f"{'✓ (0이어야 정상)' if both == 0 else '✗ 부호 전환 구간에서 %가 계산됐다'}")

    print("\n[3] 최신 분기(2026.1Q) 분포")
    latest = [(c, d) for c, k, d in rows if k == (2026, 1)]
    yoys = sorted(d.revenue_yoy for _, d in latest if d.revenue_yoy is not None)
    if yoys:
        print(f"    매출 YoY 측정 {len(yoys)}종목 · 중앙값 {statistics.median(yoys):+.1f}% · "
              f"상위10% {yoys[int(len(yoys) * 0.9)]:+.1f}% · 하위10% {yoys[int(len(yoys) * 0.1)]:+.1f}%")
    accel = [
        c for c, d in latest
        if d.revenue_yoy is not None and d.revenue_yoy > 0
    ]
    print(f"    매출 YoY > 0 : {len(accel)}종목 / {len(latest)}")

    print("\n[4] TTM이 계절성을 실제로 줄이는가 (PRD §2 검토② 근거)")
    print("     — 종목별 분기 OPM 표준편차 vs TTM OPM 표준편차")
    wins = total = 0
    samples = []
    for code, per in computed.items():
        q = [d.opm for d in per.values() if d.opm is not None]
        t = [d.ttm_opm for d in per.values() if d.ttm_opm is not None]
        if len(q) >= 5 and len(t) >= 3:
            sq, st = statistics.pstdev(q), statistics.pstdev(t)
            total += 1
            if st < sq:
                wins += 1
            samples.append((code, sq, st))
    print(f"    TTM 표준편차가 더 작은 종목: {wins} / {total}  {_pct(wins, total)}")
    for code, sq, st in samples[:3]:
        print(f"      {code}  분기 OPM σ={sq:6.2f}%p  →  TTM OPM σ={st:6.2f}%p")

    print(line)


def detail(computed: dict[str, dict], code: str) -> None:
    per = computed.get(code)
    if per is None:
        print(f"{code}: 데이터 없음")
        return
    print(f"\n■ {code} 분기별 파생지표")
    header = f"  {'분기':<9}{'매출YoY':>10}{'매출QoQ':>10}{'영업YoY':>10}{'OPM':>9}{'OPM YoYΔ':>10}{'TTM매출':>14}{'TTM OPM':>9}{'2년스택':>10}  라벨"
    print(header)
    for key in sorted(per):
        d = per[key]
        f = lambda v, w=10, p=1: (f"{v:>{w}.{p}f}" if v is not None else f"{'—':>{w}}")
        ttm = f"{d.ttm_revenue / 1e8:>14,.0f}" if d.ttm_revenue is not None else f"{'—':>14}"
        print(f"  {key[0]}.{key[1]}Q  {f(d.revenue_yoy)}{f(d.revenue_qoq)}{f(d.op_yoy)}"
              f"{f(d.opm, 9)}{f(d.opm_yoy_delta)}{ttm}{f(d.ttm_opm, 9)}{f(d.rev_2y_stack)}"
              f"  {d.op_status_label or ''}")


def save(computed: dict[str, dict]) -> int:
    """파생 컬럼만 갱신한다. PK가 (code, fy, fq, fs_div)이므로 fs_div가 필요하다."""
    db = get_client()
    existing = select_all("quarterly_fundamentals", "code,fiscal_year,fiscal_quarter,fs_div")
    fs_div_of = {
        (r["code"], r["fiscal_year"], r["fiscal_quarter"]): r["fs_div"] for r in existing
    }

    payload: list[dict] = []
    for code, per in computed.items():
        for (year, quarter), derived in per.items():
            fs_div = fs_div_of.get((code, year, quarter))
            if fs_div is None:
                continue
            row = {
                "code": code,
                "fiscal_year": year,
                "fiscal_quarter": quarter,
                "fs_div": fs_div,
            }
            row.update({c: getattr(derived, c) for c in DERIVED_COLUMNS})
            payload.append(row)

    for i in range(0, len(payload), 500):
        db.table("quarterly_fundamentals").upsert(
            payload[i : i + 500], on_conflict="code,fiscal_year,fiscal_quarter,fs_div"
        ).execute()
    return len(payload)


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="P2.5 파생지표")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--code", default=None, help="한 종목 상세 출력")
    args = parser.parse_args()

    computed = compute_all()
    report(computed)
    if args.code:
        detail(computed, args.code)

    if args.save:
        written = save(computed)
        print(f"\n✓ quarterly_fundamentals 파생지표 갱신 {written}행")
    else:
        print("\n(--save 미지정 — DB에 기록하지 않았다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
