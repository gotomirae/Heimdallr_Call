# PRD Ref: §9.3 · §10 · ADR 28
"""매일 전략 장부 갱신. 분기 최초 실행에 생성하고 원 전략을 덮어쓰지 않는다."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from src.analysis.season_strategy import create_plan, review_plan, season_of
from src.collectors.kis_prices import fetch_index_closes
from src.collectors.quarter_prices import fetch_daily_closes_naver
from src.config.constants import KST, STRATEGY_NEWS_DAYS
from src.db.supabase_client import select_all
from src.universe.sector_map import canonical_sector_name, classify_sector
from src.utils.console import enable_utf8_stdout

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "dashboard/lib/season-strategies.json"


def refresh(output: Path = OUTPUT, *, save: bool = False) -> dict:
    now = datetime.now(ZoneInfo(KST))
    today = now.date()
    ledger = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {"plans": []}
    plans = ledger["plans"]
    funds = select_all("quarterly_fundamentals", "code,fiscal_year,fiscal_quarter,revenue,op,opm,revenue_yoy,op_yoy,op_status_label,is_estimate,fs_div")
    # 추정 행은 실제 실적 검증에 쓰지 않는다. CFS가 있으면 OFS와 섞지 않는다.
    funds.sort(key=lambda r: r.get("fs_div") == "CFS")
    funds = list({(r["code"], r["fiscal_year"], r["fiscal_quarter"]): r
                  for r in funds if r.get("is_estimate") is not True}.values())
    season = season_of(today)
    if not any(p["id"] == season["id"] for p in plans):
        universe = select_all("krx_universe", "code,name,board,sector,industry,products,is_excluded")
        for u in universe:
            u["sector"] = canonical_sector_name(u.get("sector")) if u.get("sector") else classify_sector(u.get("name"), u.get("industry"), u.get("products"))
        screens = select_all("screen_results", "code,fiscal_year,fiscal_quarter,gate_passed,grade,base_effect_warning,score_flash,score_final,pri")
        consensus = select_all("consensus_snapshots", "code,fiscal_year,fiscal_quarter,revenue_est,op_est,n_estimates,snapshot_at", filters={"fiscal_year": season["target_year"], "fiscal_quarter": season["target_quarter"]})
        analyses = select_all("analyses", "code,fiscal_year,fiscal_quarter,payload,created_at")
        disclosures = select_all("earnings_disclosures", "code,rcept_no,report_nm,disclosed_at")
        outcomes = select_all("outcome_tracking", "code,fiscal_year,fiscal_quarter,excess_d20,excess_d60")
        macro = json.loads((ROOT / "dashboard/lib/macro-daily.json").read_text(encoding="utf-8"))
        # 실패한 원천의 오래된 자료는 그대로 날짜와 함께 알린다.
        macro["stale"] = str(macro.get("checkedAt", ""))[:10] < (today - timedelta(days=7)).isoformat()
        macro["recentIssues"] = [r for r in macro.get("recentIssues", [])
            if (today - timedelta(days=STRATEGY_NEWS_DAYS)).isoformat() <= str(r.get("publishedAt", ""))[:10] <= today.isoformat()]
        plans.append(create_plan(today, universe, screens, funds, consensus, analyses, disclosures, outcomes, macro, plans))
    first = min(p["created_at"] for p in plans)
    begin = (datetime.fromisoformat(first).date() - timedelta(days=180)).strftime("%Y%m%d")
    through = today if now.hour >= 16 else today - timedelta(days=1)
    end = through.strftime("%Y%m%d")
    indices, closes, errors = {}, {}, []
    # HTTP 전송 실패는 격리하되 인증·스키마·코드 오류는 정상 결과로 숨기지 않는다.
    for board in sorted({c["board"] for p in plans for c in p["candidates"] if c["board"] in ("KOSPI", "KOSDAQ")}):
        try:
            indices[board] = {d: v for d, v in fetch_index_closes(board, begin, end).items() if d <= end}
            if not indices[board]:
                errors.append(f"{board}: 지수 원천 0행")
        except (httpx.HTTPError, RuntimeError) as exc:
            errors.append(f"{board}: {type(exc).__name__}")
    for code in sorted({c["code"] for p in plans for c in p["candidates"]}):
        try:
            closes[code] = {d: v for d, v in fetch_daily_closes_naver(code, begin, end).items() if d <= end}
            if not closes[code]:
                errors.append(f"{code}: 일봉 원천 0행")
        except (httpx.HTTPError, RuntimeError) as exc:
            errors.append(f"{code}: {type(exc).__name__}")
    for plan in plans:
        plan["review"] = review_plan(plan, today, closes, indices, funds)
    ledger.update({"checked_at": today.isoformat(), "errors": errors, "plans": plans})
    if save:
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(ledger, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        temporary.replace(output)
    print(json.dumps({"seasons": len(plans), "current": season["id"],
        "candidates": len(plans[-1]["candidates"]), "price_codes": len(closes),
        "daily_rows": sum(len(v) for v in closes.values()), "index_rows": sum(len(v) for v in indices.values()),
        "errors": errors, "saved": save}, ensure_ascii=False))
    return ledger


def main():
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="실적 시즌 전략 생성·사후 검증")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    refresh(save=args.save)


if __name__ == "__main__":
    main()
