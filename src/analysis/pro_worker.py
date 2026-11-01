# PRD Ref: §7, §9, §10 · ADR50
"""분석 버튼 전용 Pro 큐. 현재 요청 우선, 과거 분기 순차 보충."""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from src.analysis.analyze import analyze, save, validate_payload
from src.analysis.freshness import facts_hash
from src.analysis.run import build_input
from src.config.constants import CODEX_ANALYSIS_MODEL
from src.db.supabase_client import get_client, service_error_code
from src.llm.subscription import SubscriptionWait, execute, read_json, write_json, single_worker, STATE

REPORT_SCHEMA = {"type": "object", "properties": {
    "title": {"type": "string"}, "report": {"type": "string"},
    "sources": {"type": "array", "items": {"type": "string"}},
    "limitations": {"type": "array", "items": {"type": "string"}}},
    "required": ["title", "report", "sources", "limitations"], "additionalProperties": False}


def evidence_hash(data) -> str:
    # SC: source identity/date/raw content matters; current prices and PRI never do.
    raw = {"funds": facts_hash(data.quarters, data.excerpt), "disclosures": data.disclosures,
           "stage": data.is_estimate, "contract": "pro-v1",
           "company": {key: getattr(data,key,None) for key in ("name","industry","products")}}
    return hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()


def company(job: dict) -> dict:
    data = build_input(job["target"], year=job["fiscal_year"], quarter=job["fiscal_quarter"], allow_fetch=True)
    digest = evidence_hash(data)
    from src.db.supabase_client import select_all
    fixed = {"fundamentals": select_all("quarterly_fundamentals", filters={"code": data.code}),
             "excerpts": select_all("disclosure_excerpts", filters={"code": data.code}, order="rcept_no", desc=True),
             "company_info": {"name": data.name, "industry": data.industry, "products": data.products}}
    input_built_at = datetime.now(timezone.utc).isoformat()
    old = (get_client().table("analyses").select("payload,created_at")
           .eq("code", data.code).eq("fiscal_year", data.fiscal_year)
           .eq("fiscal_quarter", data.fiscal_quarter).range(0, 0).execute().data or [])
    prior = old[0].get("payload") if old else None
    meta = (prior or {}).get("_heimdallr", {})
    if prior and not meta.get("invalid") and not validate_payload(prior) and not job.get("force_analysis"):
        if meta.get("pro_evidence_hash") == digest:
            return {"evidence_hash": digest, "reused": True, "url": f"/stock/{data.code}"}
    data.analysis_stage = "dashboard_on_demand"
    if job.get("historical"):
        # Retrospective context is explicit: never claim today's evidence was known then.
        data.previous_analysis = {"scope": "과거분기 사후 설명. 당시 매매 추천/당시 공개정보만의 백테스트로 표시하지 마세요."}
    if job.get("force_analysis"):
        data.previous_analysis = {**(data.previous_analysis or {}), "explicit_review": job["requested_at"]}
    result = analyze(data, provider_name="codex_subscription", model=CODEX_ANALYSIS_MODEL, web_search=False)
    errors = validate_payload(result.payload)
    if errors:
        raise ValueError("PRO_RESULT_INVALID:" + ";".join(errors[:4]))
    result.payload["_pro_evidence_hash"] = digest
    result.payload["_pro_input_built_at"] = input_built_at
    save(result)
    stored = (get_client().table("analyses").select("payload")
              .eq("code", data.code).eq("fiscal_year", data.fiscal_year)
              .eq("fiscal_quarter", data.fiscal_quarter).range(0, 0).execute().data or [])
    if not stored or stored[0]["payload"].get("_heimdallr", {}).get("pro_evidence_hash") != digest:
        raise ValueError("PRO_RESULT_READBACK_FAILED")
    if not job.get("historical"):
        get_client().table("stock_analysis_snapshots").upsert({"code": data.code, "payload": fixed,
            "analyzed_at": datetime.now(timezone.utc).isoformat()}, on_conflict="code").execute()
    return {"evidence_hash": digest, "reused": False, "url": f"/stock/{data.code}"}


def report(job: dict) -> dict:
    root = Path(__file__).resolve().parents[2]
    macro = json.loads((root / "dashboard/lib/macro-daily.json").read_text(encoding="utf-8"))
    inputs = {"kind": job["kind"], "target": job["target"], "macro": macro}
    if job["kind"] == "industry":
        from src.db.supabase_client import select_all
        universe = select_all("krx_universe", "code,name,industry")
        inputs["companies"] = [row for row in universe if row.get("industry") == job["target"]]
    if job["kind"] == "strategy":
        inputs["existing_strategy"] = json.loads((root / "dashboard/lib/season-strategies.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    key = f"{job['request_key']}:{digest}" + (f":{job['requested_at']}" if job.get("force_analysis") else "")
    prompt = ("한국 분기실적 기반 발굴을 위한 분석이다. 원자료 기준일/실제·예상/단위를 구분하고 "
              "미확보를 표시하라. 투자 반대논거·검증조건을 포함하고 자료에 없는 수치를 추측하지 말라. "
              "공개 1차 출처를 직접 열람한 경우만 sources에 기록하라. JSON report는 한국어 Markdown이다.\n"
              + json.dumps(inputs, ensure_ascii=False))
    draft = execute(prompt, REPORT_SCHEMA, key=key, phase="draft")
    result = execute(prompt + "\n다음 초안의 출처·수치·반대논거를 검수하고 전체 최종본을 반환하라.\n"
                     + json.dumps(draft, ensure_ascii=False), REPORT_SCHEMA, key=key, phase="review")
    if not isinstance(result.get("report"), str) or not result["report"].strip():
        raise ValueError("PRO_REPORT_EMPTY")
    return {**result, "evidence_hash": digest}


def run_once() -> dict:
    try:
        with single_worker(STATE / "queue-lock"):
            return _run_once()
    except SubscriptionWait as exc:
        return {"status": "deferred", "model_calls": 0, "error": str(exc), "retry_after": exc.retry_at}


def _run_once() -> dict:
    db = get_client()
    now = datetime.now(timezone.utc)
    # Paginate: deferred work cannot hide current requests behind PostgREST's first 1000 rows.
    from src.db.supabase_client import select_all
    jobs = [row for status in ("pending", "deferred")
            for row in select_all("pro_analysis_jobs", "*", filters={"status": status}, order="requested_at")]
    # Only recover jobs this machine claimed. CLI PID tickets independently block live orphans.
    for row in select_all("pro_analysis_jobs", "*", filters={"status": "working"}, order="requested_at"):
        ticket = read_json(STATE / "jobs" / f"{row['id']}-claim.json")
        if ticket.get("requested_at") == row["requested_at"]:
            jobs.append(row)
    jobs = [j for j in jobs if not j.get("retry_after") or datetime.fromisoformat(j["retry_after"]) <= now]
    jobs.sort(key=lambda j: (j["historical"], j["requested_at"]))
    if not jobs:
        return {"status": "idle", "model_calls": 0}
    quota = read_json(STATE / "usage-wait.json")
    if quota.get("retry_at") and datetime.fromisoformat(quota["retry_at"]) > now:
        return {"status": "deferred", "model_calls": 0, "retry_after": quota["retry_at"]}
    job = jobs[0]
    write_json(STATE / "jobs" / f"{job['id']}-claim.json", {"requested_at": job["requested_at"]})
    claimed = db.table("pro_analysis_jobs").update({"status": "working", "claimed_at": now.isoformat()}).eq("id", job["id"]).eq("status", job["status"]).execute().data
    if not claimed:
        return {"status": "busy", "model_calls": 0}
    try:
        # Delivery retry never reruns completed model work.
        checkpoint = STATE / "jobs" / f"{job['id']}.json"
        previous = read_json(checkpoint)
        result = previous.get("result") if previous.get("requested_at") == job["requested_at"] else None
        result = result or (company(job) if job["kind"] == "company" else report(job))
        write_json(checkpoint, {"requested_at": job["requested_at"], "result": result})
        update = {"status": "completed", "result": result, "evidence_hash": result["evidence_hash"],
                  "completed_at": datetime.now(timezone.utc).isoformat(), "error": None, "retry_after": None}
    except SubscriptionWait as exc:
        update = {"status": "deferred", "error": str(exc), "retry_after": exc.retry_at}
    except Exception as exc:
        update = {"status": "failed", "error": service_error_code(exc)}
    changed = db.table("pro_analysis_jobs").update(update).eq("id", job["id"]).eq("status", "working").execute().data
    if not changed:
        raise RuntimeError("PRO_JOB_STATE_CHANGED")
    return {"id": job["id"], **update}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        print(json.dumps({"jobs": len(get_client().table("pro_analysis_jobs").select("id").range(0, 0).execute().data or []), "model_calls": 0}))
    else:
        print(json.dumps(run_once(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
