# PRD Ref: §7, §10 — 실제 재무·공시 내용이 달라질 때만 분석을 갱신한다.
"""I/O 없는 분석 근거 비교. 수집 시각·시세 변동은 유료 재분석 조건이 아니다."""

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from src.config.constants import (
    BROKER_REPORT_LOOKBACK_DAYS,
    BROKER_REPORT_PRIORITY_CHANNELS,
)

FACT_FIELDS = (
    "fiscal_year", "fiscal_quarter", "revenue", "op", "np", "revenue_yoy",
    "op_yoy", "opm", "opm_yoy_delta", "ttm_revenue", "ttm_op", "ttm_opm",
    "ttm_cfo", "cfo", "capex", "fcf", "receivables", "inventory",
    "shares_outstanding", "shares_yoy", "op_status_label", "is_estimate",
)

CONSENSUS_FIELDS = (
    # PER·선행 PER은 같은 이익 추정치에서도 **주가만 움직여 매일 바뀔 수 있다.**
    # 리포트 창의 증거로 쓰면 시세 변화가 유료 3단계를 열어 버린다(T138).
    "revenue_est", "op_est", "np_est", "eps_est", "n_estimates",
)


@dataclass(frozen=True)
class ReportRefreshDecision:
    ready: bool
    changed: bool
    window_end: str | None = None
    evidence_hash: str | None = None
    context: dict[str, Any] | None = None


def facts_hash(quarters: list[dict], excerpt: str | None) -> str:
    def canonical(value):
        if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            return str(Decimal(str(value)).normalize())
        return value

    rows = [{k: canonical(q.get(k)) for k in FACT_FIELDS} for q in quarters]
    rows.sort(key=lambda q: (int(q["fiscal_year"]), int(q["fiscal_quarter"])))
    body = json.dumps([rows, excerpt], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def render_excerpt(row: dict, year: int, quarter: int) -> str | None:
    sections = row.get("sections") or {}
    if not sections:
        return None
    ry, rq = row.get("fiscal_year"), row.get("fiscal_quarter")
    if ry is None or rq is None:
        head = "기준 분기 미상 — 이번 분기 것이 아닐 수 있다"
    elif (ry, rq) == (year, quarter):
        head = f"{ry}년 {rq}분기 정기보고서"
    else:
        head = (f"★ {ry}년 {rq}분기 정기보고서 "
                f"— **{year}년 {quarter}분기 것이 아니다.** "
                "여기 적힌 사실을 이번 분기 사건으로 쓰지 마라.")
    body = "\n\n".join(f"### {k}\n{v}" for k, v in sections.items())
    return f"[출처: {head}]\n\n{body}"


def select_excerpt(rows: list[dict], year: int, quarter: int) -> dict | None:
    # 정정 전 원문과 정정본이 함께 있으면 같은 분기의 가장 큰 접수번호를 쓴다.
    eligible = [r for r in rows if r.get("fiscal_year") is None
                or r.get("fiscal_quarter") is None
                or (r["fiscal_year"], r["fiscal_quarter"]) <= (year, quarter)]
    return max(eligible, key=lambda r: (r.get("fiscal_year") or 0,
                                       r.get("fiscal_quarter") or 0,
                                       r.get("rcept_no") or ""), default=None)


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _consensus_value(value: Any) -> Any:
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        return str(Decimal(str(value)).normalize())
    return value


def _relevant_consensus(row: dict, year: int, quarter: int) -> bool:
    """정기보고서 뒤 리포트가 바꿀 수 있는 연간·향후 분기 추정치만 고른다."""
    ry, rq = row.get("fiscal_year"), row.get("fiscal_quarter")
    if not isinstance(ry, int) or not isinstance(rq, int):
        return False
    if rq == 0:
        return ry >= year
    return ry * 4 + rq > year * 4 + quarter and (row.get("n_estimates") or 0) >= 2


def _latest_consensus(
    rows: list[dict],
    *,
    cutoff: date,
    year: int,
    quarter: int,
) -> dict[tuple[int, int], dict]:
    latest: dict[tuple[int, int], dict] = {}
    for row in rows:
        snap_day = _day(row.get("snapshot_at"))
        if snap_day is None or snap_day > cutoff or not _relevant_consensus(row, year, quarter):
            continue
        key = (int(row["fiscal_year"]), int(row["fiscal_quarter"]))
        previous = latest.get(key)
        if previous is None or str(row.get("snapshot_at") or "") > str(previous.get("snapshot_at") or ""):
            latest[key] = row
    return latest


def _consensus_facts(row: dict | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {field: _consensus_value(row.get(field)) for field in CONSENSUS_FIELDS}


def report_refresh_decision(
    consensus_rows: list[dict],
    session_dates: list[str],
    *,
    filing_at: str | None,
    year: int,
    quarter: int,
    trading_days: int,
) -> ReportRefreshDecision:
    """정기보고서 후 N거래일에 3차 웹검색 창이 닫혔는지 판정한다.

    거래일은 KOSPI `index_snapshots`의 실제 세션 날짜다. 스냅샷 수집시각만 새로워지고
    값이 같은 경우는 리포트 변화로 세지 않는다.
    """
    filing_day = _day(filing_at)
    sessions = sorted({d for raw in session_dates if (d := _day(raw)) is not None})
    if filing_day is None or trading_days <= 0:
        return ReportRefreshDecision(False, False)
    after = [d for d in sessions if d > filing_day]
    if len(after) < trading_days:
        return ReportRefreshDecision(False, False)
    window_end = after[trading_days - 1]
    before = _latest_consensus(
        consensus_rows, cutoff=filing_day, year=year, quarter=quarter
    )
    after_window = _latest_consensus(
        consensus_rows, cutoff=window_end, year=year, quarter=quarter
    )
    changes: list[dict[str, Any]] = []
    for key in sorted(set(before) | set(after_window)):
        old = _consensus_facts(before.get(key))
        new = _consensus_facts(after_window.get(key))
        newest_day = _day((after_window.get(key) or {}).get("snapshot_at"))
        if old == new or newest_day is None or newest_day <= filing_day:
            continue
        changes.append({
            "fiscal_year": key[0],
            "fiscal_quarter": key[1],
            "before": old,
            "after": new,
        })
    # 리포트는 정기보고서 뒤에 나온 것만 쓰고, 마지막 10달력일 범위로 한 번만 찾는다.
    search_start = max(filing_day, window_end - timedelta(days=BROKER_REPORT_LOOKBACK_DAYS - 1))
    context = {
        "filing_date": filing_day.isoformat(),
        "window_end": window_end.isoformat(),
        "changes": changes,
        "source": "naver_wisereport_consensus",
        "report_search": {
            "published_from": search_start.isoformat(),
            "published_through": window_end.isoformat(),
            "lookback_calendar_days": BROKER_REPORT_LOOKBACK_DAYS,
            "priority_channels": [
                {"name": name, "url": url}
                for name, url in BROKER_REPORT_PRIORITY_CHANNELS
            ],
        },
    }
    body = json.dumps(context, ensure_ascii=False, sort_keys=True)
    return ReportRefreshDecision(
        ready=True,
        changed=bool(changes),
        window_end=window_end.isoformat(),
        evidence_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        context=context,
    )
