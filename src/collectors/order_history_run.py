# PRD Ref: §9.1-3 · §10 — 수주 분기 그래프용 과거 정기보고서 목록 발견
"""OpenDART 회사별 목록에서 최근 정기보고서 10개를 점진적으로 장부에 보강한다.

최근 7일 공시 폴링만으로는 종목당 정기보고서가 한 건뿐이라 분기 그래프가 한 점에서
멈춘다. 회사별 `list.json`은 작은 응답이므로 하루 일부 종목만 조회하고, 실제 대용량
원문은 ``excerpt_run``의 별도 시간 예산에서 받는다.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.collectors.dart_disclosure import DOC_PERIODIC, LIST_URL, classify, period_of
from src.config.constants import ORDER_HISTORY_DISCOVERY_CODES_PER_RUN, ORDER_HISTORY_QUARTERS
from src.db.supabase_client import get_client, select_all
from src.utils.console import enable_utf8_stdout
from src.utils.env import require_env
from src.utils.http import http_get


def expected_reports(listed_at: str | None, today: date) -> int:
    """상장 이력보다 많은 보고서를 요구해 신규 상장사를 매일 재조회하지 않는다."""
    if not listed_at:
        return ORDER_HISTORY_QUARTERS
    try:
        listed = date.fromisoformat(listed_at[:10])
    except ValueError:
        return ORDER_HISTORY_QUARTERS
    elapsed_quarters = max(1, ((today.year - listed.year) * 12 + today.month - listed.month) // 3)
    return min(ORDER_HISTORY_QUARTERS, elapsed_quarters)


def discovery_targets(limit: int, today: date, codes: list[str] | None = None) -> list[dict]:
    universe = [row for row in select_all(
        "krx_universe", "code,name,corp_code,listed_at,is_excluded"
    ) if row.get("corp_code") and not row.get("is_excluded")]
    disclosures = [row for row in select_all(
        "earnings_disclosures", "code,doc_type,fiscal_year,fiscal_quarter"
    ) if row.get("doc_type") == DOC_PERIODIC and row.get("fiscal_year") and row.get("fiscal_quarter")]
    counts = Counter((row["code"], row["fiscal_year"], row["fiscal_quarter"]) for row in disclosures)
    period_counts = Counter(code for code, _year, _quarter in counts)

    # 매력도 순서를 재사용해 수집이 진행 중이어도 투자판단 우선 종목부터 다분기화한다.
    from src.collectors.excerpt_run import attractiveness_rank
    rank = attractiveness_rank()
    wanted = set(codes or [])
    missing = [row for row in universe
               if (not wanted or row["code"] in wanted)
               and period_counts[row["code"]] < expected_reports(row.get("listed_at"), today)]
    return sorted(missing, key=lambda row: -(rank.get(row["code"], float("-inf"))))[:limit]


def fetch_periodic_history(row: dict, today: date) -> list[dict]:
    begin_year = today.year - 3
    response = http_get(LIST_URL, params={
        "crtfc_key": require_env("OPENDART_API_KEY"),
        "corp_code": row["corp_code"],
        "bgn_de": f"{begin_year}0101",
        "end_de": today.strftime("%Y%m%d"),
        "pblntf_ty": "A",
        "page_count": 100,
    }, timeout=90.0)
    body = response.json()
    if body.get("status") == "013":
        return []
    if body.get("status") != "000":
        raise RuntimeError(f"OpenDART 목록 오류 {body.get('status')}: {body.get('message')}")
    found: list[dict] = []
    for item in body.get("list") or []:
        doc_type, dropped = classify(str(item.get("report_nm") or ""))
        year, quarter = period_of(str(item.get("report_nm") or ""))
        if dropped or doc_type != DOC_PERIODIC or year is None or quarter is None:
            continue
        # SC: 요청한 DART 회사와 종목코드가 다르면 조용히 다른 회사 자료를 넣지 않는다.
        stock_code = str(item.get("stock_code") or "").strip()
        if stock_code and stock_code != row["code"]:
            continue
        disclosed = str(item.get("rcept_dt") or "")
        found.append({
            "rcept_no": item["rcept_no"], "code": row["code"], "corp_code": row["corp_code"],
            "report_nm": str(item.get("report_nm") or "").strip(), "doc_type": DOC_PERIODIC,
            "fiscal_year": year, "fiscal_quarter": quarter,
            "disclosed_at": f"{disclosed[:4]}-{disclosed[4:6]}-{disclosed[6:8]}" if len(disclosed) == 8 else None,
        })
    # 정정본을 포함해 받아 두되 실제 원문 수집기는 분기별 최신 접수번호만 고른다.
    return sorted(found, key=lambda item: item["rcept_no"], reverse=True)[:ORDER_HISTORY_QUARTERS * 2]


def run(*, limit: int, save: bool, today: date | None = None, codes: list[str] | None = None) -> int:
    today = today or datetime.now(ZoneInfo("Asia/Seoul")).date()
    targets = discovery_targets(limit, today, codes)
    print(f"과거 정기보고서 목록 발견 대상 {len(targets)}종목")
    db = get_client() if save else None
    discovered = failed = 0
    for row in targets:
        try:
            filings = fetch_periodic_history(row, today)
        except (RuntimeError, OSError) as exc:
            print(f"  ✗ {row['code']} {row['name']} — {exc}")
            failed += 1
            continue
        if db and filings:
            db.table("earnings_disclosures").upsert(filings, on_conflict="rcept_no").execute()
        discovered += len(filings)
        print(f"  ✓ {row['code']} {row['name']} — 정기보고서 {len(filings)}건" + ("" if save else " · DB 쓰기 0건"))
    print(f"목록 발견 {discovered}건 · 실패 {failed}종목")
    return 0 if failed == 0 else 1


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="수주 그래프용 과거 정기보고서 목록 발견")
    parser.add_argument("--limit", type=int, default=ORDER_HISTORY_DISCOVERY_CODES_PER_RUN)
    parser.add_argument("--codes", help="쉼표로 구분한 종목코드(운영 복구·검증용)")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    codes = [code.strip() for code in args.codes.split(",") if code.strip()] if args.codes else None
    return run(limit=args.limit, save=args.save, codes=codes)


if __name__ == "__main__":
    raise SystemExit(main())
