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
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.collectors.dart_financials import REQUEST_INTERVAL_SEC, _to_int, aligned_previous_report, fetch_single_all
from src.config.constants import DART_BASE_URL, GPM_HISTORY_BATCH_SIZE, GPM_HISTORY_FAILURE_STREAK_LIMIT, GPM_HISTORY_MAX_SECONDS, GPM_HISTORY_QUARTERS, REPRT_CODE
from src.db.supabase_client import get_client, select_all
from src.finance.derive import margin_pct
from src.finance.quarterize import ReportFigure, fiscal_term_of, quarterize
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
    gross_profit: ReportFigure = ReportFigure()
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
    current_revenue: float | None
    prior_revenue: float | None
    gross_profit_only: bool = False
    gross_profit_check_supported: bool = False


@dataclass
class DetailStats:
    account_calls: int = 0
    stock_calls: int = 0
    stock_status: dict[str, int] = field(default_factory=dict)
    current_report_missing: list[str] = field(default_factory=list)
    gross_profit_missing: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


_ACCOUNT_IDS: dict[str, tuple[str, ...]] = {
    "gross_profit": ("ifrs-full_GrossProfit", "ifrs_GrossProfit"),
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
    "gross_profit": ("매출총이익", "매출총이익(손실)", "매출총손익"),
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


def _income_figure(row: dict | None) -> ReportFigure:
    if row is None:
        return ReportFigure()
    return ReportFigure(
        amount=cumulative_value(row.get("thstrm_amount")),
        add_amount=cumulative_value(row.get("thstrm_add_amount")),
        fiscal_term=fiscal_term_of(row.get("thstrm_nm")),
    )


def quarter_income_value(
    quarter: int, current: ReportFigure, previous: ReportFigure
) -> int | None:
    """손익 누적치를 quarterize의 검증된 규칙으로 분기 단독치로 바꾼다."""
    reports = {REPRT_CODE[quarter]: current}
    if quarter > 1:
        reports[REPRT_CODE[quarter - 1]] = previous
    return quarterize(reports)[quarter].value


def _sum_optional(values: list[int | None]) -> int | None:
    measured = [value for value in values if value is not None]
    return sum(measured) if measured else None


def extract_accounts(rows: list[dict]) -> DetailedAccounts:
    """전체 재무제표 응답에서 D축과 화면용 계정을 추출한다."""
    gross_profit_row = _pick_row(rows, "gross_profit", "IS") or _pick_row(
        rows, "gross_profit", "CIS"
    )
    gross_profit = _income_figure(gross_profit_row)
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
        gross_profit=gross_profit,
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


_FUNDAMENTAL_COLUMNS = (
    "code,fiscal_year,fiscal_quarter,fs_div,is_estimate,"
    "revenue,gross_profit,ttm_cfo,receivables,inventory,shares_yoy"
)


def _fundamental_rows(codes: set[str] | None = None) -> tuple[list[dict], bool]:
    """GPM 확인 표식 DDL 적용 전에도 기존 수집을 계속한다."""
    def read(columns: str) -> list[dict]:
        if codes is None:
            return select_all("quarterly_fundamentals", columns)
        return [row for code in sorted(codes) for row in select_all(
            "quarterly_fundamentals", columns, filters={"code": code})]
    try:
        return read(f"{_FUNDAMENTAL_COLUMNS},gross_profit_checked_at"), True
    except Exception as exc:
        if str(getattr(exc, "code", "") or "") != "42703":
            raise
        return read(_FUNDAMENTAL_COLUMNS), False


def history_gpm_rows(rows: list[dict], eligible_codes: set[str] | None = None, *, shard_index: int = 0, shard_count: int = 1) -> list[dict]:
    """순수 선별: 게이트와 무관하게 최근 실제 10분기, 최신 연결/별도 범위 고정."""
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("GPM 분할 범위가 올바르지 않습니다")
    by_code: dict[str, list[dict]] = {}
    for row in rows:
        if row.get("is_estimate") is False and (eligible_codes is None or row["code"] in eligible_codes):
            by_code.setdefault(row["code"], []).append(row)
    pending = []
    for code in sorted(by_code):
        if zlib.crc32(code.encode("utf-8")) % shard_count != shard_index:
            continue
        history = sorted(by_code[code], key=lambda r: (r["fiscal_year"], r["fiscal_quarter"]))
        scope = history[-1]["fs_div"]
        for row in history[-GPM_HISTORY_QUARTERS:]:
            if row["fs_div"] == scope and row.get("gross_profit") is None and row.get("gross_profit_checked_at") is None:
                pending.append(row)
    return pending


def run_gpm_history(*, save: bool, codes: set[str] | None = None, limit: int | None = GPM_HISTORY_BATCH_SIZE,
                    shard_index: int = 0, shard_count: int = 1, max_seconds: int = GPM_HISTORY_MAX_SECONDS) -> int:
    """기존 재무 행의 GPM만 보충한다. 재무 없는 분기·다른 항목을 만들지 않는다."""
    rows, check_supported = _fundamental_rows(codes)
    universe = {r["code"]: r for r in select_all("krx_universe", "code,corp_code,is_excluded")}
    eligible = {code for code, uni in universe.items() if uni.get("corp_code") and not uni.get("is_excluded")}
    pending = history_gpm_rows(rows, eligible, shard_index=shard_index, shard_count=shard_count)
    targets = pending if limit is None else pending[:limit]
    cache: dict[tuple[str, int, int, str], list[dict]] = {}
    payload = []
    errors = []
    missing_reports = 0
    failures_in_a_row = 0
    started = time.monotonic()
    print(f"GPM 과거 분기 미확인 {len(pending)}행 · 이번 처리 {len(targets)}행")
    for row in targets:
        if time.monotonic() - started >= max_seconds:
            print("시간 예산 종료 — 아직 시작하지 않은 분기는 다음 실행에 남깁니다")
            break
        uni = universe.get(row["code"])
        if not uni or not uni.get("corp_code") or uni.get("is_excluded"):
            continue
        try:
            def accounts(q: int) -> list[dict]:
                key = (uni["corp_code"], row["fiscal_year"], q, row["fs_div"])
                if key not in cache:
                    cache[key] = fetch_single_all(*key)
                    time.sleep(REQUEST_INTERVAL_SEC)
                return cache[key]
            q = row["fiscal_quarter"]
            current_rows = accounts(q)
            if not current_rows:
                missing_reports += 1
                continue  # API/원문 미확보는 확인 완료로 찍지 않는다.
            previous_rows = accounts(q - 1) if q > 1 else []
            if q > 1:
                previous_rows = aligned_previous_report(uni["corp_code"], row["fiscal_year"], q,
                    row["fs_div"], current_rows, previous_rows)
            current_profit = extract_accounts(current_rows).gross_profit
            previous_profit = extract_accounts(previous_rows).gross_profit if previous_rows else ReportFigure()
            if (q > 1 and current_profit.fiscal_term is not None
                    and previous_profit.fiscal_term is not None
                    and current_profit.fiscal_term != previous_profit.fiscal_term):
                errors.append(f"{row['code']} {row['fiscal_year']}.{q}Q fiscal_term_mismatch — 원문 사업연도 확인 필요")
                continue  # T237: 기간 불일치를 checked_at 완료 표식으로 숨기지 않는다.
            profit = quarter_income_value(q, current_profit, previous_profit)
            if profit is None and q > 1 and not previous_rows:
                missing_reports += 1
                continue
            stamp = datetime.now(timezone.utc).isoformat()
            item = {key: row[key] for key in ("code", "fiscal_year", "fiscal_quarter", "fs_div")}
            item.update(gross_profit=profit, gpm=margin_pct(profit, row.get("revenue")), updated_at=stamp)
            if check_supported:
                item["gross_profit_checked_at"] = stamp
            payload.append(item)
            failures_in_a_row = 0
            print(f"  {row['code']} {row['fiscal_year']}.{q}Q GPM={item['gpm']}")
        except Exception as exc:
            errors.append(f"{row['code']} {row['fiscal_year']}.{row['fiscal_quarter']}Q {type(exc).__name__}: {exc}")
            failures_in_a_row += 1
            if failures_in_a_row >= GPM_HISTORY_FAILURE_STREAK_LIMIT:
                print("연속 원천 오류 — 무한 재실행하지 않고 실패 원인을 확인해야 합니다")
                break
    measured = sum(r["gpm"] is not None for r in payload)
    print(f"수치 확인 {measured} · GPM 수치 미확인 {len(payload) - measured} · 원문 미확보 {missing_reports} · 오류 {len(errors)} · API {len(cache)}회")
    for error in errors:
        print(error)
    if save and payload:
        _save(payload)
        print(f"저장 {len(payload)}행")
    return int(bool(errors or missing_reports))


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
    fundamental_rows, gross_profit_check_supported = _fundamental_rows()
    for row in fundamental_rows:
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
        base_detail_complete = (
            fund.get("ttm_cfo") is not None
            and fund.get("shares_yoy") is not None
            and fund.get("receivables") is not None
            and prior is not None
            and prior.get("receivables") is not None
        )
        gross_profit_complete = (
            fund.get("gross_profit") is not None
            or fund.get("gross_profit_checked_at") is not None
        )
        detail_complete = base_detail_complete and gross_profit_complete
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
                current_revenue=float(fund["revenue"]) if fund.get("revenue") is not None else None,
                prior_revenue=float(prior["revenue"]) if prior and prior.get("revenue") is not None else None,
                gross_profit_only=base_detail_complete and fund.get("gross_profit") is None,
                gross_profit_check_supported=gross_profit_check_supported,
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

    previous_quarter = _previous_report(quarter)
    current = extract_accounts(current_rows)
    previous = (
        extract_accounts(aligned_previous_report(target.corp_code, year, quarter, target.fs_div,
            current_rows, accounts(year, previous_quarter)))
        if previous_quarter is not None
        else DetailedAccounts()
    )
    prior_same = extract_accounts(accounts(year - 1, quarter))
    prior_previous = (
        extract_accounts(aligned_previous_report(target.corp_code, year - 1, quarter, target.fs_div,
            accounts(year - 1, quarter), accounts(year - 1, previous_quarter)))
        if previous_quarter is not None
        else DetailedAccounts()
    )
    stamp = datetime.now(timezone.utc).isoformat()
    gross_profit = quarter_income_value(quarter, current.gross_profit, previous.gross_profit)
    prior_gross_profit = quarter_income_value(
        quarter, prior_same.gross_profit, prior_previous.gross_profit
    )
    if gross_profit is None:
        stats.gross_profit_missing.append(target.code)

    # 기존 정밀 재무가 모두 있고 GPM만 비어 있으면 주식수·CFO·전년 연간을 다시
    # 가져오지 않는다. OpenDART 부하와 전체 백필 시간을 절반 가까이 줄인다.
    if target.gross_profit_only:
        current_payload = {
            "code": target.code,
            "fiscal_year": year,
            "fiscal_quarter": quarter,
            "fs_div": target.fs_div,
            "gross_profit": gross_profit,
            "gpm": margin_pct(gross_profit, target.current_revenue),
            "updated_at": stamp,
        }
        if target.gross_profit_check_supported:
            current_payload["gross_profit_checked_at"] = stamp
        return [
            current_payload,
            {
                "code": target.code,
                "fiscal_year": year - 1,
                "fiscal_quarter": quarter,
                "fs_div": target.fs_div,
                "gross_profit": prior_gross_profit,
                "gpm": margin_pct(prior_gross_profit, target.prior_revenue),
                "updated_at": stamp,
            },
        ]

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

    current_payload = {
        "code": target.code,
        "fiscal_year": year,
        "fiscal_quarter": quarter,
        "fs_div": target.fs_div,
        "gross_profit": gross_profit,
        "gpm": margin_pct(gross_profit, target.current_revenue),
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
        "gross_profit": prior_gross_profit,
        "gpm": margin_pct(prior_gross_profit, target.prior_revenue),
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
    gross_profit_only_codes = {target.code for target in targets if target.gross_profit_only}
    full_rows = [row for row in current_rows if row["code"] not in gross_profit_only_codes]
    print(f"  GPM 보충 전용       {len(gross_profit_only_codes)}/{len(targets)}종목")
    for field_name in ("gross_profit", "gpm"):
        measured = sum(row.get(field_name) is not None for row in current_rows)
        print(f"  {field_name:18} {measured}/{len(targets)}종목 측정")
    for field_name in (
        "ttm_cfo", "receivables", "inventory", "shares_yoy", "cfo", "fcf"
    ):
        measured = sum(row.get(field_name) is not None for row in full_rows)
        print(f"  {field_name:18} {measured}/{len(full_rows)}종목 이번 수집")
    print(f"  주식수 API status: {stats.stock_status}")
    if stats.current_report_missing:
        print(f"  ⚠ 현재 전체재무 응답 없음 {len(stats.current_report_missing)}종목: "
              f"{','.join(stats.current_report_missing[:20])}")
    if stats.gross_profit_missing:
        print(f"  ⚠ 현재 매출총이익 측정 불가 {len(stats.gross_profit_missing)}종목: "
              f"{','.join(stats.gross_profit_missing[:20])}")
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
    parser.add_argument("--gpm-history", action="store_true", help="게이트와 무관한 최근 10분기 GPM만 점진 보충")
    parser.add_argument("--full-history", action="store_true", help="GPM 미확인 전체를 시간 예산 내 처리")
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--max-seconds", type=int, default=GPM_HISTORY_MAX_SECONDS)
    args = parser.parse_args()
    codes = {code.strip() for item in args.code for code in item.split(",") if code.strip()}
    if args.gpm_history:
        if args.limit is not None and args.limit <= 0 or args.max_seconds <= 0 or args.shard_count < 1 or not 0 <= args.shard_index < args.shard_count:
            parser.error("limit/max-seconds/shard-count는 양수, shard-index는 분할 범위 내여야 합니다")
        return run_gpm_history(save=args.save, codes=codes or None,
            limit=args.limit if args.limit is not None else None if args.full_history else GPM_HISTORY_BATCH_SIZE,
            shard_index=args.shard_index, shard_count=args.shard_count, max_seconds=args.max_seconds)
    if args.full_history:
        parser.error("--full-history는 --gpm-history와 함께 사용합니다")
    return run(save=args.save, codes=codes or None, limit=args.limit, refresh=args.refresh)


if __name__ == "__main__":
    raise SystemExit(main())
