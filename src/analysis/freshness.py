# PRD Ref: §7, §10 — 실제 재무·공시 내용이 달라질 때만 분석을 갱신한다.
"""I/O 없는 분석 근거 비교. 수집 시각·시세 변동은 유료 재분석 조건이 아니다."""

import hashlib
import json
from decimal import Decimal

FACT_FIELDS = (
    "fiscal_year", "fiscal_quarter", "revenue", "op", "np", "revenue_yoy",
    "op_yoy", "opm", "opm_yoy_delta", "ttm_revenue", "ttm_op", "ttm_opm",
    "ttm_cfo", "cfo", "capex", "fcf", "receivables", "inventory",
    "shares_outstanding", "shares_yoy", "op_status_label", "is_estimate",
)


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
