# PRD Ref: §8.7 · ADR50 — 기존 영속 후속큐의 실행기만 구독 Codex로 전환.
from datetime import datetime, timezone
import json

from src.db.supabase_client import get_client, service_error_code
from src.llm.subscription import execute, SubscriptionWait, STATE, write_json


def run_once() -> dict:
    from telegram_bridge import deck_runner as old
    client = old.get_client()
    job = client.rpc("kairos_claim_deck", {}).execute().data
    if not job:
        return {"status": "idle", "model_calls": 0}
    mode, owner = job.get("mode", "deck"), job["analysis"]
    key = f"{'A' if mode == 'analysis' else 'D'}{job['id']}"
    names = ["status", "request_id", "mode", "notion_url", "drive_dir", "analysis_md",
             "proof_path", "gap_review_path", "comparison_review_path"]
    schema = {"type": "object", "properties": {name: {"type": "string"} for name in names},
              "required": names + ["files"], "additionalProperties": False}
    schema["properties"]["files"] = {"type": "array", "items": {"type": "string"}}
    schema["properties"]["top_pick"] = {"type": ["object", "null"], "properties": {
        name: {"type": "string"} for name in ("name", "market", "code")},
        "required": ["name", "market", "code"], "additionalProperties": False}
    schema["required"].append("top_pick")
    prompt = ""
    # Existing file/template/readback contracts stay in force; provider identity does not.
    prompt += (
        "\n최신 사용자 지시 ADR50: 이 작업의 실행자는 ChatGPT Pro Codex이다. "
        "Claude CLI/API, OpenAI API/Batch, 유료크레딧 구매를 호출하지 마라. "
        "기존 문서의 Claude 단계는 이 Codex 검수 단계로 읽어라. 기존 도구/전체 양식/자료범위/"
        "gap 검색/Notion 전체 재조회/실파일 해시 검증을 보존하라. "
        "다른 agent를 시작하지 말고 후처리를 직접 끝내라. 코드/예약/인증은 변경하지 마라. "
        f"최종 request_id={key}, mode={mode}, status=ok JSON만 반환하라. "
        "해당하지 않는 경로는 빈 문자열로 반환하라. 게시/검증이 실제로 안되면 성공을 만들지 마라. "
        "PPT는 mode=deck으로 사용자가 요청한 경우만 만든다."
    )
    file_first = False
    generated = False
    try:
        from telegram_bridge.file_first import is_file_first
        file_first = owner.get("update_id") is not None and is_file_first(owner["update_id"])
        ready = owner.get("status") == "sent" or (mode == "analysis" and file_first and owner.get("status") == "working" and owner.get("stage") == "claude")
        if mode not in {"analysis", "deck"} or not ready:
            raise ValueError("DECK_ANALYSIS_NOT_READY")
        prompt = old.build_prompt(job) + prompt
        result = execute(prompt, schema, key=f"kairos:{key}", phase="review-publish", writable=True)
        generated = True
        if result.get("status") != "ok" or result.get("request_id") != key or result.get("mode") != mode:
            raise ValueError("CODEX_RESULT_WRONG_REQUEST")
        old.validate_success(result, mode)
        if mode == "deck":
            old.validate_deck_readback(result, key, owner["request_kind"])
        else:
            from telegram_bridge.notion_readback import validate_readback
            from telegram_bridge.research_handoff import validate_gap_review
            from telegram_bridge.file_first import is_file_first, package_path, record_validation, validate_comparison
            package = package_path(owner["update_id"]) if owner.get("update_id") is not None else None
            validate_gap_review(result, key, package)
            validate_readback(key, result["notion_url"], owner["request_kind"], old.Path(result.get("proof_path", "")))
            if owner.get("update_id") is not None and is_file_first(owner["update_id"]):
                validate_comparison(result, key)
                record_validation(job, result, old.STATE)
        payload = {"status": "sent", "notion_url": result["notion_url"], "drive_dir": result["drive_dir"],
                   "files": result["files"], "error": None, "completed_at": datetime.now(timezone.utc).isoformat()}
        if mode == "analysis":
            payload.update(analysis_md=result["analysis_md"], top_pick=old.validate_top_pick(result.get("top_pick")) if owner["request_kind"] == "industry" else None)
    except SubscriptionWait as exc:
        payload = {"status": "pending", "error": str(exc), "retry_after": exc.retry_at,
                   "attempts": max(0, job.get("attempts", 1) - 1), "claimed_at": None, "completed_at": None}
    except Exception as exc:
        error = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else service_error_code(exc)
        if error.startswith(("GAP_", "NOTION_READBACK_", "DECK_READBACK_", "DECK_FILE_", "DECK_FILES_", "FILE_HANDOFF_", "CODEX_RESULT_")):
            if generated:
                from src.llm.subscription import invalidate
                invalidate(f"kairos:{key}", "review-publish", error)
            payload = old.retry_payload(error, job.get("attempts", 1), datetime.now(timezone.utc))
        else:
            payload = {"status": "failed", "error": error, "completed_at": datetime.now(timezone.utc).isoformat()}
    write_json(STATE / "kairos" / f"{key}.json", payload)
    # Keep legacy recovery marker for result delivery, never regenerate an already validated result.
    old.STATE.mkdir(parents=True, exist_ok=True)
    write_json(old.STATE / f"{key}.json", payload)
    changed = client.table("kairos_deck_requests").update(payload).eq("id", job["id"]).eq("status", "working").execute().data
    if not changed:
        raise RuntimeError("CODEX_REMOTE_STATUS_CHANGED")
    if mode == "analysis" and file_first:
        from telegram_bridge.file_first import finalize
        finalize({**job, **payload}, owner)
    return {"id": job["id"], "mode": mode, **payload}
