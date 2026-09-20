# PRD Ref: §8.1 · SC: 전용 봇을 1분마다 단일 로컬 수신기로 처리
"""Windows 예약 작업의 Telegram 수신 단위. 결과를 파일로 남긴다."""

from __future__ import annotations

from datetime import datetime, timezone
import argparse
import json
import os
from pathlib import Path
import sys

# 예약 작업의 시작 디렉터리는 프로젝트 루트가 아니다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.notify.listen import allowed_chats, load_universe, poll_once
from src.notify.telegram import TelegramClient, bot_id_of
from telegram_bridge.bridge import HEIMDALLR_BOT_ID


ROOT = Path(__file__).resolve().parent
HEALTH = ROOT / "state" / "listener_last.json"


def main(*, check: bool = False) -> int:
    now = datetime.now(timezone.utc).isoformat()
    try:
        client = TelegramClient()
        if bot_id_of(client.token) != HEIMDALLR_BOT_ID:
            raise RuntimeError("HEIMDALLR_BOT_ID_MISMATCH")
        chats = allowed_chats()
        universe = load_universe()
        if not chats or not universe:
            raise RuntimeError("LISTENER_PREFLIGHT_EMPTY")
        if check:
            print(json.dumps({"status": "ready", "bot_id": HEIMDALLR_BOT_ID,
                              "allowed_chats": len(chats), "universe": len(universe)}))
            return 0
        results = poll_once(client, analyze=False, universe=universe, chats=chats)
        state = {"last_success": now, "count": len(results), "last_error": ""}
        code = 0
    except Exception as exc:
        state = {"last_success": None, "count": 0, "last_error": type(exc).__name__,
                 "failed_at": now}
        code = 1
    HEALTH.parent.mkdir(parents=True, exist_ok=True)
    temp = HEALTH.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, HEALTH)
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    raise SystemExit(main(check=parser.parse_args().check))
