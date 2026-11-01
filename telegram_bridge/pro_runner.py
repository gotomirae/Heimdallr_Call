# PRD Ref: §7/8.7/10 · ADR50 — Python만 큐 확인, 요청이 있을 때만 구독 실행.
from datetime import datetime, timezone
import json
from pathlib import Path

from src.db.supabase_client import service_error_code
from src.llm.subscription import execute, invalidate, SubscriptionWait, STATE, read_json, write_json


def intake_once() -> dict:
    from telegram_bridge import bridge
    from telegram_bridge.file_first import package_path, validate_files
    db = bridge.connect()
    try:
        bridge.sync_pending(db)
        row = db.execute("SELECT * FROM jobs WHERE source='telegram' AND status IN ('pending','working') ORDER BY created_at,id LIMIT 1").fetchone()
        if not row:
            return {"status": "idle", "model_calls": 0}
        identity = int(row["id"])
        quota = read_json(STATE / "usage-wait.json")
        if quota.get("retry_at") and datetime.fromisoformat(quota["retry_at"]) > datetime.now(timezone.utc):
            return {"status": "deferred", "model_calls": 0}
        if row["status"] == "pending":
            bridge.claim(db, identity)
        checkpoint = bridge.ensure_checkpoint(db, identity)
        skill = Path.home() / ".codex/skills/kairos/SKILL.md"
        prompt = (
            f"사용자가 Telegram 분석 버튼으로 승인한 요청 {identity}를 처리하라. "
            f"작업 장부 {checkpoint}와 {skill}을 읽어 전체 기업/산업 양식으로 분석하라. "
            "최신 ADR50이 옛지시보다 우선한다. Claude/API/Batch/추가크레딧 구매를 사용하지 말라. "
            "다른agent를시작하지말고 코드/예약/인증을바꾸지말라. 기존자료/최근3개월발행자료/"
            "공식출처/gap별검색/숫자·기간·단위/전체템플릿/실파일해시를검증하라. "
            "원고와정본handoff를저장하고 bridge handoff와complete-codex로 Codex검수큐에전달하라. "
            "이번 작성단계에서는 Notion게시/PPT를하지말라. 검수단계가최종게시한다. "
            "이미 인계됐으면 다시생성하지말고 상태를확인하라. 실제인계후에만status=handed_off를반환하라."
        )
        schema = {"type": "object", "properties": {"status": {"type": "string", "enum": ["handed_off", "awaiting_input"]}},
                  "required": ["status"], "additionalProperties": False}
        result = execute(prompt + " 사용자 폴더선택을 요청한 경우 status=awaiting_input으로 반환하라.", schema,
                         key=f"kairos-draft:{identity}", phase="draft", writable=True)
        if result.get("status") == "awaiting_input":
            invalidate(f"kairos-draft:{identity}", "draft", "사용자 폴더 선택 후 같은 요청을 재개한다.")
            return {"status": "awaiting_input", "id": identity}
        validate_files(json.loads(package_path(identity).read_text(encoding="utf-8")), identity)
        after = db.execute("SELECT status FROM jobs WHERE id=?", (identity,)).fetchone()
        if not after or after["status"] != "claude":  # Legacy state label, executed only by Pro Codex.
            raise RuntimeError("CODEX_DRAFT_NOT_HANDED_OFF")
        return {"status": "review_pending", "id": identity}
    finally:
        db.close()


def run_once() -> dict:
    from src.llm.subscription import single_worker
    from telegram_bridge.pro_followups import run_once as followups
    from src.analysis.pro_worker import run_once as dashboard
    try:
        with single_worker(STATE / "runner-lock"):
            result = followups()
            if result.get("status") != "idle":
                return result
            result = intake_once()
            if result.get("status") != "idle":
                return result
            return dashboard()
    except SubscriptionWait as exc:
        return {"status": "deferred", "error": str(exc), "retry_after": exc.retry_at}


if __name__ == "__main__":
    from telegram_bridge.deck_runner import safe_notifications
    try:
        safe_notifications()
        result = run_once()
        result["notifications"] = safe_notifications()
    except Exception as exc:
        result = {"status": "error", "error": service_error_code(exc)}
    write_json(STATE / "worker.json", {"checked_at": datetime.now(timezone.utc).isoformat(), **result})
    print(json.dumps(result, ensure_ascii=False))
