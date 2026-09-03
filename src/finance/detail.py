# PRD Ref: §4.1(D), §5.1(L2″), §5.3 · traps.md T1, T2, T7, T11
"""게이트 통과 종목만 수집하는 OpenDART 정밀 재무.

전체 재무제표의 CF 행은 주요계정 API와 필드 의미가 다르다. 중간보고서의
``thstrm_amount``는 누적, ``frmtrm_q_amount``는 전년 동기 누적이다. 이 규칙으로
TTM CFO와 분기 단독 CFO를 각각 계산하고, BS·발행주식수의 전년 동기 값도 함께 저장한다.

    python -m src.finance.detail --save
    python -m src.finance.detail --code 005930 --save
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.collectors.dart_financials import REQUEST_INTERVAL_SEC, _to_int, fetch_single_all
from src.config.constants import DART_BASE_URL, REPRT_CODE
from src.db.supabase_client import get_client, select_all
from src.utils.console import enable_utf8_stdout
from src.utils.env import require_env
from src.utils.http import http_get

STOCK_TOTAL_URL = f"{DART_BASE_URL}/stockTotqySttus.json"


@dataclass(frozen=True)
class FlowFigure:
    current_cumulative: int | None = None
    prior_same_cumulative: int | None = None


@dataclass(frozen=True)
class DetailedAccounts:
    cfo: FlowFigure = FlowFigure()
    capex: FlowFigure = FlowFigure()
    receivables: int | None = None
    inventory: int | None = None
    equity: int | None = None
    assets: int | None = None
    liabilities: int | None = None


@dataclass(frozen=True)
class DetailTarget:
    code: str
    name: str
    corp_code: str
    fiscal_year: int
    fiscal_quarter: int
    fs_div: str


@dataclass
class DetailStats:
    account_calls: int = 0
    stock_calls: int = 0
    stock_status: dict[str, int] = field(default_factory=dict)
    current_report_missing: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


_ACCOUNT_IDS: dict[str, tuple[str, ...]] = {
    "cfo": (
        "ifrs-full_CashFlowsFromUsedInOperatingActivities",
        "ifrs_CashFlowsFromUsedInOperatingActivities",
        "dart_CashFlowsFromUsedInOperatingActivities",
    ),
    "receivables": (
        "ifrs-full_CurrentTradeReceivables",
        "ifrs-full_TradeAndOtherCurrentReceivables",
        "ifrs_TradeAndOtherCurrentReceivables",
        "ifrs-full_TradeReceivables",
        "dart_ShortTermTradeReceivable",
    ),
    "inventory": ("ifrs-full_Inventories", "ifrs_Inventories"),
    "assets": ("ifrs-full_Assets", "ifrs_Assets"),
    "liabilities": ("ifrs-full_Liabilities", "ifrs_Liabilities"),
    "equity": ("ifrs-full_Equity", "ifrs_Equity"),
    "capex_ppe": (
        "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        "ifrs_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        "dart_PurchaseOfPropertyPlantAndEquipment",
    ),
    "capex_intangible": (
        "ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
        "ifrs_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
        "dart_PurchaseOfIntangibleAssets",
    ),
}

_ACCOUNT_NAMES: dict[str, tuple[str, ...]] = {
    "cfo": ("영업활동현금흐름", "영업활동으로 인한 현금흐름"),
    "receivables": (
        "매출채권",
        "매출채권및기타채권",
        "매출채권 및 기타채권",
        "유동매출채권 등",
    ),
    "inventory": ("재고자산",),
    "assets": ("자산총계",),
    "liabilities": ("부채총계",),
    "equity": ("자본총계",),
    "capex_ppe": ("유형자산의 취득", "유형자산 취득"),
    "capex_intangible": ("무형자산의 취득", "무형자산 취득"),
}


def cumulative_value(value: object) -> int | None:
    """DART 숫자를 추측 없이 정수로 바꾼다. 0과 결측은 구분한다."""
    return _to_int(None if value is None else str(value))


def _pick_row(rows: list[dict], field_name: str, sj_div: str) -> dict | None:
    def order_of(row: dict) -> int:
        try:
            return int(str(row.get("ord") or "999999"))
        except ValueError:
            return 999999

    candidates = [row for row in rows if row.get("sj_div") == sj_div]
    for account_id in _ACCOUNT_IDS[field_name]:
        matches = [row for row in candidates if row.get("account_id") == account_id]
        if matches:
            return min(
                matches,
                key=lambda row: (str(row.get("account_detail") or "-") not in ("", "-"),
                                 order_of(row)),
            )
    for account_name in _ACCOUNT_NAMES[field_name]:
        normalized = account_name.replace(" ", "")
        matches = [
            row for row in candidates
            if str(row.get("account_nm") or "").replace(" ", "") == normalized
        ]
        if matches:
            return matches[0]
    return None


def _flow_of(row: dict | None, *, expenditure: bool = False) -> FlowFigure:
    if row is None:
        return FlowFigure()
    current = cumulative_value(row.get("thstrm_amount"))
    prior = cumulative_value(row.get("frmtrm_q_amount"))
    if expenditure:
        current = abs(current) if current is not None else None
        prior = abs(prior) if prior is not None else None
    return FlowFigure(current, prior)


def _sum_optional(values: list[int | None]) -> int | None:
    measured = [value for value in values if value is not None]
    return sum(measured) if measured else None


def extract_accounts(rows: list[dict]) -> DetailedAccounts:
    """전체 재무제표 응답에서 D축과 화면용 계정을 추출한다."""
    cfo = _flow_of(_pick_row(rows, "cfo", "CF"))
    capex_parts = [
        _flow_of(_pick_row(rows, "capex_ppe", "CF"), expenditure=True),
        _flow_of(_pick_row(rows, "capex_intangible", "CF"), expenditure=True),
    ]
    capex = FlowFigure(
        _sum_optional([part.current_cumulative for part in capex_parts]),
        _sum_optional([part.prior_same_cumulative for part in capex_parts]),
    )

    def balance(field_name: str) -> int | None:
        row = _pick_row(rows, field_name, "BS")
        return cumulative_value(row.get("thstrm_amount")) if row else None

    return DetailedAccounts(
        cfo=cfo,
        capex=capex,
        receivables=balance("receivables"),
        inventory=balance("inventory"),
        equity=balance("equity"),
        assets=balance("assets"),
        liabilities=balance("liabilities"),
    )


def standalone_value(quarter: int, current: int | None, previous: int | None) -> int | None:
    """누적 현금흐름을 분기 단독값으로 바꾼다."""
    if current is None:
        return None
    if quarter == 1:
        return current
    if previous is None:
        return None
    return current - previous


def ttm_value(
    quarter: int,
    current: int | None,
    prior_same: int | None,
    prior_annual: int | None,
) -> int | None:
    """중간 누적 + 전년 연간 - 전년 동기 누적으로 TTM을 계산한다."""
    if current is None:
        return None
    if quarter == 4:
        return current
    if prior_same is None or prior_annual is None:
        return None
    return current + prior_annual - prior_same


def select_total_shares(rows: list[dict]) -> int | None:
    """주식 종류별 행 중 합계 발행주식수를 고른다."""
    for row in rows:
        if str(row.get("se") or "").replace(" ", "") == "합계":
            return cumulative_value(row.get("istc_totqy"))
    values = [cumulative_value(row.get("istc_totqy")) for row in rows]
    measured = [value for value in values if value is not None]
    return max(measured) if measured else None


def shares_yoy(current: int | None, previous: int | None) -> float | None:
    if current is None or previous is None or previous <= 0:
        return None
    return (current / previous - 1) * 100


def _latest_gate_targets(
    codes: set[str] | None = None, *, refresh: bool = False
) -> list[DetailTarget]:
    latest: dict[str, dict] = {}
    for row in select_all(
        "screen_results", "code,fiscal_year,fiscal_quarter,gate_passed"
    ):
        key = (row["fiscal_year"], row["fiscal_quarter"])
        previous = latest.get(row["code"])
        if previous is None or key > (previous["fiscal_year"], previous["fiscal_quarter"]):
            latest[row["code"]] = row

    universe = {
        row["code"]: row
        for row in select_all("krx_universe", "code,name,corp_code,is_excluded")
    }
    fundamentals: dict[tuple[str, int, int], dict] = {}
    for row in select_all(
        "quarterly_fundamentals",
        "code,fiscal_year,fiscal_quarter,fs_div,is_estimate,"
        "ttm_cfo,receivables,inventory,shares_yoy",
    ):
        if row.get("is_estimate") is False:
            fundamentals[(row["code"], row["fiscal_year"], row["fiscal_quarter"])] = row

    targets: list[DetailTarget] = []
    for code, screened in latest.items():
        if codes is not None and code not in codes:
            continue
        if screened.get("gate_passed") is not True:
            continue
        uni = universe.get(code)
        key = (code, screened["fiscal_year"], screened["fiscal_quarter"])
        fund = fundamentals.get(key)
        if not uni or uni.get("is_excluded") or not uni.get("corp_code") or not fund:
            continue
        prior = fundamentals.get((code, screened["fiscal_year"] - 1, screened["fiscal_quarter"]))
        detail_complete = (
            fund.get("ttm_cfo") is not None
            and fund.get("shares_yoy") is not None
            and fund.get("receivables") is not None
            and prior is not None
            and prior.get("receivables") is not None
        )
        if detail_complete and not refresh:
            continue
        targets.append(
            DetailTarget(
                code=code,
                name=uni["name"],
                corp_code=uni["corp_code"],
                fiscal_year=screened["fiscal_year"],
                fiscal_quarter=screened["fiscal_quarter"],
                fs_div=fund["fs_div"],
            )
        )
    return sorted(targets, key=lambda target: target.code)


def _fetch_stock_rows(target: DetailTarget, year: int, quarter: int, stats: DetailStats) -> list[dict]:
    response = http_get(
        STOCK_TOTAL_URL,
        params={
            "crtfc_key": require_env("OPENDART_API_KEY"),
            "corp_code": target.corp_code,
            "bsns_year": str(year),
            "reprt_code": REPRT_CODE[quarter],
        },
        timeout=90.0,
    )
    stats.stock_calls += 1
    if "json" not in (response.headers.get("content-type") or ""):
        stats.stock_status["non_json"] = stats.stock_status.get("non_json", 0) + 1
        return []
    try:
        body = response.json()
    except ValueError:
        stats.stock_status["invalid_json"] = stats.stock_status.get("invalid_json", 0) + 1
        return []
    status = str(body.get("status") or "unknown")
    stats.stock_status[status] = stats.stock_status.get(status, 0) + 1
    return (body.get("list") or []) if status == "000" else []


def _previous_report(quarter: int) -> int | None:
    return quarter - 1 if quarter > 1 else None


def collect_target(
    target: DetailTarget,
    account_cache: dict[tuple[str, int, int, str], list[dict]],
    stock_cache: dict[tuple[str, int, int], list[dict]],
    stats: DetailStats,
) -> list[dict]:
    """한 종목의 현재행과 전년 동기행에 필요한 정밀 값을 만든다."""

    def accounts(year: int, quarter: int) -> list[dict]:
        key = (target.corp_code, year, quarter, target.fs_div)
        if key not in account_cache:
            account_cache[key] = fetch_single_all(
                target.corp_code, year, quarter, target.fs_div
            )
            stats.account_calls += 1
            time.sleep(REQUEST_INTERVAL_SEC)
        return account_cache[key]

    def stocks(year: int, quarter: int) -> list[dict]:
        key = (target.corp_code, year, quarter)
        if key not in stock_cache:
            stock_cache[key] = _fetch_stock_rows(target, year, quarter, stats)
            time.sleep(REQUEST_INTERVAL_SEC)
        return stock_cache[key]

    year, quarter = target.fiscal_year, target.fiscal_quarter
    current_rows = accounts(year, quarter)
    if not current_rows:
        stats.current_report_missing.append(target.code)
        return []

    current = extract_accounts(current_rows)
    previous_quarter = _previous_report(quarter)
    previous = (
        extract_accounts(accounts(year, previous_quarter))
        if previous_quarter is not None
        else DetailedAccounts()
    )
    prior_same = extract_accounts(accounts(year - 1, quarter))
    prior_annual = prior_same if quarter == 4 else extract_accounts(accounts(year - 1, 4))

    cfo = standalone_value(
        quarter, current.cfo.current_cumulative, previous.cfo.current_cumulative
    )
    capex = standalone_value(
        quarter, current.capex.current_cumulative, previous.capex.current_cumulative
    )
    ttm_cfo = ttm_value(
        quarter,
        current.cfo.current_cumulative,
        current.cfo.prior_same_cumulative
        if current.cfo.prior_same_cumulative is not None
        else prior_same.cfo.current_cumulative,
        prior_annual.cfo.current_cumulative,
    )
    current_shares = select_total_shares(stocks(year, quarter))
    prior_shares = select_total_shares(stocks(year - 1, quarter))
    stamp = datetime.now(timezone.utc).isoformat()

    current_payload = {
        "code": target.code,
        "fiscal_year": year,
        "fiscal_quarter": quarter,
        "fs_div": target.fs_div,
        "ttm_cfo": ttm_cfo,
        "cfo": cfo,
        "capex": capex,
        "fcf": cfo - capex if cfo is not None and capex is not None else None,
        "receivables": current.receivables,
        "inventory": current.inventory,
        "equity": current.equity,
        "assets": current.assets,
        "liabilities": current.liabilities,
        "shares_outstanding": current_shares,
        "shares_yoy": shares_yoy(current_shares, prior_shares),
        "updated_at": stamp,
    }
    prior_payload = {
        "code": target.code,
        "fiscal_year": year - 1,
        "fiscal_quarter": quarter,
        "fs_div": target.fs_div,
        "receivables": prior_same.receivables,
        "inventory": prior_same.inventory,
        "shares_outstanding": prior_shares,
        "updated_at": stamp,
    }
    return [current_payload, prior_payload]


def run(
    *,
    save: bool,
    codes: set[str] | None = None,
    limit: int | None = None,
    refresh: bool = False,
) -> int:
    targets = _latest_gate_targets(codes, refresh=refresh)
    if limit is not None:
        targets = targets[:limit]
    print(f"L2″ 정밀 재무 — 최신 게이트 통과 확정종목 {len(targets)}개")

    stats = DetailStats()
    account_cache: dict[tuple[str, int, int, str], list[dict]] = {}
    stock_cache: dict[tuple[str, int, int], list[dict]] = {}
    payload: list[dict] = []
    for index, target in enumerate(targets, start=1):
        try:
            payload.extend(collect_target(target, account_cache, stock_cache, stats))
        except Exception as exc:  # 한 회사 장애가 나머지 274개를 막지 않되 반드시 밝힌다.
            stats.errors.append(f"{target.code}: {type(exc).__name__}: {exc}")
        if index % 5 == 0 or index == len(targets):
            print(f"  {index}/{len(targets)}종목 · 전체재무 {stats.account_calls}콜 · 주식수 {stats.stock_calls}콜")

    current_year = {target.code: target.fiscal_year for target in targets}
    current_rows = [
        row for row in payload if row["fiscal_year"] == current_year.get(row["code"])
    ]
    for field_name in ("ttm_cfo", "receivables", "inventory", "shares_yoy", "cfo", "fcf"):
        measured = sum(row.get(field_name) is not None for row in current_rows)
        print(f"  {field_name:18} {measured}/{len(targets)}종목 측정")
    print(f"  주식수 API status: {stats.stock_status}")
    if stats.current_report_missing:
        print(f"  ⚠ 현재 전체재무 응답 없음 {len(stats.current_report_missing)}종목: "
              f"{','.join(stats.current_report_missing[:20])}")
    if stats.errors:
        print(f"  ✗ 예외 {len(stats.errors)}건")
        for error in stats.errors[:20]:
            print(f"    {error}")

    if save and payload:
        written, _ = _save(payload)
        print(f"\n✓ quarterly_fundamentals 정밀 재무 upsert {written}행")
    else:
        print("\n(--save 미지정 — DB에 기록하지 않았다)" if not save else "\n저장할 행 없음")
    return 1 if stats.errors else 0


def _save(payload: list[dict]) -> tuple[int, int]:
    db = get_client()
    for index in range(0, len(payload), 500):
        db.table("quarterly_fundamentals").upsert(
            payload[index : index + 500],
            on_conflict="code,fiscal_year,fiscal_quarter,fs_div",
        ).execute()
    return len(payload), 0


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="L2″ 게이트 통과 종목 정밀 재무")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--code", action="append", default=[], help="특정 6자리 종목코드(반복 가능)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--refresh", action="store_true", help="이미 측정된 게이트 통과 종목도 재수집")
    args = parser.parse_args()
    codes = {code.strip() for item in args.code for code in item.split(",") if code.strip()}
    return run(save=args.save, codes=codes or None, limit=args.limit, refresh=args.refresh)


if __name__ == "__main__":
    raise SystemExit(main())
