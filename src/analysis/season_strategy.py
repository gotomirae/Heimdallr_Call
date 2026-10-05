# PRD Ref: §9.3 · ADR 28
"""실적 시즌 전략과 사후 검증. 순수 함수, 외부 I/O 없음."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import date, timedelta
from math import isfinite

from src.analysis.outcome import median, pct_change
from src.config.constants import (
    STRATEGY_HORIZONS, STRATEGY_MAX_CANDIDATES, STRATEGY_MIN_SAMPLE,
    STRATEGY_MIN_SEASONS, STRATEGY_MONTHS, STRATEGY_NEWS_DAYS,
    STRATEGY_RULE_VERSION, STRATEGY_TREND_SESSIONS, MIN_ESTIMATES,
)


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def season_of(today: date) -> dict:
    month = max(m for m in STRATEGY_MONTHS if m <= today.month)
    quarter = (month - 1) // 3  # 10월에는 다가오는 3Q 발표를 준비한다.
    return {"id": f"{today.year}-{month:02}", "starts": f"{today.year}-{month:02}-01",
            "target_year": today.year if quarter else today.year - 1,
            "target_quarter": quarter or 4}


def latest_before(rows: list[dict], cutoff: int) -> dict[str, dict]:
    result = {}
    for row in rows:
        idx = row["fiscal_year"] * 4 + row["fiscal_quarter"]
        if idx > cutoff:
            continue
        old = result.get(row["code"])
        if old is None or idx > old["fiscal_year"] * 4 + old["fiscal_quarter"]:
            result[row["code"]] = row
    return result


def feedback(plans: list[dict], before: str) -> list[dict]:
    """생성 전에 실제로 알려진 D+60 결과만 반영. 동일 시즌 중복은 표본 증가 아님."""
    sectors = defaultdict(list)
    for plan in plans:
        for row in plan.get("review", {}).get("stocks", []):
            point = row.get("horizons", {}).get("60", {})
            value = number(point.get("excess"))
            if value is not None and point.get("date", "9999") < before:
                sectors[row["sector"]].append((plan["id"], value))
    out = []
    for sector, values in sorted(sectors.items()):
        seasons = len({item[0] for item in values})
        season_counts = {s: sum(item[0] == s for item in values) for s in {item[0] for item in values}}
        enough = sum(n >= STRATEGY_MIN_SAMPLE for n in season_counts.values()) >= STRATEGY_MIN_SEASONS
        med = median([item[1] for item in values])
        out.append({"sector": sector, "n": len(values), "seasons": seasons, "median": med,
                    "action": "재확인 우선" if enough and med < 0 else "유지" if enough else "잠정 관찰",
                    "applied": enough, "season_samples": season_counts})
    return out


def create_plan(today: date, universe: list[dict], screens: list[dict], funds: list[dict],
                consensus: list[dict], analyses: list[dict], disclosures: list[dict],
                outcomes: list[dict], macro: dict, prior: list[dict]) -> dict:
    season = season_of(today)
    target = season["target_year"] * 4 + season["target_quarter"]
    sc = latest_before(screens, target - 1)
    fs = {(r["code"], r["fiscal_year"], r["fiscal_quarter"]): r for r in funds}
    cs = {}
    for r in sorted(consensus, key=lambda r: str(r.get("snapshot_at", ""))):
        if (r["fiscal_year"] * 4 + r["fiscal_quarter"] == target
                and str(r.get("snapshot_at", ""))[:10] <= today.isoformat()
                and (number(r.get("n_estimates")) or 0) >= MIN_ESTIMATES):
            cs[r["code"]] = r
    issues_from = (today - timedelta(days=STRATEGY_NEWS_DAYS)).isoformat()
    analysis = {}
    for r in sorted(analyses, key=lambda r: str(r.get("created_at", ""))):
        payload = r.get("payload") or {}
        if (issues_from <= str(r.get("created_at", ""))[:10] <= today.isoformat()
                and not (payload.get("_heimdallr") or {}).get("invalid")):
            analysis[(r["code"], r.get("fiscal_year"), r.get("fiscal_quarter"))] = r
    notes = feedback(prior, today.isoformat())
    caution = {r["sector"] for r in notes if r["action"] == "재확인 우선"}
    candidates = []
    for u in universe:
        s = sc.get(u["code"])
        if (u.get("is_excluded") is True or not s or s.get("gate_passed") is not True
                or s.get("grade") not in ("★", "○") or s.get("base_effect_warning") is not False):
            continue
        # 이미 목표 실적이 나온 기업을 '발표 전 후보'로 넣지 않는다.
        if (u["code"], season["target_year"], season["target_quarter"]) in fs:
            continue
        key = (u["code"], s["fiscal_year"], s["fiscal_quarter"])
        f, c = fs.get(key, {}), cs.get(u["code"], {})
        if s["fiscal_year"] * 4 + s["fiscal_quarter"] != target - 1:
            continue  # 여러 분기 낡은 가속 판정을 현재 전략으로 승격하지 않는다.
        a = analysis.get(key, {})
        payload = a.get("payload") or {}
        news = [r for r in disclosures if r["code"] == u["code"]
                and issues_from <= str(r.get("disclosed_at", ""))[:10] <= today.isoformat()]
        news.sort(key=lambda r: str(r.get("disclosed_at", "")), reverse=True)
        candidates.append({"code": u["code"], "name": u.get("name"), "board": u.get("board"),
            "sector": u.get("sector") or "기타", "grade": s["grade"],
            "score": number(s.get("score_final")) if s.get("score_final") is not None else number(s.get("score_flash")),
            "pri": number(s.get("pri")), "source_quarter": f'{s["fiscal_year"]}.{s["fiscal_quarter"]}Q',
            "revenue_yoy": number(f.get("revenue_yoy")), "op_yoy": number(f.get("op_yoy")),
            "op_status_label": f.get("op_status_label"), "opm": number(f.get("opm")),
            "expected_revenue": number(c.get("revenue_est")), "expected_op": number(c.get("op_est")),
            "thesis": payload.get("one_line_thesis") if isinstance(payload.get("one_line_thesis"), str) else None,
            "analysis_date": a.get("created_at"), "risks": payload.get("risks") or [],
            "news": [{"title": n.get("report_nm"), "date": str(n.get("disclosed_at"))[:10],
                      "url": f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={n["rcept_no"]}'} for n in news[:3]],
            "feedback_caution": (u.get("sector") or "기타") in caution})
    preferred = set(macro.get("preferredSectors", [])) if not macro.get("stale") else set()
    candidates.sort(key=lambda r: (r["feedback_caution"], r["sector"] not in preferred,
        r["pri"] is None, r["pri"] if r["pri"] is not None else float("inf"),
        -(r["score"] if r["score"] is not None else -float("inf")), r["code"]))
    # 기존 시즌 성과는 회고 근거이며 새 전략 수익률과 합치지 않는다.
    historical = [number(r.get("excess_d60")) for r in outcomes
                  if r["fiscal_year"] * 4 + r["fiscal_quarter"] < target]
    historical = [v for v in historical if v is not None]
    universe_by_code = {r["code"]: r for r in universe}
    previous_results = defaultdict(list)
    for r in outcomes:
        if r["fiscal_year"] * 4 + r["fiscal_quarter"] != target - 1:
            continue
        value = number(r.get("excess_d20"))
        if value is not None:
            sector = universe_by_code.get(r["code"], {}).get("sector") or "기타"
            previous_results[sector].append(value)
    recent_sectors = [{"sector": sector, "n": len(v), "median": median(v)}
                      for sector, v in sorted(previous_results.items())]
    season.update({"created_at": today.isoformat(), "rule_version": STRATEGY_RULE_VERSION,
        "late_start": today.isoformat() != season["starts"], "feedback": notes,
        "candidates": candidates[:STRATEGY_MAX_CANDIDATES], "eligible": len(candidates),
        "macro": deepcopy(macro), "history": {"n": len(historical), "median": median(historical)},
        "recent_sectors": recent_sectors,
        "actions": ["매크로 대응: " + ("한국 시장 위험회피 국면에서는 발표 확인 후 진입을 우선하고 섹터 집중을 줄인다." if macro.get("koreaMode") == "risk_off" else "선호 섹터와 실적 가속이 겹치는 후보를 우선하되 선반영 확대 시 추격을 보류한다."),
                    "발표 전: 직전 실적 가속·마진과 최근 공시를 확인하고 낮은 PRI 후보부터 관찰한다.",
                    "발표 후: 매출·영업이익·OPM과 저장한 기대치를 대조한 뒤 분할 진입을 검토한다.",
                    "철회: 가속 둔화·마진 훼손·일회성 이익·전망 하향을 확인하면 신규 진입을 보류한다.",
                    "관리: 같은 섹터 편중을 줄이고 매크로 위험 및 선반영 확대 시 확인 후 접근한다."],
        "limitations": ["선별은 규칙 기반이며 저장된 분석만 사용한다. 신규 유료 LLM 호출 없음.",
                         "실제 매매 성과가 아닌 고정 후보군의 종가 관찰 성과다. 수수료·슬리피지 미포함.",
                         "시즌 최초 실행일에 고정한다. 지연 생성 시 월초 전략으로 소급하지 않는다."]})
    return season


def review_plan(plan: dict, today: date, closes: dict[str, dict[str, float]],
                indices: dict[str, dict[str, float]], funds: list[dict]) -> dict:
    """전략 생성 후 첫 거래일 종가 기준. 거래일 달력은 해당 시장 지수로 고정."""
    fs = {(r["code"], r["fiscal_year"], r["fiscal_quarter"]): r for r in funds}
    old = {r["code"]: r for r in plan.get("review", {}).get("stocks", [])}
    stocks = []
    for c in plan["candidates"]:
        index = indices.get(c["board"], {})
        stock = closes.get(c["code"], {})
        days = sorted(d for d in index if plan["created_at"].replace("-", "") < d <= today.strftime("%Y%m%d"))
        row = {"code": c["code"], "sector": c["sector"], "horizons": deepcopy(old.get(c["code"], {}).get("horizons", {}))}
        row["base_date"] = days[0] if days else old.get(c["code"], {}).get("base_date")
        base = row["base_date"]
        for horizon in STRATEGY_HORIZONS:
            if len(days) <= horizon:
                continue
            end = days[horizon]
            ret = pct_change(number(stock.get(base)), number(stock.get(end)))
            bench = pct_change(number(index.get(base)), number(index.get(end)))
            if ret is not None and bench is not None:
                row["horizons"][str(horizon)] = {"date": f"{end[:4]}-{end[4:6]}-{end[6:]}",
                    "return": ret, "benchmark": bench, "excess": ret - bench}
        current = days[-1] if days else None
        ret = pct_change(number(stock.get(base)), number(stock.get(current)))
        bench = pct_change(number(index.get(base)), number(index.get(current)))
        row["current"] = ({"date": current, "return": ret, "excess": ret - bench if bench is not None else None}
                          if ret is not None else deepcopy(old.get(c["code"], {}).get("current", {"date": current, "return": None, "excess": None})))
        # 전략 전 60거래일 가격 추이도 실제 같은 날짜끼리 대조한다.
        before = sorted(d for d in index if d <= plan["created_at"].replace("-", ""))
        start = before[-STRATEGY_TREND_SESSIONS - 1] if len(before) > STRATEGY_TREND_SESSIONS else None
        finish = before[-1] if before else None
        trend = pct_change(number(stock.get(start)), number(stock.get(finish)))
        row["trend"] = ({"return": trend, "from": start, "through": finish} if trend is not None else
                        deepcopy(old.get(c["code"], {}).get("trend", {"return": None, "from": start, "through": finish})))
        f = fs.get((c["code"], plan["target_year"], plan["target_quarter"]), {})
        actual_rev, actual_op = number(f.get("revenue")), number(f.get("op"))
        # 성장률은 같은 부호 양수에서만. 흑적 전환은 숫자 차이와 상태로 보여준다.
        row["earnings"] = {"revenue": actual_rev, "op": actual_op, "opm": number(f.get("opm")),
            "revenue_yoy": number(f.get("revenue_yoy")), "op_status_label": f.get("op_status_label"),
            "revenue_gap_pct": pct_change(c["expected_revenue"], actual_rev) if c["expected_revenue"] and c["expected_revenue"] > 0 and actual_rev is not None and actual_rev > 0 else None,
            "op_gap": actual_op - c["expected_op"] if actual_op is not None and c["expected_op"] is not None else None}
        stocks.append(row)
    summaries = {}
    for horizon in STRATEGY_HORIZONS:
        points = [r["horizons"].get(str(horizon), {}) for r in stocks]
        excess = [number(p.get("excess")) for p in points]
        values = [v for v in excess if v is not None]
        summaries[str(horizon)] = {"n": len(values), "total": len(stocks), "median": median(values),
            "win_rate": sum(v > 0 for v in values) / len(values) if values else None,
            "status": "검증 완료" if stocks and len(values) == len(stocks) else "검증 진행 중"}
    lessons = []
    for sector in sorted({r["sector"] for r in stocks}):
        selected = [r for r in stocks if r["sector"] == sector]
        values = [r["horizons"]["60"]["excess"] for r in selected if "60" in r["horizons"]]
        m = median(values)
        lessons.append({"sector": sector, "n": len(values), "total": len(selected), "median": m,
            "message": "D+60 미성숙: 검증 대기" if m is None else
                "지수 대비 부진: 기대 실적 미달·마진 훼손·선반영을 재점검" if m < 0 else
                "지수 대비 양호: 가속 지속·기대치 충족 여부 확인",
            "earnings_measured": sum(r["earnings"]["revenue"] is not None for r in selected)})
    return {"checked_at": today.isoformat(), "stocks": stocks, "summary": summaries, "lessons": lessons}
