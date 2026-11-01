# PRD Ref: §8.7 N · SC: Codex 원고 보존→자동 Claude→최종 Notion→사용자 PPT 승인
"""File-first handoff. Parent remains working until verified Claude completion."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

PIPELINE = 'file-first-v1'


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def package_path(request_id: int) -> Path:
    from telegram_bridge.bridge import checkpoint_path
    return checkpoint_path(request_id).with_name(f'{request_id}-handoff.json')


def is_file_first(request_id: int) -> bool:
    try:
        return json.loads(package_path(request_id).read_text(encoding='utf-8')).get('pipeline') == PIPELINE
    except (OSError, ValueError):
        return False


def validate_files(data: dict, request_id: int, roots=None) -> dict:
    from telegram_bridge.research_handoff import validate_package
    from telegram_bridge.bridge import STATE
    from src.collectors.drive_bootstrap import DRIVE_ROOT
    validate_package(data, request_id)
    if data.get('pipeline') != PIPELINE:
        raise ValueError('FILE_HANDOFF_PIPELINE_REQUIRED')
    roots = [Path(p).resolve() for p in (roots or [STATE.parent, DRIVE_ROOT])]

    def check(item):
        if not isinstance(item, dict) or not isinstance(item.get('path'), str):
            raise ValueError('FILE_HANDOFF_MANIFEST_INVALID')
        path = Path(item['path'])
        if not path.is_absolute():
            raise ValueError('FILE_HANDOFF_ABSOLUTE_PATH_REQUIRED')
        path = path.resolve()
        if not any(path.is_relative_to(root) for root in roots) or not path.is_file():
            raise ValueError('FILE_HANDOFF_FILE_MISSING_OR_OUTSIDE')
        if digest(path) != item.get('sha256'):
            raise ValueError('FILE_HANDOFF_HASH_MISMATCH')
        return path

    draft = check(data.get('draft'))
    template = data.get('template')
    template_path = check(template)
    titles = template.get('section_titles')
    if not isinstance(titles, list) or not titles or not all(isinstance(s, str) and s.strip() for s in titles):
        raise ValueError('FILE_HANDOFF_TEMPLATE_REQUIRED')
    text = draft.read_text(encoding='utf-8')
    snapshot = json.loads(template_path.read_text(encoding='utf-8'))
    if not snapshot.get('page', {}).get('id') or not snapshot.get('blocks', {}).get('results') or snapshot.get('blocks', {}).get('has_more') is not False:
        raise ValueError('FILE_HANDOFF_TEMPLATE_READBACK_REQUIRED')
    offset = 0
    for title in titles:
        position = text.find(title, offset)
        if position < 0:
            raise ValueError('FILE_HANDOFF_SECTION_MISSING')
        offset = position + len(title)
    if not isinstance(data.get('thesis'), dict) or not data['thesis']:
        raise ValueError('FILE_HANDOFF_THESIS_REQUIRED')
    if not isinstance(data.get('artifacts'), list) or not data['artifacts']:
        raise ValueError('FILE_HANDOFF_ARTIFACTS_REQUIRED')
    for item in data['artifacts']:
        check(item)
    return data


def submit(db, request_id: int, industry: str) -> dict:
    from telegram_bridge import bridge
    from src.notify.kairos_followups import enqueue_followup, latest_job, request_row
    row = db.execute('SELECT * FROM jobs WHERE id=?', (request_id,)).fetchone()
    if not row or row['status'] not in {'working', 'claude'}:
        raise RuntimeError('NOT_WORKING_OR_ALREADY_COMPLETE')
    data = validate_files(json.loads(package_path(request_id).read_text(encoding='utf-8')), request_id)
    previous = latest_job(request_id, 'analysis')
    if previous and previous['status'] == 'failed':
        raise RuntimeError('CLAUDE_TERMINAL_NEEDS_RECOVERY')
    industry = industry.strip() or (row['target_name'] if row['request_kind'] == 'industry' else '')
    if not industry or len(industry) > 100 or '\n' in industry or '\r' in industry:
        raise ValueError('INVALID_INDUSTRY')
    now = datetime.now(timezone.utc).isoformat()
    # Durable local intent before external side effects; collector repairs any interrupted handoff.
    with db:
        db.execute("UPDATE jobs SET progress_stage='claude',progress_updated_at=?,industry=? WHERE id=?",
                   (now, industry, request_id))
    owner = request_row(request_id)
    if not owner or owner['status'] != 'working':
        raise RuntimeError('REMOTE_JOB_NOT_WORKING')
    if not bridge.change_remote(request_id, 'working', 'working', stage='claude', stage_updated_at=now, industry=industry):
        raise RuntimeError('REMOTE_JOB_STATUS_CHANGED')
    owner = {**owner, 'stage': 'claude', 'industry': industry}
    try:
        from src.notify.kairos_followups import notify_codex
        notify_codex(owner, 'completed')
    except Exception:
        pass  # Preserve files/queue even when Telegram is unavailable.
    job = enqueue_followup(owner, 'analysis')
    if job['status'] not in {'pending', 'working', 'sent'}:
        raise RuntimeError('CLAUDE_HANDOFF_NOT_ACCEPTED')
    with db:
        db.execute("UPDATE jobs SET status='claude',resume_requested=0 WHERE id=?", (request_id,))
    if row['source'] == 'telegram':
        # Existing durable progress reservations handle retry/ambiguous-send deduplication.
        from src.notify.kairos_followups import notify_progress
        try:
            notify_progress(job, owner)
        except Exception:
            pass
    return {'status': 'claude', 'id': request_id, 'claude_job_id': job['id'],
            'draft_path': data['draft']['path'], 'notion_published': False}


def repair_handoffs(db) -> int:
    rows = db.execute("SELECT id,industry FROM jobs WHERE status IN ('working','claude') AND progress_stage='claude'").fetchall()
    repaired = 0
    for row in rows:
        try:
            # Refresh parent from the DB before replaying, never re-enqueue sent history.
            from src.notify.kairos_followups import latest_job, request_row
            owner = request_row(row['id'])
            if owner and owner['status'] in {'sent', 'failed'}:
                existing = latest_job(row['id'], 'analysis')
                if existing:
                    finalize(existing, owner)
                continue
            if owner and owner['status'] == 'working':
                existing = latest_job(row['id'], 'analysis')
                if existing and existing['status'] in {'sent', 'failed'}:
                    finalize(existing, owner)
                    continue
                submit(db, row['id'], row['industry'] or '')
                repaired += 1
        except Exception:
            pass  # Existing intent and original package survive; retry next collector run.
    return repaired


def validate_comparison(result: dict, request_key: str) -> None:
    path = Path(result.get('comparison_review_path', ''))
    if not path.is_absolute() or not path.is_file():
        raise ValueError('FILE_HANDOFF_COMPARISON_REQUIRED')
    data = json.loads(path.read_text(encoding='utf-8'))
    rows = data.get('comparisons')
    if data.get('request_id') != request_key or not isinstance(rows, list) or not rows:
        raise ValueError('FILE_HANDOFF_COMPARISON_INVALID')
    for row in rows:
        if not isinstance(row, dict) or not all(isinstance(row.get(key), str) and row[key].strip()
                for key in ('topic', 'codex_view', 'claude_view', 'reason')) or not row.get('source_urls'):
            raise ValueError('FILE_HANDOFF_COMPARISON_INVALID')


def record_validation(job: dict, result: dict, state: Path) -> None:
    """Called only after fresh full Notion readback, file and gap validation passed."""
    validate_files(json.loads(package_path(job['request_id']).read_text(encoding='utf-8')), job['request_id'])
    key = f"A{job['id']}"
    proof = Path(result['proof_path'])
    comparison = Path(result['comparison_review_path'])
    marker = {'request_id': job['request_id'], 'job_id': job['id'],
              'notion_url': result['notion_url'], 'proof_path': str(proof), 'proof_sha256': digest(proof),
              'comparison_path': str(comparison), 'comparison_sha256': digest(comparison),
              'handoff_sha256': digest(package_path(job['request_id'])),
              'validated_at': datetime.now(timezone.utc).isoformat()}
    files = []
    for name in result.get('files', []):
        path = Path(name)
        if not path.is_absolute():
            path = Path(result['drive_dir']) / path
        files.append({'path': str(path.resolve()), 'sha256': digest(path)})
    if result.get('gap_review_path'):
        path = Path(result['gap_review_path'])
        files.append({'path': str(path.resolve()), 'sha256': digest(path)})
    marker['files'] = files
    path = state / f'{key}-final-validation.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def validation_marker(job: dict, state: Path) -> dict:
    marker = json.loads((state / f"A{job['id']}-final-validation.json").read_text(encoding='utf-8'))
    if marker['job_id'] != job['id'] or marker['request_id'] != job['request_id'] or marker['notion_url'] != job['notion_url']:
        raise ValueError('FILE_HANDOFF_FINAL_MARKER_INVALID')
    for path_key, hash_key in [('proof_path', 'proof_sha256'), ('comparison_path', 'comparison_sha256')]:
        if digest(Path(marker[path_key])) != marker[hash_key]:
            raise ValueError('FILE_HANDOFF_FINAL_HASH_MISMATCH')
    if digest(package_path(job['request_id'])) != marker['handoff_sha256']:
        raise ValueError('FILE_HANDOFF_FINAL_HASH_MISMATCH')
    validate_files(json.loads(package_path(job['request_id']).read_text(encoding='utf-8')), job['request_id'])
    for item in marker.get('files', []):
        if digest(Path(item['path'])) != item['sha256']:
            raise ValueError('FILE_HANDOFF_FINAL_HASH_MISMATCH')
    return marker


def finalize(job: dict, owner: dict) -> dict:
    """Reconcile stored verified Claude success without rerunning analysis or publishing."""
    if not is_file_first(owner['update_id']) or job.get('mode') != 'analysis':
        return owner
    if owner['status'] in {'sent', 'failed'}:
        from telegram_bridge import bridge
        with bridge.connect() as db:
            db.execute("UPDATE jobs SET status=?,notion_url=?,progress_stage=?,progress_updated_at=? WHERE id=? AND status IN ('working','claude') AND progress_stage='claude'",
                       (owner['status'], owner.get('notion_url'), owner.get('stage'), owner.get('stage_updated_at'), owner['update_id']))
        return owner
    if owner['status'] != 'working' or owner.get('stage') != 'claude':
        return owner
    from src.db.supabase_client import get_client
    from telegram_bridge import bridge, deck_runner
    if job['status'] == 'sent':
        if job['request_id'] != owner['update_id']:
            raise ValueError('FILE_HANDOFF_FINAL_MARKER_INVALID')
        validation_marker(job, deck_runner.STATE)
        payload = {'status': 'sent', 'notion_url': job['notion_url'], 'completed_at': job['completed_at'],
                   'stage': 'complete', 'stage_updated_at': job['completed_at'], 'error': None}
    elif job['status'] == 'failed':
        payload = {'status': 'failed', 'error': job.get('error') or 'CLAUDE_ANALYSIS_FAILED',
                   'stage': 'claude', 'stage_updated_at': job.get('completed_at')}
    else:
        return owner
    rows = (get_client().table('kairos_requests').update(payload).eq('update_id', owner['update_id'])
            .eq('status', 'working').eq('stage', 'claude').execute().data)
    if not rows:
        from src.notify.kairos_followups import request_row
        actual = request_row(owner['update_id'])
        if not actual or actual['status'] != payload['status']:
            raise RuntimeError('FILE_HANDOFF_FINAL_STATUS_CHANGED')
        return actual
    with bridge.connect() as db:
        db.execute('UPDATE jobs SET status=?,notion_url=?,progress_stage=?,progress_updated_at=? WHERE id=?',
                   (payload['status'], payload.get('notion_url'), payload['stage'], payload['stage_updated_at'], owner['update_id']))
    return {**owner, **payload}
