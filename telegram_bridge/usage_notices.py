# PRD Ref: §8.7 L · SC: 사용량 대기/재개 주기별 1회, JARVIS 무발송
"""Durable notification reservations, shared by Codex and Claude."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from src.notify.telegram import TelegramClient, bot_id_of

STATE = Path(__file__).with_name('state') / 'usage_notices.sqlite3'


def usage_event(key: str, owner: dict, paused: bool, provider: str, retry_after: str = '') -> dict:
    if owner.get('source') != 'telegram':
        return {'notification': 'suppressed'}
    from src.notify.listen import allowed_chats
    if str(owner.get('chat_id')) not in allowed_chats():
        return {'notification': 'suppressed'}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(STATE, timeout=30) as db:
        db.executescript('CREATE TABLE IF NOT EXISTS states (key TEXT PRIMARY KEY, paused INTEGER NOT NULL, cycle INTEGER NOT NULL);'
                        'CREATE TABLE IF NOT EXISTS events (key TEXT, cycle INTEGER, phase TEXT, delivery TEXT, message_id INTEGER, checked_at TEXT, PRIMARY KEY(key,cycle,phase));')
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT paused,cycle FROM states WHERE key=?', (key,)).fetchone()
        if (not row and not paused) or (row and bool(row[0]) == paused):
            return {'notification': 'unchanged'}
        cycle = (row[1] if row else 0) + int(paused)
        phase = 'paused' if paused else 'resumed'
        db.execute('INSERT INTO states VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET paused=excluded.paused,cycle=excluded.cycle', (key, int(paused), cycle))
        db.execute('INSERT INTO events VALUES(?,?,?,\'reserved\',NULL,?)', (key, cycle, phase, datetime.now(timezone.utc).isoformat()))
    name = owner.get('target_name') or owner.get('company_name') or owner.get('company') or owner.get('industry') or ''
    reset_text = ''
    if retry_after:
        try:
            from zoneinfo import ZoneInfo
            reset_text = '\n다음 재개 확인: ' + datetime.fromisoformat(retry_after.replace('Z', '+00:00')).astimezone(ZoneInfo('Asia/Seoul')).strftime('%m/%d %H:%M KST')
        except ValueError:
            pass
    text = (f'⏸ {name} {provider} 사용량 제한으로 분석을 일시 중지했습니다.\n원고·출처·저장 상태를 보존했습니다. 사용 가능량이 회복되면 같은 작업을 자동으로 이어갑니다.{reset_text}' if paused
            else f'▶️ {name} {provider} 기존 분석의 재개를 시도합니다.\n한도가 아직 부족하면 다시 대기하며, 완료 후 Notion 링크를 보내드립니다.')
    delivery, message_id = 'uncertain', None
    try:
        client = TelegramClient(chat_id=str(owner['chat_id']))
        if bot_id_of(client.token) != '8933940541':
            raise ValueError('DEDICATED_BOT_REQUIRED')
        response = client.call('sendMessage', {'chat_id': owner['chat_id'], 'text': text, 'disable_web_page_preview': True})
        message_id, delivery = response['result']['message_id'], 'sent'
    except Exception:
        pass  # Ambiguous sends are reserved and never replayed.
    with sqlite3.connect(STATE, timeout=30) as db:
        db.execute('UPDATE events SET delivery=?,message_id=? WHERE key=? AND cycle=? AND phase=?', (delivery, message_id, key, cycle, phase))
    return {'notification': delivery}
