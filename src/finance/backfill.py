# PRD Ref: §5.1(L2), §13 (P2 검증 게이트) · traps.md T1, T2, T3
"""P2 분기 재무 백필.

    python -m src.finance.backfill --spot            # 3사 × 8분기 검증표 (게이트)
    python -m src.finance.backfill --save            # 전 종목 배치 → DB
    python -m src.finance.backfill --save --limit 50 # 상위 50종목만 (예행)
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone

from src.collectors.dart_financials import (
    FetchStats,
    collect_year,
    detect_restatement,
)
from src.config.constants import (
    DART_MULTI_ACNT_BATCH_SIZE,
    DART_MULTI_ACNT_MAX_CORP_CODES,
    DATA_START_QUARTER,
    DATA_START_YEAR,
)
from src.db.supabase_client import get_client, select_all
from src.finance.quarterize import QuarterValue
from src.utils.console import enable_utf8_stdout

# 검증 게이트 대상 (PRD §13) — 대형·연결 / 중형·코스닥 / 중소형·변동성
SPOT_COMPANIES = {
    "00126380": ("005930", "삼성전자"),
    "00369657": ("058470", "리노공업"),
    "00298340": ("039440", "에스티아이"),
}

# 수집 대상 연도는 constants.DATA_START_YEAR 하한을 따른다.


def _fmt(value: int | None, unit: float = 1e8) -> str:
    """억원 단위. None은 '—'로 (0과 구분)."""
    return "—" if value is None else f"{value / unit:,.0f}"


def _quarter_rows(
    results, corp_code: str, field: str, years: list[int]
) -> list[tuple[int, int, QuarterValue]]:
    out = []
    for year in years:
        company = results.get(year, {}).get(corp_code)
        if company is None:
            continue
        per_quarter = company.quarters.get(field, {})
        for quarter in (1, 2, 3, 4):
            qv = per_quarter.get(quarter)
            if qv is not None:
                out.append((year, quarter, qv))
    return out


def spot_check(years: list[int]) -> int:
    stats = FetchStats()
    results = {y: collect_year(list(SPOT_COMPANIES), y, stats=stats) for y in years}

    line = "═" * 78
    print(line)
    print(f"P2 검증 게이트 — 3사 × 8분기 (단위: 억원) · {date.today()}")
    print(line)
    print(f"DART 호출 {stats.calls}콜 · 레코드 {stats.records:,}건 · "
          f"status {dict(stats.status_counts)}")

    problems = 0
    for corp_code, (code, name) in SPOT_COMPANIES.items():
        fs_div = stats.fs_div_fixed.get(corp_code)
        print(f"\n■ {name} ({code}) · fs_div={fs_div}")
        print(f"  {'분기':<9}{'매출액':>14}{'영업이익':>14}{'산출근거':>18}{'단독값차이':>14}")

        revenue = dict(((y, q), v) for y, q, v in _quarter_rows(results, corp_code, "revenue", years))
        op = dict(((y, q), v) for y, q, v in _quarter_rows(results, corp_code, "op", years))

        keys = sorted(set(revenue) | set(op))[-10:]
        for year, quarter in keys:
            rv = revenue.get((year, quarter))
            ov = op.get((year, quarter))
            src = (rv.source if rv else None) or (ov.source if ov else None) or "-"
            reason = (rv.reason if rv else None) or (ov.reason if ov else None)
            mism = rv.standalone_mismatch if rv else None
            mism_txt = "0" if mism == 0 else (_fmt(mism) if mism is not None else "—")
            if mism not in (None, 0):
                problems += 1
            flag = "" if not reason else f"  ⚠{reason}"
            print(f"  {year}.{quarter}Q   {_fmt(rv.value if rv else None):>14}"
                  f"{_fmt(ov.value if ov else None):>14}{src:>18}{mism_txt:>14}{flag}")

        # ★ 교차 공시 대조 — 이것이 진짜 검증이다.
        #   "4분기 합 == 연간"은 Q4를 연간−3Q누적으로 만들었으니 항등식이라 검증이 안 된다.
        #   대신 **다음 해 보고서에 실린 전년동기 값**(frmtrm)과 대조한다.
        #   다른 공시에서 온 숫자이므로 독립 검증이고, 어긋나면 그 자체가 재작성 신호다(T3).
        for field, label in (("revenue", "매출"), ("op", "영업이익")):
            table = revenue if field == "revenue" else op
            for year in years[1:]:
                company = results.get(year, {}).get(corp_code)
                if company is None:
                    continue
                reported = company.prior_year_reported.get(field, {})
                for quarter in (1, 2, 3, 4):
                    said = reported.get(quarter)
                    if said is None:
                        continue
                    quads = [table.get((year - 1, q)) for q in range(1, quarter + 1)]
                    if not all(q is not None and q.is_measured for q in quads):
                        continue
                    mine = sum(q.value for q in quads)
                    delta = said - mine
                    mark = "✓" if delta == 0 else ("≈" if abs(delta) <= abs(mine) * 0.001 else "✗")
                    if mark == "✗":
                        problems += 1
                    if mark != "✓":
                        print(f"    {mark} {label} {year - 1}년 {quarter}Q누적 대조: "
                              f"내 계산 {_fmt(mine)}억 vs {year}년 공시 {_fmt(said)}억 "
                              f"(차이 {_fmt(delta)}억) — 재작성 가능성(T3)")
                print(f"    ✓ {label} {year - 1}년 누적 대조 완료 "
                      f"({sum(1 for q in (1,2,3,4) if reported.get(q) is not None)}개 시점)")

    print(f"\n계정 매칭 실패: {dict(stats.account_misses) or '없음'}")
    print(f"단독값 불일치 분기: {problems}건")
    print(line)
    return 0 if problems == 0 else 1


def _before_floor(year: int, quarter: int) -> bool:
    """데이터 시작 하한(constants.DATA_START_*)보다 앞선 분기인가."""
    return (year, quarter) < (DATA_START_YEAR, DATA_START_QUARTER)


def preliminary_delta(preliminary: dict | None, final: dict) -> dict | None:
    if not preliminary or preliminary.get("is_estimate") is not True:
        return None
    out: dict[str, dict] = {}
    for field in ("revenue", "op", "np"):
        before, after = preliminary.get(field), final.get(field)
        if before is None or after is None:
            continue
        item = {"preliminary": before, "final": after, "delta": after - before}
        if before > 0 and after > 0:
            item["delta_pct"] = (after - before) / before * 100
        out[field] = item
    return out or None


def _rows_for_db(
    company,
    code: str,
    year: int,
    preliminary: dict[tuple[str, int, int, str], dict] | None = None,
) -> list[dict]:
    out = []
    for quarter in (1, 2, 3, 4):
        if _before_floor(year, quarter):
            continue
        row = {
            "code": code,
            "fiscal_year": year,
            "fiscal_quarter": quarter,
            "fs_div": company.fs_div,
            "source": "dart_periodic",
            "is_estimate": False,
        }
        measured = False
        for field in ("revenue", "op", "np"):
            qv = company.quarters.get(field, {}).get(quarter)
            row[field] = qv.value if qv else None
            measured = measured or (qv is not None and qv.is_measured)
        if measured:  # 전부 결측인 분기는 저장하지 않는다
            old = (preliminary or {}).get((code, year, quarter, company.fs_div))
            delta = preliminary_delta(old, row)
            if delta:
                row["delta_from_preliminary"] = delta
            row["updated_at"] = datetime.now(timezone.utc).isoformat()
            out.append(row)
    return out


def codes_missing_revenue() -> list[str]:
    """매출이 하나라도 결측인 종목 (T39 폴백 대상).

    영업이익은 있는데 매출만 없는 회사가 있다 — 주요계정 API가 매출 계정을
    아예 반환하지 않기 때문이다. 전량 재수집은 비싸므로 이 종목들만 다시 돈다.
    """
    missing: set[str] = set()
    for row in select_all("quarterly_fundamentals", "code,revenue"):
        if row["revenue"] is None:
            missing.add(row["code"])
    return sorted(missing)


def recent_periodic_targets(days: int) -> list[dict]:
    """아직 확정 재무에 반영되지 않은 최근 정기보고서만 반환한다.

    공시 폴링은 시즌 중 하루 수십 번 돈다. 날짜만 보고 최근 3일치를 매번
    다시 모으면 같은 DART 보고서를 100회 넘게 읽게 되므로, 해당 분기의
    확정 행이 공시일 이후 갱신됐으면 완료로 본다.
    """
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    disclosures = [
        row for row in select_all(
            "earnings_disclosures",
            "code,doc_type,fiscal_year,fiscal_quarter,disclosed_at",
        )
        if row.get("doc_type") == "periodic"
        and row.get("fiscal_year") is not None
        and row.get("fiscal_quarter") is not None
        and str(row.get("disclosed_at") or "")[:10] >= cutoff
    ]
    if not disclosures:
        return []

    wanted = {
        (r["code"], r["fiscal_year"], r["fiscal_quarter"])
        for r in disclosures
    }
    refreshed: dict[tuple[str, int, int], str] = {}
    for row in select_all(
        "quarterly_fundamentals",
        "code,fiscal_year,fiscal_quarter,is_estimate,updated_at",
    ):
        key = (row["code"], row["fiscal_year"], row["fiscal_quarter"])
        if key not in wanted or row.get("is_estimate") is not False:
            continue
        updated = str(row.get("updated_at") or "")[:10]
        if updated > refreshed.get(key, ""):
            refreshed[key] = updated

    # 같은 종목·분기의 정정공시가 여러 건이면 가장 최근 공시만 비교한다.
    newest: dict[tuple[str, int, int], dict] = {}
    for row in disclosures:
        key = (row["code"], row["fiscal_year"], row["fiscal_quarter"])
        if key not in newest or str(row.get("disclosed_at") or "") > str(
            newest[key].get("disclosed_at") or ""
        ):
            newest[key] = row

    return sorted(
        (
            row for key, row in newest.items()
            if refreshed.get(key, "") < str(row.get("disclosed_at") or "")[:10]
        ),
        key=lambda row: (row["code"], row["fiscal_year"], row["fiscal_quarter"]),
    )


def codes_from_recent_periodic(days: int) -> list[str]:
    return sorted({row["code"] for row in recent_periodic_targets(days)})


def save_all(limit: int | None, years: list[int], codes: list[str] | None = None) -> int:
    universe = select_all(
        "krx_universe",
        "code,name,corp_code,is_excluded",
        order="market_cap_krw",
        desc=True,
    )
    targets = [r for r in universe if r["corp_code"] and not r["is_excluded"]]
    if codes:
        wanted = set(codes)
        targets = [r for r in targets if r["code"] in wanted]
        print(f"★ 종목 지정 모드 — 요청 {len(wanted)}종목 중 유니버스에 있는 {len(targets)}종목")
    if limit:
        targets = targets[:limit]
    by_corp = {r["corp_code"]: r["code"] for r in targets}
    corp_codes = list(by_corp)
    target_codes = set(by_corp.values())
    preliminary = {
        (r["code"], r["fiscal_year"], r["fiscal_quarter"], r["fs_div"]): r
        for r in select_all(
            "quarterly_fundamentals",
            "code,fiscal_year,fiscal_quarter,fs_div,revenue,op,np,is_estimate",
        )
        if r["code"] in target_codes and r.get("is_estimate") is True
    }

    print(f"대상 {len(corp_codes)}종목 × {len(years)}개 연도 "
          f"× 4보고서 = 예상 "
          f"{-(-len(corp_codes) // DART_MULTI_ACNT_MAX_CORP_CODES) * 4 * len(years)}콜")

    stats = FetchStats()
    db = get_client()
    written = 0
    # ★ 최신 연도부터 돌아 fs_div를 먼저 확정하고, 과거 연도에 그 기준을 강제한다 (T2).
    #   연도별로 독립 선택하면 같은 종목에 CFS/OFS가 섞여 저장된다(실측 39종목).
    for year in sorted(years, reverse=True):
        results = collect_year(
            corp_codes, year, stats=stats, fs_div_by_corp=dict(stats.fs_div_fixed)
        )
        payload: list[dict] = []
        for corp_code, company in results.items():
            code = by_corp.get(corp_code)
            if code:
                payload.extend(_rows_for_db(company, code, year, preliminary))
        for i in range(0, len(payload), 500):
            db.table("quarterly_fundamentals").upsert(
                payload[i : i + 500],
                on_conflict="code,fiscal_year,fiscal_quarter,fs_div",
            ).execute()
        written += len(payload)
        print(f"  {year}: {len(results)}사 → {len(payload)}행 저장")

    print(f"\n✓ quarterly_fundamentals upsert {written}행 "
          f"(DART {stats.calls}콜 · status {dict(stats.status_counts)})")
    print(f"  fs_div 고정: CFS {sum(1 for v in stats.fs_div_fixed.values() if v == 'CFS')} / "
          f"OFS {sum(1 for v in stats.fs_div_fixed.values() if v == 'OFS')}")
    print(f"  수집 성공 회사: {len(stats.fs_div_fixed)} / 대상 {len(corp_codes)}")
    if stats.fs_div_unavailable:
        print(f"  fs_div 불일치로 건너뛴 (회사,연도): {sum(stats.fs_div_unavailable.values())}건 "
              f"— 기준을 바꾸느니 결측으로 둔다 (T2)")

    # 이전 실행이 남긴 다른 기준의 행을 정리한다(같은 종목에 두 기준이 남으면 T2 위반).
    stale = 0
    for corp_code, fs_div in stats.fs_div_fixed.items():
        code = by_corp.get(corp_code)
        if code:
            removed = (
                db.table("quarterly_fundamentals")
                .delete()
                .eq("code", code)
                .neq("fs_div", fs_div)
                .execute()
            )
            stale += len(removed.data or [])
    print(f"  기준 불일치 행 정리: {stale}행 삭제")

    if stats.failed_batches:
        # ★ 실패한 배치의 종목은 "실적이 없는 종목"이 아니라 "못 받은 종목"이다.
        #   구분하지 않으면 게이트 판정이 조용히 틀린다.
        print(f"\n✗ 응답 파싱 실패 배치 {len(stats.failed_batches)}건 — 해당 종목은 누락됐다:")
        for year, quarter, size in stats.failed_batches:
            print(f"    {year}년 {quarter}Q · {size}종목")
        print("  재실행하면 upsert라 안전하게 메워진다.")
        return 1
    return 0


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="P2 분기 재무 백필")
    parser.add_argument("--spot", action="store_true", help="3사 검증표만 출력")
    parser.add_argument("--save", action="store_true", help="DB에 저장")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--codes", default=None,
                        help="쉼표로 구분한 종목코드만 재수집 (예: 039340,298830)")
    parser.add_argument("--fix-missing-revenue", action="store_true",
                        help="매출이 결측인 종목만 재수집 (T39 폴백)")
    parser.add_argument("--recent-periodic-days", type=int,
                        help="최근 N일 정기보고서 제출 종목만 확정 재무로 갱신")
    args = parser.parse_args()

    this_year = date.today().year
    years = list(range(DATA_START_YEAR, this_year + 1))

    codes = None
    if args.recent_periodic_days:
        periodic_targets = recent_periodic_targets(args.recent_periodic_days)
        codes = sorted({row["code"] for row in periodic_targets})
        years = sorted({row["fiscal_year"] for row in periodic_targets}, reverse=True)
        print(
            f"최근 {args.recent_periodic_days}일 미반영 정기보고서 "
            f"{len(periodic_targets)}건 · {len(codes)}종목 · 연도 {years}"
        )
        if not periodic_targets:
            return 0
    elif args.fix_missing_revenue:
        codes = codes_missing_revenue()
        print(f"매출 결측 종목 {len(codes)}개: {', '.join(codes[:12])}"
              f"{' …' if len(codes) > 12 else ''}")
    elif args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]

    if args.spot or not args.save:
        return spot_check(years)
    return save_all(args.limit, years, codes)


if __name__ == "__main__":
    raise SystemExit(main())
