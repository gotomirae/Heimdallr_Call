# PRD Ref: §8 · SC: 인증된 Telegram 요청만 Kairos에 한 번 전달
"""Supabase 수신함을 로컬 큐로 옮겨 Codex를 깨운다. Telegram은 폴링하지 않는다.

    python -m telegram_bridge.bridge ingest
    python -m telegram_bridge.bridge poll
    python -m telegram_bridge.bridge claim UPDATE_ID
    python -m telegram_bridge.bridge ask-folder UPDATE_ID --json-stdin
    python -m telegram_bridge.bridge deliver UPDATE_ID --notion URL [--industry NAME]
    python -m telegram_bridge.bridge fail UPDATE_ID --reason NOTION_WRITE
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys

from src.db.supabase_client import get_client, select_all
from src.notify.kairos_requests import drive_industry_folder_matches
from src.notify.listen import allowed_chats
from src.notify.telegram import TelegramClient, bot_id_of


ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state" / "queue.sqlite3"
HEIMDALLR_BOT_ID = "8933940541"
TABLE = "kairos_requests"
WAKE_RETRY = timedelta(minutes=5)
STAGES = {
    "sources": "15% · 최근 3개월 Drive·Notion 자료 선별 중",
    "industry": "30% · 산업 구조·사이클·시장 성장 조사 중",
    "company": "50% · 기업 공시·실적·리포트 검증 중",
    "web": "60% · 공식 원문·신뢰 가능한 웹 자료 보완 중",
    "history": "70% · 기존 분석 대비 변경사항 확인 중",
    "notion": "85% · Notion 보고서·표·그래프 작성 중",
    "verify": "95% · Notion 저장 위치·출처·링크 검증 중",
    "usage": "사용량 제한으로 일시 중지 · 자동 재개 대기 중",
}

FAILURE_MESSAGES = {
    "TARGET_AMBIGUOUS": "기업 또는 산업을 하나로 식별하지 못했습니다. 정식 명칭으로 다시 요청해 주세요.",
    "SOURCE_ACCESS": "Drive·Notion 핵심 자료에 접근하지 못했습니다. 연결 권한을 확인해 주세요.",
    "WEB_RESEARCH": "필수 최신 근거를 검증하지 못해 보고서를 발행하지 않았습니다.",
    "NOTION_WRITE": "Notion 페이지 작성에 실패했습니다. 대상 페이지 권한을 확인해 주세요.",
    "NOTION_VERIFY": "저장된 Notion 페이지의 위치·본문·출처 검증에 실패했습니다.",
    "UNEXPECTED": "예상하지 못한 오류로 분석을 완료하지 못했습니다. /status에서 상태를 확인해 주세요.",
}


def connect() -> sqlite3.Connection:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(STATE, timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY, code TEXT NOT NULL, company TEXT NOT NULL,
            raw_text TEXT NOT NULL, chat_id INTEGER NOT NULL, status TEXT NOT NULL,
            request_kind TEXT NOT NULL DEFAULT 'company', target_name TEXT,
            notion_url TEXT, telegram_message_id INTEGER,
            wake_sent INTEGER NOT NULL DEFAULT 0, wake_sent_at TEXT, wake_error TEXT,
            progress_stage TEXT, progress_updated_at TEXT, failure_reason TEXT,
            drive_folder_name TEXT, drive_folder_url TEXT,
            drive_folder_confirmed INTEGER NOT NULL DEFAULT 0,
            confirmation_message_id INTEGER, confirmation_response TEXT,
            confirmation_responded_at TEXT, resume_requested INTEGER NOT NULL DEFAULT 0
        );
    """)
    columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
    if "wake_sent_at" not in columns:
        db.execute("ALTER TABLE jobs ADD COLUMN wake_sent_at TEXT")
    migrations = {
        "request_kind": "TEXT NOT NULL DEFAULT 'company'",
        "target_name": "TEXT",
        "progress_stage": "TEXT",
        "progress_updated_at": "TEXT",
        "failure_reason": "TEXT",
        "drive_folder_name": "TEXT",
        "drive_folder_url": "TEXT",
        "drive_folder_confirmed": "INTEGER NOT NULL DEFAULT 0",
        "confirmation_message_id": "INTEGER",
        "confirmation_response": "TEXT",
        "confirmation_responded_at": "TEXT",
        "resume_requested": "INTEGER NOT NULL DEFAULT 0",
        "source": "TEXT NOT NULL DEFAULT 'telegram'",
        "market": "TEXT NOT NULL DEFAULT 'KR'",
        "ticker": "TEXT",
        "industry": "TEXT",
        "created_at": "TEXT",
    }
    for name, definition in migrations.items():
        if name not in columns:
            db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
    db.execute(
        "UPDATE jobs SET target_name=company WHERE target_name IS NULL OR target_name=''"
    )
    db.commit()
    return db


def _kind_label(kind: str) -> str:
    return "기업" if kind == "company" else "산업"


def _identity(row: sqlite3.Row) -> str:
    kind = row["request_kind"] if "request_kind" in row.keys() else "company"
    name = (row["target_name"] if "target_name" in row.keys() else None) or row["company"]
    code = row["code"] if "code" in row.keys() else ""
    return f"{name} ({code})" if kind == "company" and code else str(name)


def checkpoint_path(job_id: int) -> Path:
    return STATE.parent / "checkpoints" / f"{job_id}.md"


def ensure_checkpoint(db: sqlite3.Connection, job_id: int) -> Path:
    """작업 ID별 재개 장부를 만든다. 기존 원고·진행 기록은 절대 덮어쓰지 않는다."""
    row = db.execute(
        "SELECT code,company,request_kind,target_name,raw_text,status,source,market,ticker FROM jobs WHERE id=?",
        (job_id,),
    ).fetchone()
    if not row or row["status"] != "working":
        raise RuntimeError("NOT_WORKING")
    path = checkpoint_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as record:
            record.write(
                f"# Kairos 작업 {job_id}\n\n"
                f"- 출처/시장: {row['source']} / {row['market']} / {row['ticker'] or ''}\n"
                f"- 대상 유형: {_kind_label(row['request_kind'])}\n"
                f"- 대상: {_identity(row)}\n"
                f"- 원문: {row['raw_text']}\n"
                "- 단계: 대상 식별 완료\n"
                "- 출처·수치 검증: 미작성\n"
                "- 최근 3개월 Drive·Notion 선택 기록: 미작성\n"
                "- Telegram 원소스(SungwooInsight 72시간·DOC_POOL·sunstudy1234) 조회 장부: 미작성\n"
                "- 페이지 단위 근거·강조 사본 장부: 미작성\n"
                "- 직접 확인 필요 외부 자료·링크: 미작성\n"
                "- 언급 종목 네이버증권 링크 검증: 미작성\n"
                "- 기존 분석 비교·변경사항: 미작성\n"
                "- 원고 경로: 미작성\n"
                "- Notion 페이지 ID·URL: 미작성\n"
                "- Notion 부모·본문 재조회: 미완료\n"
                "- Telegram 발송: 미완료\n"
                "- 사용량 재설정 시각: 해당 없음\n"
                "- 다음 행동: 자료 조사 시작\n"
            )
    except FileExistsError:
        pass
    return path


def setting(db: sqlite3.Connection, key: str) -> str | None:
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def save_setting(db: sqlite3.Connection, key: str, value: str) -> None:
    with db:
        db.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value)
        )


def configure_trigger(db: sqlite3.Connection, thread_id: str) -> dict:
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", thread_id):
        raise ValueError("INVALID_THREAD_ID")
    previous = setting(db, "trigger_thread")
    configured_at = datetime.now(timezone.utc).isoformat()
    with db:
        db.execute(
            "INSERT INTO settings(key,value) VALUES('trigger_thread',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (thread_id,)
        )
        db.execute(
            "INSERT INTO settings(key,value) VALUES('trigger_thread_updated_at',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (configured_at,)
        )
        requeued = 0
        if previous and previous != thread_id:
            cursor = db.execute(
                "UPDATE jobs SET wake_sent=0,wake_sent_at=NULL,wake_error=NULL "
                "WHERE status='pending'"
            )
            requeued = cursor.rowcount
    return {
        "status": "configured", "thread_id": thread_id,
        "configured_at": configured_at, "requeued_pending": requeued,
    }


def verify_bot() -> None:
    # 현재 봇만 수신된 요청에 응답한다. 다른 토큰으로 배포되면 조용히 섞이지 않는다.
    if bot_id_of(TelegramClient().token) != HEIMDALLR_BOT_ID:
        raise RuntimeError("HEIMDALLR_BOT_ID_MISMATCH")


def sync_pending(db: sqlite3.Connection) -> int:
    """전용 로컬 수신기가 기록한 pending만 로컬에 복사한다."""
    chats = allowed_chats()
    try:
        rows = select_all(
            TABLE,
            "update_id,chat_id,user_id,request_kind,target_name,code,company_name,"
            "industry,raw_text,status,telegram_message_id,source,market,ticker,created_at",
            filters={"status": "pending"}, order="update_id",
        )
    except Exception as exc:
        if str(getattr(exc, "code", "")) != "42703":
            raise
        rows = select_all(
            TABLE, "update_id,chat_id,user_id,code,company_name,raw_text,status,telegram_message_id",
            filters={"status": "pending"}, order="update_id",
        )
    if any(r.get("source", "telegram") == "telegram" for r in rows):
        verify_bot()
    added = 0
    with db:
        for row in rows:
            # 클라우드 테이블이 손상돼도 인증 조건이 없는 요청은 깨우지 않는다.
            source = row.get("source", "telegram")
            if source == "jarvis":
                if row["update_id"] >= 0 or row["chat_id"] != 0 or row["user_id"] != 0:
                    continue
            elif source != "telegram" or str(row["chat_id"]) not in chats or row["user_id"] != row["chat_id"]:
                continue
            kind = row.get("request_kind") or "company"
            target = (
                row.get("target_name") or row.get("company_name") or row.get("industry")
            )
            if kind not in {"company", "industry"} or not target:
                continue
            cursor = db.execute(
                "INSERT OR IGNORE INTO jobs("
                "id,code,company,request_kind,target_name,raw_text,chat_id,status,telegram_message_id,"
                "source,market,ticker,industry,created_at"
                ") VALUES(?,?,?,?,?,?,?,'pending',?,?,?,?,?,?)",
                (row["update_id"], row.get("code") or "", row.get("company_name") or target,
                 kind, target, row["raw_text"], row["chat_id"],
                 row.get("telegram_message_id"), source, row.get("market", "KR"), row.get("ticker"),
                 row.get("industry"), row.get("created_at")),
            )
            added += cursor.rowcount
            if row.get("telegram_message_id"):
                db.execute(
                    "UPDATE jobs SET telegram_message_id=? WHERE id=? "
                    "AND status='pending' AND telegram_message_id IS NULL",
                    (row["telegram_message_id"], row["update_id"]),
                )
    return added


def sync_folder_confirmations(db: sqlite3.Connection) -> int:
    """Mirror Telegram folder answers into the local resume queue."""
    waiting = db.execute(
        "SELECT id,confirmation_message_id FROM jobs "
        "WHERE status='awaiting_input' ORDER BY id"
    ).fetchall()
    changed = 0
    for item in waiting:
        rows = (
            get_client().table(TABLE)
            .select(
                "status,drive_folder_name,drive_folder_url,drive_folder_confirmed,"
                "confirmation_message_id,confirmation_response,confirmation_responded_at,error"
            )
            .eq("update_id", item["id"]).limit(1).execute().data or []
        )
        if not rows:
            continue
        remote = rows[0]
        status = remote.get("status")
        if status == "awaiting_input":
            if item["confirmation_message_id"] and not remote.get("confirmation_message_id"):
                repaired = (
                    get_client().table(TABLE).update({
                        "confirmation_message_id": item["confirmation_message_id"]
                    }).eq("update_id", item["id"]).eq(
                        "status", "awaiting_input"
                    ).execute()
                )
                if repaired.data:
                    changed += 1
            continue
        if status not in {"working", "rejected", "failed"}:
            continue
        resume = int(status == "working" and bool(remote.get("drive_folder_confirmed")))
        with db:
            db.execute(
                "UPDATE jobs SET status=?,drive_folder_name=?,drive_folder_url=?,"
                "drive_folder_confirmed=?,confirmation_message_id=?,confirmation_response=?,"
                "confirmation_responded_at=?,resume_requested=?,failure_reason=? WHERE id=?",
                (
                    status, remote.get("drive_folder_name"), remote.get("drive_folder_url"),
                    int(bool(remote.get("drive_folder_confirmed"))),
                    remote.get("confirmation_message_id"),
                    remote.get("confirmation_response"),
                    remote.get("confirmation_responded_at"), resume,
                    "DRIVE_FOLDER_DECLINED" if status == "rejected" else remote.get("error"),
                    item["id"],
                ),
            )
        changed += 1
    return changed


def ask_folder(
    db: sqlite3.Connection, job_id: int, folder_name: str, folder_url: str
) -> dict:
    """Pause an industry job until the user confirms a non-matching Drive folder."""
    folder_name = folder_name.strip()
    folder_url = folder_url.strip()
    if not folder_name or len(folder_name) > 200 or "\n" in folder_name or "\r" in folder_name:
        raise ValueError("INVALID_FOLDER_NAME")
    if not re.fullmatch(
        r"https://drive\.google\.com/drive/folders/[A-Za-z0-9_-]+(?:\?[^\s]+)?",
        folder_url,
    ):
        raise ValueError("INVALID_DRIVE_FOLDER_URL")
    row = db.execute(
        "SELECT company,code,request_kind,target_name,chat_id,status,source FROM jobs WHERE id=?",
        (job_id,),
    ).fetchone()
    if not row or row["status"] != "working" or row["request_kind"] != "industry":
        raise RuntimeError("NOT_WORKING_INDUSTRY")
    from src.collectors.drive_bootstrap import mapped_folder
    mapped = mapped_folder(row["target_name"])
    if row["source"] == "jarvis":
        if not mapped or not drive_industry_folder_matches(mapped, folder_name):
            raise RuntimeError("JARVIS_FOLDER_USE_BOOTSTRAP")
    if drive_industry_folder_matches(row["target_name"], folder_name) or (
        mapped and drive_industry_folder_matches(mapped, folder_name)
    ):
        if not change_remote(
            job_id, "working", "working", drive_folder_name=folder_name,
            drive_folder_url=folder_url, drive_folder_confirmed=True,
        ):
            raise RuntimeError("REMOTE_JOB_NOT_WORKING")
        with db:
            db.execute(
                "UPDATE jobs SET drive_folder_name=?,drive_folder_url=?,"
                "drive_folder_confirmed=1 WHERE id=?",
                (folder_name, folder_url, job_id),
            )
        return {
            "status": "matched", "id": job_id, "confirmation_required": False,
            "folder_name": folder_name,
        }
    fields = {
        "drive_folder_name": folder_name,
        "drive_folder_url": folder_url,
        "drive_folder_confirmed": False,
        "confirmation_response": None,
        "confirmation_responded_at": None,
    }
    now = datetime.now(timezone.utc).isoformat()
    with db:
        db.execute(
            "UPDATE jobs SET status='awaiting_input',drive_folder_name=?,drive_folder_url=?,"
            "drive_folder_confirmed=0,confirmation_message_id=NULL,confirmation_response=NULL,"
            "confirmation_responded_at=NULL,resume_requested=0,progress_stage='folder_confirmation',"
            "progress_updated_at=? WHERE id=?",
            (folder_name, folder_url, now, job_id),
        )
    if not change_remote(job_id, "working", "awaiting_input", **fields):
        with db:
            db.execute("UPDATE jobs SET status='working' WHERE id=?", (job_id,))
        raise RuntimeError("REMOTE_JOB_NOT_WORKING")
    verify_bot()
    client = TelegramClient(chat_id=str(row["chat_id"]))
    message_id: int | None = None
    try:
        result = client.call("sendMessage", {
            "chat_id": row["chat_id"],
            "text": (
                "📁 Drive 산업 폴더 확인이 필요합니다.\n\n"
                f"요청 산업명: {row['target_name']}\n"
                f"선택 후보: {folder_name}\n"
                "이 폴더의 가장 최근 하위 폴더 자료를 사용할까요?\n"
                "이 메시지에 '예' 또는 '아니오'로 답장해 주세요."
            ),
            "disable_web_page_preview": True,
            "reply_markup": {"force_reply": True, "selective": True},
        })
        message_id = int(result["result"]["message_id"])
        with db:
            db.execute(
                "UPDATE jobs SET confirmation_message_id=? WHERE id=?",
                (message_id, job_id),
            )
        updated = (
            get_client().table(TABLE).update({"confirmation_message_id": message_id})
            .eq("update_id", job_id).eq("status", "awaiting_input").execute()
        )
        if not updated.data:
            raise RuntimeError("CONFIRMATION_MESSAGE_NOT_RECORDED")
    except Exception:
        if message_id is not None:
            try:
                client.call("editMessageText", {
                    "chat_id": row["chat_id"], "message_id": message_id,
                    "text": (
                        "⚠️ Drive 폴더 확인 등록에 실패했습니다.\n"
                        "이 메시지에 답장하지 말고 /status로 상태를 확인해 주세요."
                    ),
                })
            except Exception:
                pass
        try:
            change_remote(job_id, "awaiting_input", "working", error="Folder confirmation send failed")
        except Exception:
            pass
        with db:
            db.execute(
                "UPDATE jobs SET status='working',confirmation_message_id=NULL WHERE id=?",
                (job_id,),
            )
        raise
    return {
        "status": "awaiting_input", "id": job_id,
        "folder_name": folder_name, "confirmation_message_id": message_id,
    }


def set_progress(db: sqlite3.Connection, job_id: int, stage: str) -> dict:
    if stage not in STAGES:
        raise ValueError("INVALID_PROGRESS_STAGE")
    row = db.execute(
        "SELECT company,code,request_kind,target_name,chat_id,telegram_message_id,status,"
        "progress_stage,progress_updated_at,source "
        "FROM jobs WHERE id=?",
        (job_id,),
    ).fetchone()
    if not row or row["status"] != "working":
        raise RuntimeError("NOT_WORKING")
    if row["progress_stage"] == stage:
        return {"status": "progress", "id": job_id, "stage": stage,
                "updated_at": row["progress_updated_at"]}
    now = datetime.now(timezone.utc).isoformat()
    if row["source"] == "jarvis":
        if not change_remote(job_id, "working", "working", stage=stage, stage_updated_at=now):
            raise RuntimeError("REMOTE_JOB_NOT_WORKING")
    with db:
        db.execute(
            "UPDATE jobs SET progress_stage=?,progress_updated_at=? WHERE id=?",
            (stage, now, job_id),
        )
    telegram_updated = False
    telegram_error = None
    if row["source"] != "jarvis" and row["telegram_message_id"]:
        try:
            verify_bot()
            TelegramClient(chat_id=str(row["chat_id"])).call("editMessageText", {
                "chat_id": row["chat_id"],
                "message_id": row["telegram_message_id"],
                "text": (
                    f"⏳ {_identity(row)} {_kind_label(row['request_kind'])} 분석 진행 중\n"
                    f"상태: {STAGES[stage]}\n"
                    "완료 예상: 자료량에 따라 대략 30~90분 이상\n"
                    "오래 걸리면 /status로 최근 상태를 확인해 주세요."
                ),
                "disable_web_page_preview": True,
            })
            telegram_updated = True
        except Exception as exc:
            # 단계 장부는 보존한다. /status에서 확인할 수 있고 다음 단계에서 다시 편집한다.
            telegram_error = type(exc).__name__
    return {"status": "progress", "id": job_id, "stage": stage, "updated_at": now,
            "telegram_updated": telegram_updated, "telegram_error": telegram_error}


def find_codex() -> str | None:
    found = shutil.which("codex.exe") or shutil.which("codex")
    if found:
        return found
    root = Path.home() / "AppData" / "Local" / "OpenAI" / "Codex" / "bin"
    candidates = sorted(root.glob("*/codex.exe"), key=lambda p: p.stat().st_mtime,
                        reverse=True)
    return str(candidates[0]) if candidates else None


def wake_pending(db: sqlite3.Connection) -> dict:
    thread = setting(db, "trigger_thread")
    if not thread:
        return {"status": "not_configured"}
    resume = db.execute(
        "SELECT id FROM jobs WHERE status='working' AND resume_requested=1 ORDER BY id LIMIT 1"
    ).fetchone()
    if resume:
        codex = find_codex()
        if not codex:
            return {"status": "error", "id": resume["id"], "error": "CODEX_NOT_FOUND"}
        message = (
            f"Heimdallr Telegram 산업 분석 요청 {resume['id']}의 Drive 폴더 선택을 "
            "사용자가 확인했습니다. `python -m telegram_bridge.bridge poll`에서 "
            "확정된 drive_folder_name·drive_folder_url·checkpoint를 확인하고, 같은 ID의 "
            "$kairos 분석을 중복 생성 없이 재개하세요."
        )
        try:
            result = subprocess.run(
                [codex, "queue", "--thread", thread, "--message", message],
                capture_output=True, text=True, timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode:
                raise RuntimeError("CODEX_QUEUE_FAILED")
        except Exception:
            with db:
                db.execute(
                    "UPDATE jobs SET wake_error='CODEX_QUEUE_FAILED' WHERE id=?",
                    (resume["id"],),
                )
            return {"status": "error", "id": resume["id"], "error": "CODEX_QUEUE_FAILED"}
        with db:
            db.execute(
                "UPDATE jobs SET resume_requested=0,wake_sent_at=?,wake_error=NULL,"
                "progress_stage='sources',progress_updated_at=? WHERE id=?",
                (
                    datetime.now(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat(), resume["id"],
                ),
            )
        return {"status": "resumed", "id": resume["id"]}
    busy = db.execute(
        "SELECT id FROM jobs WHERE status IN ('working','awaiting_input','sending','uncertain') LIMIT 1"
    ).fetchone()
    if busy:
        return {"status": "busy", "id": busy[0]}
    row = db.execute(
        "SELECT id,wake_sent,wake_sent_at,company,code,request_kind,target_name,chat_id,"
        "telegram_message_id,progress_stage,source "
        "FROM jobs WHERE status='pending' ORDER BY created_at,id DESC LIMIT 1"
    ).fetchone()
    if not row:
        return {"status": "idle"}
    if row["wake_sent_at"]:
        last_wake = datetime.fromisoformat(row["wake_sent_at"])
        if datetime.now(timezone.utc) - last_wake < WAKE_RETRY:
            return {"status": "already_queued", "id": row["id"]}
    if row["source"] != "jarvis" and row["wake_sent"] and row["telegram_message_id"] and row["progress_stage"] != "delayed":
        try:
            verify_bot()
            TelegramClient(chat_id=str(row["chat_id"])).call("editMessageText", {
                "chat_id": row["chat_id"],
                "message_id": row["telegram_message_id"],
                "text": (f"⏳ {_identity(row)} 분석 시작 지연\n"
                         "Codex 연결을 다시 시도하고 있습니다. /status로 확인해 주세요."),
            })
            with db:
                db.execute("UPDATE jobs SET progress_stage='delayed',progress_updated_at=? WHERE id=?",
                           (datetime.now(timezone.utc).isoformat(), row["id"]))
        except Exception:
            pass
    codex = find_codex()
    if not codex:
        return {"status": "error", "id": row[0], "error": "CODEX_NOT_FOUND"}
    message = (
        f"Heimdallr {row['source']} 기업·산업 분석 요청 {row[0]}가 등록되었습니다. "
        "이 프로젝트의 `python -m telegram_bridge.bridge poll`로 실제 요청을 확인하고, "
        "request_kind와 대상을 공식 출처로 식별한 뒤 `claim ID`가 성공하면 $kairos 스킬로 "
        "분석을 시작하면서 기존 Codex heartbeat `kairos`를 ACTIVE로 설정하세요. "
        "최근 3개월 Google Drive·Notion, 기존 분석, 공식 원문·신뢰 가능한 웹 자료를 조사해 "
        "대상 유형별 지정 Notion 부모와 양식에 작성하세요. 저장 결과를 재조회한 다음 "
        "`deliver ID --notion URL --industry 산업명`으로 링크를 보내세요. "
        "식별 불가면 `reject ID`, 분석 실패면 `fail ID --reason 코드`로 원인을 알려 주세요."
    )
    message += (
        " G절 사용자 결정은 기존 Kairos Telegram-only 실행 규칙보다 우선합니다. "
        "source=jarvis는 Vault 토큰 RPC로 인증된 실제 사용자 버튼 요청이며 별도 확인 없이 처리합니다. "
        "claim 직후 생성된 Drive bootstrap 장부와 source/market/ticker를 반드시 읽으세요. "
        "config/industry_folders.yaml 매핑은 Telegram 요청에도 우선합니다. "
        "미국 Telegram 요청도 인증된 큐의 market=US/ticker를 기준으로 처리하세요. "
        "미국 기업 Notion 제목은 기업명 (TICKER·NASDAQ|NYSE)로 SEC 시장을 사용하세요. "
        "jarvis는 awaiting_input과 Heimdallr Telegram 발송을 금지합니다. 미국은 SEC 식별·공시를 사용하고 "
        "국내 /stock 링크를 미국 티커로 만들지 마세요. 산업 PDF 실제 읽은 원문만 bootstrap의 "
        "industry_pdf_destination에 복사하고 원문 URL/발행일/해시를 장부에 남기세요. "
        "Notion 재조회 결과 page/blocks/ancestors와 checked_at/request_id를 "
        "telegram_bridge/state/checkpoints/ID-notion.json에 저장한 뒤 deliver 하세요. "
        "운영 계약 정본은 telegram_bridge/JARVIS.md입니다."
    )
    try:
        result = subprocess.run(
            [codex, "queue", "--thread", thread, "--message", message],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise RuntimeError("CODEX_QUEUE_FAILED")
    except Exception:
        with db:
            db.execute(
                "UPDATE jobs SET wake_error='CODEX_QUEUE_FAILED' WHERE id=?", (row[0],)
            )
        return {"status": "error", "id": row[0], "error": "CODEX_QUEUE_FAILED"}
    with db:
        db.execute(
            "UPDATE jobs SET wake_sent=1,wake_sent_at=?,wake_error=NULL WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), row[0]),
        )
    return {"status": "requeued" if row["wake_sent"] else "queued", "id": row[0]}


def poll(db: sqlite3.Connection) -> dict:
    """Codex 쪽 조회는 로컬 큐만 읽는다."""
    rows = db.execute(
        "SELECT id,code,company,request_kind,target_name,raw_text,status,notion_url,wake_sent,"
        "wake_sent_at,wake_error,progress_stage,progress_updated_at,failure_reason,"
        "drive_folder_name,drive_folder_url,drive_folder_confirmed,confirmation_message_id,"
        "confirmation_response,confirmation_responded_at,resume_requested,source,market,ticker,industry "
        "FROM jobs WHERE status NOT IN ('sent','rejected','failed') ORDER BY id LIMIT 20"
    ).fetchall()
    jobs = [dict(row) for row in rows]
    for job in jobs:
        job["checkpoint"] = (
            str(checkpoint_path(job["id"]))
            if job["status"] in {"working", "awaiting_input"} else None
        )
    try:
        listener = json.loads((STATE.parent / "listener_last.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        listener = {"last_success": None, "last_error": "LISTENER_NOT_RUN"}
    trigger_thread = setting(db, "trigger_thread")
    return {"trigger_configured": bool(trigger_thread),
            "trigger_thread": trigger_thread,
            "trigger_thread_updated_at": setting(db, "trigger_thread_updated_at"),
            "listener": listener,
            "collector": {"last_success": setting(db, "last_success"),
                          "last_error": setting(db, "last_error"),
                          "registry_error": setting(db, "registry_error")},
            "jobs": jobs}


def change_remote(job_id: int, old: str, new: str, **fields: object) -> bool:
    result = (
        get_client().table(TABLE).update({"status": new, **fields})
        .eq("update_id", job_id).eq("status", old).execute()
    )
    return bool(result.data)


def claim(db: sqlite3.Connection, job_id: int) -> dict:
    row = db.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row or row[0] != "pending":
        return {"status": "not_claimed", "id": job_id}
    busy = db.execute(
        "SELECT id FROM jobs WHERE status IN ('working','awaiting_input','sending','uncertain') LIMIT 1"
    ).fetchone()
    if busy:
        return {"status": "busy", "id": busy[0]}
    if not change_remote(job_id, "pending", "working",
                         claimed_at=datetime.now(timezone.utc).isoformat()):
        return {"status": "not_claimed", "id": job_id}
    with db:
        db.execute("UPDATE jobs SET status='working' WHERE id=?", (job_id,))
    receipt = db.execute(
        "SELECT telegram_message_id FROM jobs WHERE id=?", (job_id,)
    ).fetchone()[0]
    if receipt is None:
        try:
            remote = (
                get_client().table(TABLE).select("telegram_message_id")
                .eq("update_id", job_id).limit(1).execute().data or []
            )
            if remote and remote[0].get("telegram_message_id"):
                with db:
                    db.execute(
                        "UPDATE jobs SET telegram_message_id=? WHERE id=?",
                        (remote[0]["telegram_message_id"], job_id),
                    )
        except Exception:
            pass
    try:
        set_progress(db, job_id, "sources")
    except Exception:
        # 상태 표시 장애는 이미 claim된 작업을 되돌리지 않는다.
        pass
    checkpoint = ensure_checkpoint(db, job_id)
    bootstrap_result = prepare_drive(db, job_id, checkpoint)
    return {"status": "claimed", "id": job_id, "checkpoint": str(checkpoint),
            "drive": bootstrap_result}


def prepare_drive(db: sqlite3.Connection, job_id: int, checkpoint: Path) -> dict:
    from src.collectors.drive_bootstrap import bootstrap
    job = dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
    try:
        if job["request_kind"] == "company" and job["market"] == "KR":
            rows = get_client().table("krx_universe").select("sector,industry").eq("code", job["code"]).limit(1).execute().data or []
            if rows:
                job["sector_hint"] = " ".join(str(rows[0].get(k) or "") for k in ("sector", "industry"))
        result = bootstrap(job)
        if job["request_kind"] == "company" and job["market"] == "US":
            from telegram_bridge.jarvis_registry import refresh_us_company
            try:
                result["reuse_evidence"] = refresh_us_company(job["ticker"])
            except Exception as exc:
                result.setdefault("failures", []).append({"source": "US_REUSE_METADATA", "error": type(exc).__name__})
        if job["request_kind"] == "industry":
            name = Path(result["folder"]).name
            if change_remote(job_id, "working", "working", drive_folder_name=name, drive_folder_confirmed=True):
                with db:
                    db.execute("UPDATE jobs SET drive_folder_name=?,drive_folder_confirmed=1 WHERE id=?", (name, job_id))
    except Exception as exc:
        # Source access/download errors never turn a claimed request into 'complete'.
        result = {"failures": [{"error": type(exc).__name__}], "files": []}
    manifest = checkpoint.with_suffix(".drive.json")
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with checkpoint.open("a", encoding="utf-8") as record:
        record.write(f"\n- Drive bootstrap 장부: {manifest}\n")
    return result


def reject(db: sqlite3.Connection, job_id: int) -> dict:
    row = db.execute(
        "SELECT company,code,request_kind,target_name,chat_id,telegram_message_id,status,source "
        "FROM jobs WHERE id=?", (job_id,),
    ).fetchone()
    if not row or row["status"] != "pending":
        return {"status": "not_rejected", "id": job_id}
    message = FAILURE_MESSAGES["TARGET_AMBIGUOUS"]
    if not change_remote(job_id, "pending", "rejected", error=message):
        return {"status": "not_rejected", "id": job_id}
    with db:
        db.execute(
            "UPDATE jobs SET status='rejected',failure_reason='TARGET_AMBIGUOUS' WHERE id=?",
            (job_id,),
        )
    if row["source"] != "jarvis" and row["telegram_message_id"]:
        try:
            verify_bot()
            TelegramClient(chat_id=str(row["chat_id"])).call("editMessageText", {
                "chat_id": row["chat_id"],
                "message_id": row["telegram_message_id"],
                "text": f"⚠️ {_identity(row)} 분석 요청 제외\n원인: {message}",
            })
        except Exception:
            pass
    return {"status": "rejected", "id": job_id}


def fail(db: sqlite3.Connection, job_id: int, reason: str) -> dict:
    """분석 실패를 영구 기록하고 접수 메시지에 복구 가능한 원인을 표시한다."""
    if reason not in FAILURE_MESSAGES:
        raise ValueError("INVALID_FAILURE_REASON")
    row = db.execute(
        "SELECT company,code,request_kind,target_name,chat_id,telegram_message_id,status,source "
        "FROM jobs WHERE id=?", (job_id,),
    ).fetchone()
    if not row or row["status"] not in {"pending", "working", "awaiting_input"}:
        raise RuntimeError("NOT_ACTIVE")
    message = FAILURE_MESSAGES[reason]
    if not change_remote(job_id, row["status"], "failed", error=reason if row["source"] == "jarvis" else message):
        raise RuntimeError("REMOTE_JOB_STATUS_CHANGED")
    with db:
        db.execute(
            "UPDATE jobs SET status='failed',failure_reason=?,progress_updated_at=? WHERE id=?",
            (reason, datetime.now(timezone.utc).isoformat(), job_id),
        )
    telegram_updated = False
    if row["source"] != "jarvis" and row["telegram_message_id"]:
        try:
            verify_bot()
            TelegramClient(chat_id=str(row["chat_id"])).call("editMessageText", {
                "chat_id": row["chat_id"],
                "message_id": row["telegram_message_id"],
                "text": (
                    f"❌ {_identity(row)} {_kind_label(row['request_kind'])} 분석 실패\n"
                    f"원인: {message}\n같은 문제가 해소된 뒤 다시 입력해 주세요."
                ),
                "disable_web_page_preview": True,
            })
            telegram_updated = True
        except Exception:
            pass
    return {"status": "failed", "id": job_id, "reason": reason,
            "telegram_updated": telegram_updated}


def deliver(db: sqlite3.Connection, job_id: int, notion: str, industry: str = "") -> dict:
    if not re.fullmatch(r"https://(?:www\.)?notion\.so/\S+|https://app\.notion\.com/p/\S+", notion):
        raise ValueError("INVALID_NOTION_URL")
    row = db.execute(
        "SELECT company,code,request_kind,target_name,chat_id,status,telegram_message_id,source "
        "FROM jobs WHERE id=?", (job_id,)
    ).fetchone()
    if not row or row["status"] != "working":
        raise RuntimeError("NOT_WORKING_OR_ALREADY_SENT")
    resolved_industry = industry.strip() or (
        row["target_name"] if row["request_kind"] == "industry" else ""
    )
    if not 1 <= len(resolved_industry) <= 100 or "\n" in resolved_industry or "\r" in resolved_industry:
        raise ValueError("INVALID_INDUSTRY")
    if row["source"] == "jarvis":
        from telegram_bridge.notion_readback import validate_readback
        validate_readback(job_id, notion, row["request_kind"], STATE.parent / "checkpoints" / f"{job_id}-notion.json")
        if not change_remote(job_id, "working", "sent", notion_url=notion,
                             completed_at=datetime.now(timezone.utc).isoformat(), error=None):
            raise RuntimeError("REMOTE_JOB_NOT_WORKING")
        with db:
            db.execute("UPDATE jobs SET status='sent',notion_url=? WHERE id=?", (notion, job_id))
        return {"status": "sent", "id": job_id, "notion_url": notion}
    verify_bot()
    client = TelegramClient(chat_id=str(row["chat_id"]))
    if not change_remote(job_id, "working", "sending",
                         notion_url=notion, industry=resolved_industry):
        raise RuntimeError("REMOTE_JOB_NOT_WORKING")
    with db:
        db.execute("UPDATE jobs SET status='sending',notion_url=? WHERE id=?",
                   (notion, job_id))
    try:
        if row["request_kind"] == "company":
            summary = f"🏭 산업: {resolved_industry}\n🏢 기업: {row['company']}"
        else:
            summary = f"🏭 산업: {row['target_name']}"
        result = client.call("sendMessage", {
            "chat_id": row["chat_id"],
            "text": (
                f"📑 Kairos {_kind_label(row['request_kind'])} 분석이 완료되었습니다.\n\n"
                f"{summary}\n\n{notion}"
            ),
            "disable_web_page_preview": True,
            "reply_markup": {"inline_keyboard": [[
                {"text": "📝 Notion 분석 페이지 열기", "url": notion}
            ]]},
        })
        message_id = result["result"]["message_id"]
        if not change_remote(job_id, "sending", "sent",
                             telegram_message_id=message_id,
                             completed_at=datetime.now(timezone.utc).isoformat()):
            raise RuntimeError("REMOTE_SENT_UPDATE_FAILED")
    except Exception:
        # Telegram 발송의 성공 여부가 불확실하므로 자동 재전송하지 않는다.
        with db:
            db.execute("UPDATE jobs SET status='uncertain' WHERE id=?", (job_id,))
        try:
            change_remote(job_id, "sending", "uncertain",
                          error="Delivery result uncertain; no automatic resend")
        except Exception:
            pass
        raise
    with db:
        db.execute(
            "UPDATE jobs SET status='sent',telegram_message_id=? WHERE id=?",
            (message_id, job_id),
        )
    if row["source"] != "jarvis" and row["telegram_message_id"]:
        try:
            client.call("editMessageText", {
                "chat_id": row["chat_id"],
                "message_id": row["telegram_message_id"],
                "text": (
                    f"✅ {_identity(row)} {_kind_label(row['request_kind'])} 분석 완료\n"
                    "Notion 링크를 새 메시지로 보냈습니다."
                ),
            })
        except Exception:
            pass
    return {"status": "sent", "id": job_id, "telegram_message_id": message_id}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("poll")
    sub.add_parser("ingest")
    sub.add_parser("status")
    sub.add_parser("checkpoint").add_argument("id", type=int)
    trigger = sub.add_parser("configure-trigger")
    trigger.add_argument("--thread", required=True)
    for command in ("claim", "reject"):
        sub.add_parser(command).add_argument("id", type=int)
    failed = sub.add_parser("fail")
    failed.add_argument("id", type=int)
    failed.add_argument("--reason", choices=tuple(FAILURE_MESSAGES), required=True)
    progress = sub.add_parser("progress")
    progress.add_argument("id", type=int)
    progress.add_argument("--stage", choices=tuple(STAGES), required=True)
    folder = sub.add_parser("ask-folder")
    folder.add_argument("id", type=int)
    folder.add_argument("--folder-name")
    folder.add_argument("--folder-url")
    folder.add_argument(
        "--json-stdin", action="store_true",
        help="Read folder_name and folder_url as one JSON object from stdin",
    )
    delivery = sub.add_parser("deliver")
    delivery.add_argument("id", type=int)
    delivery.add_argument("--notion", required=True)
    delivery.add_argument("--industry", default="")
    args = parser.parse_args()
    db = connect()
    try:
        if args.command == "configure-trigger":
            result = configure_trigger(db, args.thread)
        elif args.command == "ingest":
            try:
                # Registry errors do not block existing Korean/Telegram requests.
                today = datetime.now(timezone.utc).date().isoformat()
                if setting(db, "registry_day") != today:
                    from telegram_bridge.jarvis_registry import sync_registry
                    try:
                        registry = sync_registry()
                        save_setting(db, "registry_day", today)
                        save_setting(db, "registry_error", "")
                    except Exception as exc:
                        save_setting(db, "registry_error", type(exc).__name__)
                        # Retry at most daily; explicit jarvis_registry command can retry immediately.
                        save_setting(db, "registry_day", today)
                count = sync_pending(db)
                confirmations = sync_folder_confirmations(db)
                wake = wake_pending(db)
            except Exception as exc:
                save_setting(db, "last_error", type(exc).__name__)
                raise
            save_setting(db, "last_success", datetime.now(timezone.utc).isoformat())
            save_setting(db, "last_error", "")
            result = {"mirrored": count, "confirmations": confirmations, "wake": wake}
        elif args.command == "poll":
            result = poll(db)
        elif args.command == "status":
            result = {"queue": poll(db), "bot_id": bot_id_of(TelegramClient().token)}
        elif args.command == "checkpoint":
            result = {"status": "working", "id": args.id,
                      "checkpoint": str(ensure_checkpoint(db, args.id))}
        elif args.command == "claim":
            result = claim(db, args.id)
        elif args.command == "reject":
            result = reject(db, args.id)
        elif args.command == "fail":
            result = fail(db, args.id, args.reason)
        elif args.command == "progress":
            result = set_progress(db, args.id, args.stage)
        elif args.command == "ask-folder":
            if args.json_stdin:
                folder_input = json.load(sys.stdin)
                folder_name = folder_input.get("folder_name")
                folder_url = folder_input.get("folder_url")
            else:
                folder_name, folder_url = args.folder_name, args.folder_url
            if not isinstance(folder_name, str) or not isinstance(folder_url, str):
                raise ValueError("MISSING_FOLDER_INPUT")
            result = ask_folder(db, args.id, folder_name, folder_url)
        else:
            result = deliver(db, args.id, args.notion, args.industry)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"error": str(exc) if isinstance(exc, (RuntimeError, ValueError))
                          else type(exc).__name__}, ensure_ascii=False))
        raise SystemExit(1) from None
