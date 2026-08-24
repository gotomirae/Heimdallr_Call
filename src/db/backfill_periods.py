# PRD Ref: §5.1 · traps.md T99
"""`earnings_disclosures`·`disclosure_excerpts`의 빈 분기 칸을 공시명으로 채운다.

    python -m src.db.backfill_periods            # 실측만 (쓰지 않는다)
    python -m src.db.backfill_periods --save

★★ **왜 필요한가:** 저장 쪽이 이 두 칸을 한 번도 안 채워 1,576행 전부가 NULL이었다.
   그 값을 그대로 받아 쓴 발췌 453행도 전부 NULL이고, 읽는 쪽(`load_excerpt`)은
   분기가 안 맞으면 "가장 최근 것"으로 물러선다 — 즉 **분기가 넘어가는 순간
   지난 분기 원문이 이번 분기 분석에 조용히 실린다**(T99).

★ **이미 값이 있는 행은 건드리지 않는다.** 채우는 것이지 덮어쓰는 게 아니다.

★ 기간을 못 읽는 행(잠정실적 공시 · 12월 결산이 아닌 회사)은 **NULL로 남긴다.**
  추측해서 채우면 틀린 값이 맞는 값처럼 보인다.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict

from src.collectors.dart_disclosure import period_of
from src.db.supabase_client import get_client, select_all
from src.utils.console import enable_utf8_stdout

#: PostgREST `in.()` 필터 한 번에 넣을 키 개수. URL 길이 한계를 넘지 않게 자른다.
CHUNK = 200


def _plan(rows: list[dict], name_of: dict[str, str]) -> dict[tuple[int, int], list[str]]:
    """{(연도, 분기): [접수번호…]} — 채울 것만 모은다."""
    plan: dict[tuple[int, int], list[str]] = defaultdict(list)
    for row in rows:
        if row.get("fiscal_year") is not None and row.get("fiscal_quarter") is not None:
            continue  # 이미 채워져 있다 — 덮어쓰지 않는다
        year, quarter = period_of(name_of.get(row["rcept_no"]))
        if year is None or quarter is None:
            continue  # 못 읽으면 비운 채로 둔다
        plan[(year, quarter)].append(row["rcept_no"])
    return plan


def _apply(table: str, plan: dict[tuple[int, int], list[str]], *, save: bool) -> int:
    db = get_client()
    written = 0
    for (year, quarter), keys in sorted(plan.items()):
        print(f"    {table:22} {year}Q{quarter}  {len(keys):>5}행")
        if not save:
            continue
        for i in range(0, len(keys), CHUNK):
            (db.table(table)
               .update({"fiscal_year": year, "fiscal_quarter": quarter})
               .in_("rcept_no", keys[i : i + CHUNK])
               .execute())
        written += len(keys)
    return written


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true", help="실제로 쓴다")
    args = parser.parse_args()

    disclosures = select_all(
        "earnings_disclosures", "rcept_no,report_nm,fiscal_year,fiscal_quarter"
    )
    name_of = {d["rcept_no"]: d.get("report_nm") or "" for d in disclosures}
    excerpts = select_all(
        "disclosure_excerpts", "rcept_no,code,fiscal_year,fiscal_quarter"
    )

    print(f"\n[1] earnings_disclosures {len(disclosures)}행")
    empty = sum(1 for d in disclosures if d.get("fiscal_year") is None)
    print(f"    분기 칸이 빈 행 {empty}행")
    disc_plan = _plan(disclosures, name_of)
    disc_fill = sum(len(v) for v in disc_plan.values())
    print(f"    이름에서 기간을 읽어낸 행 {disc_fill}행")

    # ★ 못 읽은 행이 왜 못 읽혔는지 밝힌다 — 조용히 넘어가면 파서 결함을 못 본다.
    unreadable = [d for d in disclosures
                  if d.get("fiscal_year") is None
                  and period_of(d.get("report_nm"))[0] is None]
    kinds = Counter(
        "잠정·손익변동(이름에 기간 없음)"
        if "보고서" not in (d.get("report_nm") or "")
        else "정기보고서인데 12월 결산이 아니다"
        for d in unreadable
    )
    print(f"    읽지 못해 NULL로 남기는 행 {len(unreadable)}행")
    for kind, n in kinds.most_common():
        print(f"      - {kind}: {n}행")

    print(f"\n[2] disclosure_excerpts {len(excerpts)}행")
    empty_ex = sum(1 for e in excerpts if e.get("fiscal_year") is None)
    print(f"    분기 칸이 빈 행 {empty_ex}행")
    ex_plan = _plan(excerpts, name_of)
    ex_fill = sum(len(v) for v in ex_plan.values())
    print(f"    채울 수 있는 행 {ex_fill}행")

    print(f"\n[3] {'쓴다' if args.save else '실측만 — 쓰지 않는다 (--save로 실행하라)'}")
    _apply("earnings_disclosures", disc_plan, save=args.save)
    _apply("disclosure_excerpts", ex_plan, save=args.save)

    if args.save:
        print(f"\n✓ earnings_disclosures {disc_fill}행 · "
              f"disclosure_excerpts {ex_fill}행 채웠다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
