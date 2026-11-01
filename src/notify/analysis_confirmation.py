# PRD Ref: §8.7 · ADR50 — 이름 입력은 대상 선택, 분석 버튼만 생성 승인.
from dataclasses import asdict
import json
from pathlib import Path
import re
import sqlite3

from src.notify.kairos_requests import AnalysisTarget, enqueue

STATE = Path(__file__).resolve().parents[2] / "telegram_bridge/state/analysis-confirmations.sqlite3"
CALLBACK = re.compile(r"^pro:analyze:([0-9]+)$")


def connect():
    STATE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(STATE, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS proposals (id INTEGER PRIMARY KEY, chat_id TEXT NOT NULL, user_id TEXT NOT NULL, message TEXT NOT NULL, target TEXT NOT NULL)")
    return db


def propose(client, update_id: int, message: dict, target: AnalysisTarget) -> dict:
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO proposals VALUES(?,?,?,?,?)", (update_id, str(message["chat"]["id"]),
                   str(message["from"]["id"]), json.dumps(message), json.dumps(asdict(target))))
    client.send_message(f"{target.name}\n분석을 눌러야 보고서 작성·갱신을 시작합니다. 같은 근거는 기존 결과를 재사용합니다.",
                        parse_mode=None, reply_markup={"inline_keyboard": [[{"text": "분석", "callback_data": f"pro:analyze:{update_id}"}]]})
    return {"result": "분석 버튼 대기", "id": update_id}


def handle(client, callback: dict, chats: set[str]) -> dict | None:
    match = CALLBACK.fullmatch(callback.get("data", ""))
    if not match:
        return None
    identity = int(match[1])
    with connect() as db:
        row = db.execute("SELECT * FROM proposals WHERE id=?", (identity,)).fetchone()
    message = callback.get("message", {})
    chat = message.get("chat", {})
    sender = callback.get("from", {})
    if (not row or str(chat.get("id")) not in chats or chat.get("type") != "private"
            or str(chat.get("id")) != row["chat_id"] or str(sender.get("id")) != row["user_id"]
            or sender.get("is_bot")):
        return {"result": "분석 버튼 권한 없음"}
    # Repeated delivery uses the original unique update_id, so cannot create two analyses.
    created = enqueue(identity, json.loads(row["message"]), AnalysisTarget(**json.loads(row["target"])))
    client.call("answerCallbackQuery", {"callback_query_id": callback["id"], "text": "분석 접수" if created else "기존 요청 확인"})
    return {"result": "분석 접수" if created else "기존 요청", "id": identity}
