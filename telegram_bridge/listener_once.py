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

from src.config.constants import KAIROS_LISTENER_CATALOG_CACHE_SECONDS
from src.db.supabase_client import service_error_code
from src.notify.listen import allowed_chats, load_catalogs, poll_once
from src.notify.telegram import TelegramClient, bot_id_of
from telegram_bridge.bridge import HEIMDALLR_BOT_ID


ROOT = Path(__file__).resolve().parent
HEALTH = ROOT / "state" / "listener_last.json"
CATALOG = ROOT / "state" / "listener_catalog.json"


def load_listener_catalogs(*, refresh: bool = False) -> tuple[dict[str, str], set[str]]:
    """매분 전체 명부 전송을 피한다. 만료·불완전 캐시는 실제 DB에서 갱신한다."""
    now = datetime.now(timezone.utc)
    if not refresh:
        try:
            cached = json.loads(CATALOG.read_text(encoding="utf-8"))
            age = (now - datetime.fromisoformat(cached["checked_at"])).total_seconds()
            universe, industries = cached["universe"], cached["industries"]
            if (
                cached.get("version") == 1
                and 0 <= age < KAIROS_LISTENER_CATALOG_CACHE_SECONDS
                and isinstance(universe, dict) and universe
                and all(isinstance(k, str) and len(k) == 6 and k.isdigit()
                        and isinstance(v, str) and v for k, v in universe.items())
                and isinstance(industries, list) and industries
                and all(isinstance(v, str) and v for v in industries)
            ):
                return universe, set(industries)
        except (OSError, ValueError, KeyError, TypeError):
            pass
    # DB 조회 실패는 전달한다. 오래된 명부로 접수하거나 update를 확인하지 않는다.
    universe, industries = load_catalogs()
    if not universe or not industries:
        raise RuntimeError("LISTENER_PREFLIGHT_EMPTY")
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    temp = CATALOG.with_suffix(".tmp")
    temp.write_text(json.dumps({"version": 1, "checked_at": now.isoformat(),
                               "universe": universe, "industries": sorted(industries)},
                              ensure_ascii=False), encoding="utf-8")
    os.replace(temp, CATALOG)
    return universe, industries


def main(*, check: bool = False) -> int:
    now = datetime.now(timezone.utc).isoformat()
    try:
        client = TelegramClient()
        if bot_id_of(client.token) != HEIMDALLR_BOT_ID:
            raise RuntimeError("HEIMDALLR_BOT_ID_MISMATCH")
        chats = allowed_chats()
        universe, industries = load_listener_catalogs(refresh=check)
        if not chats or not universe or not industries:
            raise RuntimeError("LISTENER_PREFLIGHT_EMPTY")
        if check:
            print(json.dumps({"status": "ready", "bot_id": HEIMDALLR_BOT_ID,
                              "allowed_chats": len(chats), "universe": len(universe),
                              "industries": len(industries)}))
            return 0
        results = poll_once(
            client, analyze=False, universe=universe, industries=industries, chats=chats
        )
        state = {"last_success": now, "count": len(results), "last_error": ""}
        code = 0
    except Exception as exc:
        state = {"last_success": None, "count": 0, "last_error": service_error_code(exc),
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
