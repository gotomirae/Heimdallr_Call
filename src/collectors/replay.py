# PRD Ref: §5.1(L1, L2'), §13 (P4 검증) · traps.md T11, T27
"""P4 replay 검증 — 과거 구간을 재생해 감지·파싱 품질을 잰다.

    python -m src.collectors.replay                       # 2Q 시즌 구간
    python -m src.collectors.replay --begin 20260715 --end 20260813
    python -m src.collectors.replay --parse 40            # 잠정실적 40건 실제 파싱
    python -m src.collectors.replay --save                # earnings_disclosures 저장
"""

from __future__ import annotations

import argparse
import collections
import time

from src.collectors.dart_disclosure import (
    DOC_PERIODIC,
    DOC_PL_CHANGE,
    DOC_PROVISIONAL,
    PollStats,
    period_of,
    poll,
)
from src.collectors.provisional_parser import (
    fetch_document_html,
    parse_provisional,
    to_db_row,
)
from src.db.supabase_client import get_client, select_all
from src.utils.console import enable_utf8_stdout

PARSE_INTERVAL_SEC = 0.4  # DART 웹 뷰어 배려


def load_universe() -> dict[str, dict]:
    return {
        u["code"]: u
        for u in select_all("krx_universe", "code,name,is_excluded,exclude_reason")
    }


def replay(begin: str, end: str, parse_limit: int, save: bool) -> int:
    universe = load_universe()
    stats = PollStats()
    found = poll(begin, end, universe=universe, stats=stats)

    line = "═" * 74
    print(line)
    print(f"P4 replay — {begin} ~ {end}")
    print(line)

    print("\n[1] 감지 결과")
    print(f"    DART 호출 {stats.calls}콜 · 훑은 공시 {stats.scanned:,}건")
    print(f"    실적 공시로 분류 {stats.matched}건")
    for doc_type, label in (
        (DOC_PROVISIONAL, "provisional 잠정실적"),
        (DOC_PL_CHANGE, "pl_change 손익구조변경"),
        (DOC_PERIODIC, "periodic 정기보고서"),
    ):
        print(f"      {label:24} {stats.by_type.get(doc_type, 0):>5}건")
    print(f"    정정공시 포함 {stats.corrections}건")

    print("\n[2] 분류에서 걸러낸 것 (오탐 방지)")
    print(f"    자회사 실적 공시      {stats.dropped_subsidiary:>5}건  ← 모회사 실적으로 둔갑 방지")
    print(f"    실적 '전망' 공시      {stats.dropped_forecast:>5}건  ← 확정치가 아니다")
    print(f"    유니버스 밖 종목      {stats.dropped_not_in_universe:>5}건")
    print(f"    업종 제외 종목        {stats.dropped_excluded:>5}건")

    print("\n[3] 오탐 점검 — 분류된 공시명 전수")
    names = collections.Counter(d.report_nm for d in found)
    suspicious = [
        (n, c) for n, c in names.items()
        if "영업(잠정)실적" not in n
        and "매출액또는손익구조" not in n
        and not any(t in n for t in ("분기보고서", "반기보고서", "사업보고서"))
    ]
    print(f"    고유 공시명 {len(names)}종")
    for name, count in names.most_common(12):
        print(f"      {count:>4}  {name[:58]}")
    print(f"    ★ 규칙 밖 이름 {len(suspicious)}종 "
          f"{'✓ 오탐 0%' if not suspicious else '✗ 확인 필요: ' + str(suspicious[:3])}")

    if parse_limit:
        _parse_sample(found, parse_limit)

    if save:
        return _save(found)
    print("\n(--save 미지정 — DB에 기록하지 않았다)")
    return 0


def _parse_sample(found: list, limit: int) -> None:
    targets = [d for d in found if d.doc_type == DOC_PROVISIONAL][:limit]
    print(f"\n[4] 잠정실적 규칙 파서 — {len(targets)}건 실제 파싱")

    ok = 0
    failures: collections.Counter = collections.Counter()
    units: collections.Counter = collections.Counter()
    fs_divs: collections.Counter = collections.Counter()
    skipped_items = 0
    not_quarterly = 0
    samples = []

    for disclosure in targets:
        try:
            html = fetch_document_html(disclosure.rcept_no)
        except Exception as exc:
            failures[f"fetch_error:{type(exc).__name__}"] += 1
            time.sleep(PARSE_INTERVAL_SEC)
            continue
        if html is None:
            failures["no_document"] += 1
            time.sleep(PARSE_INTERVAL_SEC)
            continue

        result = parse_provisional(
            html, disclosure.rcept_no, disclosed_at=disclosure.disclosed_at
        )
        units[result.unit or "미확인"] += 1
        fs_divs[result.fs_div or "미확인"] += 1
        if result.skipped:
            skipped_items += len(result.skipped)
        if result.period_warning and result.period_warning.startswith("not_quarterly"):
            # 월별 실적 공시 — 파싱 실패가 아니라 '분기 실적이 아님'이다.
            # LLM을 불러도 여전히 월별이므로 폴백 대상도 아니다.
            not_quarterly += 1
            time.sleep(PARSE_INTERVAL_SEC)
            continue
        if result.ok:
            ok += 1
            if len(samples) < 5:
                samples.append((disclosure, result))
        else:
            failures[result.failure or "unknown"] += 1
        time.sleep(PARSE_INTERVAL_SEC)

    total = len(targets)
    quarterly = total - not_quarterly
    print(f"    대상 {total}건 = 분기 실적 {quarterly} + 월별 실적 {not_quarterly}")
    print(f"    ★ 월별 실적 공시 {not_quarterly}건 제외 (T28) — 같은 공시명이지만 기간이 1개월이다.")
    print("      분기 칸에 넣으면 매출이 1/3로 들어가 '가짜 급감'이 된다.")
    if quarterly:
        print(f"    규칙 파서 성공 {ok}/{quarterly} ({ok / quarterly * 100:.1f}%)")
    print(f"    실패 사유: {dict(failures) or '없음'}")
    print(f"    단위 분포: {dict(units)}")
    print(f"    연결/별도: {dict(fs_divs)}")
    print(f"    ★ 단위 미확인으로 건너뛴 항목 {skipped_items}개 "
          f"— 추측해서 곱하지 않았다 (T11)")
    print(f"    Haiku 폴백 필요 건수: {sum(failures.values())} "
          f"(이번 실행에서는 호출하지 않았다 — 비용 승인 전)")

    if samples:
        print("\n    파싱 성공 샘플 (억원)")
        print(f"      {'종목':>14} {'분기':>8}{'매출':>12}{'영업이익':>12}{'순이익':>12}  단위/기준")
        for d, r in samples:
            f = lambda v: f"{v / 1e8:>12,.0f}" if v is not None else f"{'—':>12}"
            print(f"      {d.corp_name[:12]:>14} {r.fiscal_year}.{r.fiscal_quarter}Q"
                  f"{f(r.revenue)}{f(r.op)}{f(r.np)}  {r.unit}/{r.fs_div}")


def _save(found: list) -> int:
    db = get_client()
    payload = [
        {
            "rcept_no": d.rcept_no,
            "code": d.code,
            "corp_code": d.corp_code,
            "report_nm": d.report_nm,
            "doc_type": d.doc_type,
            "disclosed_at": f"{d.disclosed_at[:4]}-{d.disclosed_at[4:6]}-{d.disclosed_at[6:]}",
            # ★★ 이 두 칸을 안 채우면 발췌가 **어느 분기 것인지 모르는 채로** 저장되고,
            #   읽는 쪽이 "가장 최근 것"으로 물러서 **남의 분기 원문을 LLM에 싣는다**(T99).
            #   잠정실적 공시는 이름에 기간이 없어 None이 정상이다.
            **dict(zip(("fiscal_year", "fiscal_quarter"), period_of(d.report_nm))),
        }
        for d in found
    ]
    for i in range(0, len(payload), 500):
        db.table("earnings_disclosures").upsert(
            payload[i : i + 500], on_conflict="rcept_no"
        ).execute()
    print(f"\n✓ earnings_disclosures upsert {len(payload)}행 (rcept_no 멱등)")
    return 0


def ingest_provisionals(begin: str, end: str, limit: int) -> int:
    """잠정실적을 `quarterly_fundamentals`에 `is_estimate=True`로 반영한다.

    ★ 같은 종목·분기에 공시가 여러 건이면 **나중 것이 이긴다**(정정·상세 공시).
      실측: 삼성전자 2026.2Q는 7/7(조원 단위, 개략)과 7/30(억원, 상세) 두 건이다.
    ★ fs_div가 기존 저장값과 다르면 **건너뛴다** — 기준을 섞으면 YoY가 조작된 것처럼
      보인다(T2). 잠정치가 별도(OFS)인데 확정 이력이 연결(CFS)인 경우가 그렇다.
    """
    universe = load_universe()
    found = poll(begin, end, universe=universe, stats=PollStats())
    completed = {r["rcept_no"] for r in select_all("earnings_disclosures", "rcept_no,processed") if r.get("processed") is True}
    targets = [d for d in found if d.doc_type == DOC_PROVISIONAL and d.rcept_no not in completed][:limit]

    existing_fs = {}
    finalized = set()
    for row in select_all("quarterly_fundamentals", "code,fs_div,fiscal_year,fiscal_quarter,is_estimate"):
        existing_fs.setdefault(row["code"], row["fs_div"])
        if row.get("is_estimate") is False:
            finalized.add((row["code"], row["fiscal_year"], row["fiscal_quarter"], row["fs_div"]))

    print(f"잠정실적 {len(targets)}건 파싱 → quarterly_fundamentals 반영")
    rows: dict[tuple, dict] = {}
    stats = collections.Counter()
    processed = []
    for d in sorted(targets, key=lambda x: x.disclosed_at):  # 나중 공시가 이긴다
        try:
            html = fetch_document_html(d.rcept_no)
        except Exception:
            stats["fetch_error"] += 1
            time.sleep(PARSE_INTERVAL_SEC)
            continue
        if html is None:
            stats["no_document"] += 1
            time.sleep(PARSE_INTERVAL_SEC)
            continue
        result = parse_provisional(html, d.rcept_no, disclosed_at=d.disclosed_at)
        row = to_db_row(result, d.code, disclosed_at=d.disclosed_at)
        if row is None:
            stats[result.failure or "parse_failed"] += 1
            time.sleep(PARSE_INTERVAL_SEC)
            continue
        prior = existing_fs.get(d.code)
        if prior and prior != row["fs_div"]:
            # 기준이 다르면 섞지 않는다 (T2)
            stats[f"fs_div_mismatch({prior}≠{row['fs_div']})"] += 1
            time.sleep(PARSE_INTERVAL_SEC)
            continue
        key = (row["code"], row["fiscal_year"], row["fiscal_quarter"], row["fs_div"])
        if key in finalized:
            stats["already_final"] += 1
            processed.append(d.rcept_no)
            continue
        rows[key] = row
        processed.append(d.rcept_no)
        stats["ok"] += 1
        time.sleep(PARSE_INTERVAL_SEC)

    payload = list(rows.values())
    db = get_client()
    for i in range(0, len(payload), 500):
        db.table("quarterly_fundamentals").upsert(
            payload[i : i + 500],
            on_conflict="code,fiscal_year,fiscal_quarter,fs_div",
        ).execute()

    for receipt in processed:
        db.table("earnings_disclosures").update({"processed": True}).eq("rcept_no", receipt).execute()

    print(f"\n✓ quarterly_fundamentals upsert {len(payload)}행 (is_estimate=true)")
    print(f"  결과: {dict(stats)}")
    quarters = collections.Counter((r["fiscal_year"], r["fiscal_quarter"]) for r in payload)
    print(f"  분기 분포: {dict(quarters)}")
    return 0


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="P4 공시 감지 replay")
    parser.add_argument("--begin", default="20260715")
    parser.add_argument("--end", default="20260813")
    parser.add_argument("--parse", type=int, default=0, help="잠정실적 N건 실제 파싱")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--ingest", type=int, default=0,
                        help="잠정실적 N건을 파싱해 quarterly_fundamentals에 반영")
    args = parser.parse_args()
    if args.ingest:
        return ingest_provisionals(args.begin, args.end, args.ingest)
    return replay(args.begin, args.end, args.parse, args.save)


if __name__ == "__main__":
    raise SystemExit(main())
