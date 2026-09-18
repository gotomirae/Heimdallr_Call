# PRD Ref: §8 · SC: 인증된 Telegram 요청만 Kairos에 한 번 전달
"""Supabase 수신함을 로컬 큐로 옮겨 Codex를 깨운다. Telegram은 폴링하지 않는다.

    python -m telegram_bridge.bridge ingest
    python -m telegram_bridge.bridge poll
    python -m telegram_bridge.bridge claim UPDATE_ID
    python -m telegram_bridge.bridge deliver UPDATE_ID --notion URL --industry NAME
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys

from src.db.supabase_client import get_client, select_all
from src.notify.listen import allowed_chats
from src.notify.telegram import TelegramClient, bot_id_of


ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state" / "queue.sqlite3"
HEIMDALLR_BOT_ID = "8933940541"
TABLE = "kairos_requests"


def connect() -> sqlite3.Connection:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(STATE, timeout=30)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY, code TEXT NOT NULL, company TEXT NOT NULL,
            raw_text TEXT NOT NULL, chat_id INTEGER NOT NULL, status TEXT NOT NULL,
            notion_url TEXT, telegram_message_id INTEGER,
            wake_sent INTEGER NOT NULL DEFAULT 0, wake_sent_at TEXT, wake_error TEXT
        );
    """)
    columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
    if "wake_sent_at" not in columns:
        db.execute("ALTER TABLE jobs ADD COLUMN wake_sent_at TEXT")
    return db


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
    save_setting(db, "trigger_thread", thread_id)
    return {"status": "configured", "thread_id": thread_id}


def verify_bot() -> None:
    # 현재 봇만 수신된 요청에 응답한다. 다른 토큰으로 배포되면 조용히 섞이지 않는다.
    if bot_id_of(TelegramClient().token) != HEIMDALLR_BOT_ID:
        raise RuntimeError("HEIMDALLR_BOT_ID_MISMATCH")


def sync_pending(db: sqlite3.Connection) -> int:
    """GitHub 수신기가 기록한 pending만 로컬에 복사한다. Telegram API는 호출하지 않는다."""
    verify_bot()
    chats = allowed_chats()
    rows = select_all(
        TABLE, "update_id,chat_id,user_id,code,company_name,raw_text,status",
        filters={"status": "pending"}, order="update_id",
    )
    added = 0
    with db:
        for row in rows:
            # 클라우드 테이블이 손상돼도 인증 조건이 없는 요청은 깨우지 않는다.
            if str(row["chat_id"]) not in chats or row["user_id"] != row["chat_id"]:
                continue
            cursor = db.execute(
                "INSERT OR IGNORE INTO jobs(id,code,company,raw_text,chat_id,status) "
                "VALUES(?,?,?,?,?,'pending')",
                (row["update_id"], row["code"], row["company_name"],
                 row["raw_text"], row["chat_id"]),
            )
            added += cursor.rowcount
    return added


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
    busy = db.execute(
        "SELECT id FROM jobs WHERE status IN ('working','sending','uncertain') LIMIT 1"
    ).fetchone()
    if busy:
        return {"status": "busy", "id": busy[0]}
    queued = db.execute(
        "SELECT id FROM jobs WHERE status='pending' AND wake_sent=1 ORDER BY id LIMIT 1"
    ).fetchone()
    if queued:
        return {"status": "already_queued", "id": queued[0]}
    row = db.execute(
        "SELECT id FROM jobs WHERE status='pending' AND wake_sent=0 ORDER BY id LIMIT 1"
    ).fetchone()
    if not row:
        return {"status": "idle"}
    codex = find_codex()
    if not codex:
        return {"status": "error", "id": row[0], "error": "CODEX_NOT_FOUND"}
    message = (
        f"Heimdallr Telegram 기업분석 요청 {row[0]}가 등록되었습니다. "
        "이 프로젝트의 `python -m telegram_bridge.bridge poll`로 실제 요청을 확인하고, "
        "기업·티커를 공식 출처로 식별한 뒤 `claim ID`가 성공하면 $kairos 스킬로 "
        "Google Drive·공시·웹·증권사 리포트를 조사해 지정 Notion 양식에 작성하세요. "
        "저장 결과를 재조회한 다음 `deliver ID --notion URL --industry 산업명`으로 링크를 보내세요. "
        "요청이 기업명이 아니면 `reject ID`로 제외하세요."
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
    return {"status": "queued", "id": row[0]}


def poll(db: sqlite3.Connection) -> dict:
    """Codex 쪽 조회는 로컬 큐만 읽는다."""
    rows = db.execute(
        "SELECT id,code,company,raw_text,status,notion_url,wake_sent,wake_sent_at,wake_error "
        "FROM jobs WHERE status NOT IN ('sent','rejected') ORDER BY id LIMIT 20"
    ).fetchall()
    return {"trigger_configured": bool(setting(db, "trigger_thread")),
            "collector": {"last_success": setting(db, "last_success"),
                          "last_error": setting(db, "last_error")},
            "jobs": [dict(row) for row in rows]}


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
        "SELECT id FROM jobs WHERE status IN ('working','sending','uncertain') LIMIT 1"
    ).fetchone()
    if busy:
        return {"status": "busy", "id": busy[0]}
    if not change_remote(job_id, "pending", "working",
                         claimed_at=datetime.now(timezone.utc).isoformat()):
        return {"status": "not_claimed", "id": job_id}
    with db:
        db.execute("UPDATE jobs SET status='working' WHERE id=?", (job_id,))
    return {"status": "claimed", "id": job_id}


def reject(db: sqlite3.Connection, job_id: int) -> dict:
    if not change_remote(job_id, "pending", "rejected", error="Not a company or ticker"):
        return {"status": "not_rejected", "id": job_id}
    with db:
        db.execute("UPDATE jobs SET status='rejected' WHERE id=?", (job_id,))
    return {"status": "rejected", "id": job_id}


def deliver(db: sqlite3.Connection, job_id: int, notion: str, industry: str) -> dict:
    if not re.fullmatch(r"https://(?:www\.)?notion\.so/\S+|https://app\.notion\.com/p/\S+", notion):
        raise ValueError("INVALID_NOTION_URL")
    if not 1 <= len(industry.strip()) <= 100 or "\n" in industry or "\r" in industry:
        raise ValueError("INVALID_INDUSTRY")
    row = db.execute(
        "SELECT company,chat_id,status FROM jobs WHERE id=?", (job_id,)
    ).fetchone()
    if not row or row["status"] != "working":
        raise RuntimeError("NOT_WORKING_OR_ALREADY_SENT")
    verify_bot()
    client = TelegramClient(chat_id=str(row["chat_id"]))
    if not change_remote(job_id, "working", "sending",
                         notion_url=notion, industry=industry.strip()):
        raise RuntimeError("REMOTE_JOB_NOT_WORKING")
    with db:
        db.execute("UPDATE jobs SET status='sending',notion_url=? WHERE id=?",
                   (notion, job_id))
    try:
        result = client.call("sendMessage", {
            "chat_id": row["chat_id"],
            "text": (
                "📑 Kairos 기업 분석이 완료되었습니다.\n\n"
                f"🏭 산업: {industry.strip()}\n🏢 기업: {row['company']}\n\n{notion}"
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
    return {"status": "sent", "id": job_id, "telegram_message_id": message_id}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("poll")
    sub.add_parser("ingest")
    sub.add_parser("status")
    trigger = sub.add_parser("configure-trigger")
    trigger.add_argument("--thread", required=True)
    for command in ("claim", "reject"):
        sub.add_parser(command).add_argument("id", type=int)
    delivery = sub.add_parser("deliver")
    delivery.add_argument("id", type=int)
    delivery.add_argument("--notion", required=True)
    delivery.add_argument("--industry", required=True)
    args = parser.parse_args()
    db = connect()
    try:
        if args.command == "configure-trigger":
            result = configure_trigger(db, args.thread)
        elif args.command == "ingest":
            try:
                count = sync_pending(db)
                wake = wake_pending(db)
            except Exception as exc:
                save_setting(db, "last_error", type(exc).__name__)
                raise
            save_setting(db, "last_success", datetime.now(timezone.utc).isoformat())
            save_setting(db, "last_error", "")
            result = {"mirrored": count, "wake": wake}
        elif args.command == "poll":
            result = poll(db)
        elif args.command == "status":
            result = {"queue": poll(db), "bot_id": bot_id_of(TelegramClient().token)}
        elif args.command == "claim":
            result = claim(db, args.id)
        elif args.command == "reject":
            result = reject(db, args.id)
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
