# PRD Ref: §8.7 K·N · SC: 자동 Claude 인계·검증 후 사용자 PPT 버튼 접수
"""Automatic file handoff and authorized PPT continuation of the Claude worker."""
from __future__ import annotations

from pathlib import Path
import re
import sqlite3

from src.db.supabase_client import get_client
from src.notify.telegram import TelegramClient, bot_id_of

STATE = Path(__file__).resolve().parents[2] / 'telegram_bridge/state/followups.sqlite3'
BOT_ID = '8933940541'
CALLBACK = re.compile(r'^kairos:(analysis|deck):([1-9][0-9]{0,18})$')


def connect():
    STATE.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(STATE, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS notices (job_id INTEGER PRIMARY KEY, request_id INTEGER NOT NULL, mode TEXT NOT NULL, chat_id INTEGER NOT NULL, status TEXT, delivery TEXT, message_id INTEGER, error TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS progress_notices (job_id INTEGER NOT NULL, phase TEXT NOT NULL, delivery TEXT NOT NULL, message_id INTEGER, PRIMARY KEY(job_id,phase))')
    return db


def keyboard(request_id: int, url: str, mode: str = 'deck') -> dict:
    label = '🧠 분석' if mode == 'analysis' else '🎤 PPT 발표자료 만들기'
    return {'inline_keyboard': [
        [{'text': '📝 Notion 분석 열기', 'url': url}],
        [{'text': label, 'callback_data': f'kairos:{mode}:{request_id}'}],
    ]}


def request_row(request_id: int) -> dict | None:
    rows = get_client().table('kairos_requests').select('*').eq('update_id', request_id).limit(1).execute().data
    return rows[0] if rows else None


def latest_job(request_id: int, mode: str) -> dict | None:
    rows = (get_client().table('kairos_deck_requests').select('*')
            .eq('request_id', request_id).eq('mode', mode).order('id', desc=True).limit(1).execute().data)
    return rows[0] if rows else None


def remember(job: dict, owner: dict):
    if owner.get('source') != 'telegram':
        return  # JARVIS finalization is repaired by collector; never starve Telegram notices.
    with connect() as db:
        db.execute('INSERT OR IGNORE INTO notices(job_id,request_id,mode,chat_id) VALUES(?,?,?,?)',
                   (job['id'], owner['update_id'], job['mode'], owner['chat_id']))


def notify_codex(owner: dict, event: str, client: TelegramClient | None = None) -> int:
    """New milestone messages; request/event reservations survive handoff replay."""
    from src.notify.listen import allowed_chats
    if event not in {'started', 'completed'}:
        raise ValueError('INVALID_CODEX_EVENT')
    if owner.get('source') != 'telegram' or str(owner.get('chat_id')) not in allowed_chats():
        return 0
    if owner.get('status') not in {'working', 'claude'}:
        return 0
    client = client or TelegramClient(chat_id=str(owner['chat_id']))
    if bot_id_of(client.token) != BOT_ID:
        return 0
    request_id = owner.get('update_id', owner.get('id'))
    phase = f'codex_{event}'
    with connect() as db:
        inserted = db.execute("INSERT OR IGNORE INTO progress_notices(job_id,phase,delivery) VALUES(?,?,'reserved')", (request_id, phase)).rowcount
    if not inserted:
        return 0
    name = owner.get('target_name') or owner.get('company_name') or owner.get('company') or owner.get('industry')
    text = (f'🔎 {name} Codex 분석을 시작했습니다.\n공식 자료·기존 분석을 조사하고 원고를 작성합니다.' if event == 'started'
            else f'✅ {name} Codex 분석이 완료되었습니다.\n원고·출처·표·차트를 저장했습니다. Codex가 원문·수치를 검수하고 게시합니다.')
    try:
        response = client.call('sendMessage', {'chat_id': owner['chat_id'], 'text': text, 'disable_web_page_preview': True})
        with connect() as db:
            db.execute("UPDATE progress_notices SET delivery='sent',message_id=? WHERE job_id=? AND phase=?", (response['result']['message_id'], request_id, phase))
        return 1
    except Exception:
        with connect() as db:
            db.execute("UPDATE progress_notices SET delivery='uncertain' WHERE job_id=? AND phase=?", (request_id, phase))
        return 0


def notify_progress(job: dict, owner: dict, client: TelegramClient | None = None) -> int:
    """Durable, once-per-job receipt/start messages, independent of completion."""
    from src.notify.listen import allowed_chats
    phase = {'pending': 'received', 'working': 'started'}.get(job.get('status'))
    ready = owner.get('status') == 'sent' or (owner.get('status') == 'working' and owner.get('stage') == 'claude')
    if not phase or owner.get('source') != 'telegram' or not ready:
        return 0
    with connect() as db:
        watched = db.execute('SELECT 1 FROM notices WHERE job_id=? AND request_id=? AND chat_id=?',
                             (job['id'], owner['update_id'], owner['chat_id'])).fetchone()
    if not watched or str(owner['chat_id']) not in allowed_chats():
        return 0
    client = client or TelegramClient(chat_id=str(owner['chat_id']))
    if bot_id_of(client.token) != BOT_ID:
        return 0
    with connect() as db:
        inserted = db.execute("INSERT OR IGNORE INTO progress_notices(job_id,phase,delivery) VALUES(?,?,'reserved')", (job['id'], phase)).rowcount
    if not inserted:
        return 0
    label = 'Codex 검수' if job['mode'] == 'analysis' else 'PPT 발표자료'
    name = owner.get('target_name') or owner.get('company_name') or owner.get('industry')
    text = (f'📥 {name} {label} 요청을 접수했습니다.\n현재 실행 대기 중이며, 실제 시작되면 알려드립니다.' if phase == 'received'
            else f'🧠 {name} {label}을 시작했습니다.\n완료되면 Notion 링크를 보내드립니다.')
    try:
        response = client.call('sendMessage', {'chat_id': owner['chat_id'], 'text': text, 'disable_web_page_preview': True})
        with connect() as db:
            db.execute("UPDATE progress_notices SET delivery='sent',message_id=? WHERE job_id=? AND phase=?", (response['result']['message_id'], job['id'], phase))
        return 1
    except Exception:
        # A timeout may already have delivered; never replay an ambiguous send.
        with connect() as db:
            db.execute("UPDATE progress_notices SET delivery='uncertain' WHERE job_id=? AND phase=?", (job['id'], phase))
        return 0


def authorize(callback: dict, row: dict | None, mode: str, chats: set[str]) -> bool:
    message = callback.get('message') or {}
    chat = message.get('chat') or {}
    sender = callback.get('from') or {}
    bot = message.get('from') or {}
    if (not row or row.get('source') != 'telegram' or row.get('status') != 'sent'
            or not row.get('notion_url') or str(chat.get('id')) not in chats
            or chat.get('type') != 'private' or sender.get('is_bot')
            or str(sender.get('id')) != str(row.get('user_id'))
            or str(chat.get('id')) != str(row.get('chat_id'))
            or str(bot.get('id')) != BOT_ID or bot.get('is_bot') is not True):
        return False
    if mode == 'analysis':
        return message.get('message_id') == row.get('telegram_message_id')
    # A PPT button is issued only on a delivered Claude completion notice.
    with connect() as db:
        return db.execute("SELECT 1 FROM notices WHERE request_id=? AND mode='analysis' AND status='sent' AND delivery='sent' AND message_id=? AND chat_id=?",
                          (row['update_id'], message.get('message_id'), row['chat_id'])).fetchone() is not None


def enqueue_followup(owner: dict, mode: str) -> dict:
    if mode == 'deck':
        prior = latest_job(owner['update_id'], 'analysis')
        if not prior or prior['status'] != 'sent' or not prior.get('analysis_md') or not prior.get('notion_url'):
            return {'status': 'rejected', 'reason': 'Codex 검수 완료 후 PPT를 요청해 주세요.'}
    job = latest_job(owner['update_id'], mode)
    if job and job['status'] in {'pending', 'working', 'sent'}:
        remember(job, owner)
        return job
    try:
        rows = get_client().table('kairos_deck_requests').insert({'request_id': owner['update_id'], 'mode': mode}).execute().data
        job = rows[0]
    except Exception as exc:
        if str(getattr(exc, 'code', '')) != '23505':
            raise
        # Existing unique(request_id, mode) index wins concurrent/replayed clicks.
        job = latest_job(owner['update_id'], mode)
        if not job or job['status'] not in {'pending', 'working', 'sent'}:
            raise
    remember(job, owner)
    return job


def handle_callback(client: TelegramClient, callback: dict, chats: set[str]) -> dict:
    match = CALLBACK.fullmatch(callback.get('data') or '')
    if not match or bot_id_of(client.token) != BOT_ID:
        return {'result': '무시(지원하지 않는 버튼)'}
    mode, request_id = match[1], int(match[2])
    row = request_row(request_id)
    if not authorize(callback, row, mode, chats):
        client.call('answerCallbackQuery', {'callback_query_id': callback['id'], 'text': '본인의 완료된 분석 버튼만 사용할 수 있습니다.', 'show_alert': True})
        return {'result': '후속 요청 인증 거부'}
    job = enqueue_followup(row, mode)
    labels = {'pending': '접수했습니다. 기존 실행기가 순서대로 처리합니다.', 'working': '이미 진행 중입니다.',
              'sent': '이미 완료되었습니다. 완료 링크를 확인해 주세요.', 'rejected': job.get('reason', '분석 완료를 기다려 주세요.')}
    acknowledged = True
    try:
        client.call('answerCallbackQuery', {'callback_query_id': callback['id'], 'text': labels.get(job['status'], '상태 확인 필요'), 'show_alert': True})
    except Exception:
        # The durable job already exists. An expired callback toast must not
        # trap the listener on this offset or block later company requests.
        acknowledged = False
    if job['status'] in {'pending', 'working'}:
        try:
            notify_progress(job, row, client)
        except Exception:
            pass  # Durable queue acceptance survives a notification outage.
    return {'result': '분석 후속 버튼 처리', 'request_id': request_id, 'mode': mode, 'status': job['status'], 'acknowledged': acknowledged}


def flush_notifications() -> dict:
    """Watched automatic/legacy jobs. Reserve before send; ambiguous sends never retry."""
    from src.notify.listen import allowed_chats
    with connect() as db:
        watched = [dict(r) for r in db.execute("SELECT * FROM notices WHERE delivery IS NULL ORDER BY job_id LIMIT 50")]
    sent = 0
    for notice in watched:
        rows = get_client().table('kairos_deck_requests').select('*').eq('id', notice['job_id']).limit(1).execute().data
        if not rows:
            continue
        job = rows[0]
        owner = request_row(notice['request_id'])
        if owner:
            from telegram_bridge.file_first import finalize
            owner = finalize(job, owner)
        if (not owner or owner.get('source') != 'telegram' or owner['status'] not in {'sent', 'working', 'failed'}
                or str(owner['chat_id']) not in allowed_chats() or owner['chat_id'] != notice['chat_id']):
            continue
        if job['status'] in {'pending', 'working'}:
            if job.get('error') == 'USAGE':
                from telegram_bridge.usage_notices import usage_event
                usage_event(f'{"A" if job["mode"] == "analysis" else "D"}{job["id"]}', owner, True, 'Codex Pro', job.get('retry_after') or '')
            sent += notify_progress(job, owner)
            continue
        if job['status'] not in {'sent', 'failed'}:
            continue
        if job['status'] == 'sent' and (owner['status'] != 'sent' or not job.get('notion_url')):
            continue
        with connect() as db:
            changed = db.execute("UPDATE notices SET delivery='reserved',status=? WHERE job_id=? AND delivery IS NULL", (job['status'], job['id'])).rowcount
        if not changed:
            continue
        try:
            client = TelegramClient(chat_id=str(owner['chat_id']))
            if bot_id_of(client.token) != BOT_ID:
                raise ValueError('DEDICATED_BOT_REQUIRED')
            label = 'Codex 검수' if job['mode'] == 'analysis' else 'PPT 발표자료'
            name = owner.get('target_name') or owner.get('company_name') or owner.get('industry')
            if job['status'] == 'sent':
                text = f'✅ {name} {label} 완료\n\n{job["notion_url"]}'
                markup = (keyboard(owner['update_id'], job['notion_url'], 'deck') if job['mode'] == 'analysis'
                          else {'inline_keyboard': [[{'text': '📊 Notion에서 PPT 열기', 'url': job['notion_url']}]]})
            else:
                from telegram_bridge.file_first import is_file_first
                recovery = ('Codex 원고·출처는 보존되어 있습니다. 오류 해소 후 동일 작업을 복구할 수 있습니다.'
                            if is_file_first(owner['update_id']) else '연결·로그인·자료를 확인한 뒤 원래 버튼으로 다시 요청할 수 있습니다.')
                text = f'⚠️ {name} {label} 실패\n원인: {job.get("error") or "UNEXPECTED"}\n{recovery}'
                markup = None
            payload = {'chat_id': owner['chat_id'], 'text': text, 'disable_web_page_preview': True}
            if markup:
                payload['reply_markup'] = markup
            result = client.call('sendMessage', payload)
            with connect() as db:
                db.execute("UPDATE notices SET delivery='sent',message_id=? WHERE job_id=?", (result['result']['message_id'], job['id']))
            sent += 1
        except Exception as exc:
            with connect() as db:
                db.execute("UPDATE notices SET delivery='uncertain',error=? WHERE job_id=?", (type(exc).__name__, job['id']))
    return {'sent': sent, 'watched': len(watched)}


def install_buttons(request_id: int) -> dict:
    """Explicit retrofit of an actual sent message; does not enqueue an analysis."""
    from src.notify.listen import allowed_chats
    row = request_row(request_id)
    if (not row or row.get('source') != 'telegram' or row['status'] != 'sent'
            or str(row['chat_id']) not in allowed_chats() or not row.get('telegram_message_id')):
        raise ValueError('SENT_TELEGRAM_REQUEST_REQUIRED')
    client = TelegramClient(chat_id=str(row['chat_id']))
    if bot_id_of(client.token) != BOT_ID:
        raise ValueError('DEDICATED_BOT_REQUIRED')
    response = client.call('editMessageReplyMarkup', {'chat_id': row['chat_id'], 'message_id': row['telegram_message_id'],
                 'reply_markup': keyboard(request_id, row['notion_url'])})
    actual = (response.get('result') or {}).get('reply_markup')
    if actual != keyboard(request_id, row['notion_url']):
        raise ValueError('TELEGRAM_BUTTON_READBACK_FAILED')
    return {'request_id': request_id, 'message_id': row['telegram_message_id'], 'buttons_installed': True, 'reply_markup': actual}
