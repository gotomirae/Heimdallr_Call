# PRD Ref: §8.7 G-7
"""One headless Claude Code deck worker. No Telegram messages or API key."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from src.config.constants import KAIROS_DECK_TIMEOUT_SECONDS, KAIROS_DECK_RETRY_MINUTES, KAIROS_DECK_USAGE_RETRIES
from src.db.supabase_client import get_client
from src.utils.env import subscription_cli_env

SKILL = Path.home() / '.claude/skills/kairos-deck'
STATE = Path(__file__).resolve().parent / 'state/decks'
USAGE = re.compile(r'usage limit|rate.?limit|hit your limit|out of extra usage|resets? (?:at|in)|사용량.*(?:한도|제한)', re.I)


def parse_result(output: str) -> dict | None:
    # --output-format json wraps the skill's last line in result.
    for line in reversed(output.splitlines()):
        try:
            payload = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get('status') in {'ok', 'failed'}:
            return payload
        if isinstance(payload.get('result'), str):
            return parse_result(payload['result'])
    return None


def result_file(skill: Path, request_id: int, started: float) -> dict | None:
    # Never accept an unrelated or stale work/*/result.json.
    found = []
    for path in (skill / 'work').glob('*/result.json'):
        if path.stat().st_mtime < started:
            continue
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            continue
        if str(payload.get('request_id', '')) == f'D{request_id}':
            found.append(payload)
    if len(found) > 1:
        raise ValueError('DECK_RESULT_AMBIGUOUS')
    return found[0] if found else None


def validate_success(result: dict) -> None:
    if not re.fullmatch(r'https://(?:www\.)?notion\.so/\S+|https://app\.notion\.com/p/\S+', result.get('notion_url', '')):
        raise ValueError('DECK_NOTION_URL_INVALID')
    directory = Path(result.get('drive_dir', ''))
    if not directory.is_absolute() or not directory.is_dir():
        raise ValueError('DECK_DRIVE_DIR_INVALID')
    files = result.get('files', [])
    paths = []
    for name in files:
        path = Path(name)
        if not path.is_absolute():
            path = directory / path
        path = path.resolve()
        if not path.is_relative_to(directory.resolve()) or not path.is_file() or path.stat().st_size == 0:
            raise ValueError('DECK_FILE_MISSING')
        paths.append(path)
    if not {'.pptx', '.pdf', '.md'} <= {p.suffix.lower() for p in paths}:
        raise ValueError('DECK_FILES_INCOMPLETE')


class TimeoutTreeUncertain(RuntimeError):
    pass


def run_claude(args: list[str]):
    process = subprocess.Popen(args, cwd=SKILL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", env=subscription_cli_env(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        stdout, stderr = process.communicate(timeout=KAIROS_DECK_TIMEOUT_SECONDS)
        return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        if sys.platform == "win32":
            killed = subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if killed.returncode:
                raise TimeoutTreeUncertain("TIMEOUT_TREE_UNCERTAIN")
        else:
            process.kill()
        process.communicate()
        raise


def run_once() -> dict:
    cli = shutil.which('claude.exe') or shutil.which('claude')
    if not cli or not (SKILL / 'SKILL.md').is_file():
        return {'status': 'unavailable', 'error': 'CLAUDE_OR_SKILL_MISSING'}
    auth = subprocess.run([cli, "auth", "status", "--json"], capture_output=True,
        text=True, encoding="utf-8", timeout=30, env=subscription_cli_env(),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        login = json.loads(auth.stdout)
    except ValueError:
        return {"status": "unavailable", "error": "CLAUDE_LOGIN_REQUIRED"}
    if auth.returncode or not login.get("loggedIn") or login.get("authMethod") != "claude.ai":
        return {"status": "unavailable", "error": "CLAUDE_SUBSCRIPTION_REQUIRED"}
    client = get_client()
    job = client.rpc('kairos_claim_deck', {}).execute().data
    if not job:
        return {'status': 'idle'}
    analysis = job['analysis']
    deck_id = int(job['id'])
    STATE.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    # JSON quoting prevents data becoming slash-command options or extra instructions.
    prompt = (
        '/kairos-deck ' + json.dumps(analysis['company_name'], ensure_ascii=False)
        + ' --code ' + json.dumps(analysis.get('code') or analysis.get('ticker'))
        + ' --market ' + json.dumps(analysis['market'])
        + ' --analysis ' + json.dumps(analysis['notion_url'])
        + f' --request-id D{deck_id}'
        + '\n완료 결과 JSON에 request_id=' + json.dumps(f'D{deck_id}')
        + '를 반드시 포함하세요. 기존 기업 분석을 재조회하고 발표자료만 추가하세요. 사용자에게 질문하지 마세요.'
    )
    payload = {'status': 'failed', 'error': 'UNEXPECTED', 'completed_at': started.isoformat()}
    try:
        if analysis['request_kind'] != 'company' or analysis['status'] != 'sent':
            raise ValueError('DECK_ANALYSIS_NOT_READY')
        run = run_claude([cli, '-p', prompt, '--allowedTools',
            'Bash,Read,Write,Edit,Glob,Grep,WebSearch,WebFetch',
            '--permission-mode', 'acceptEdits', '--output-format', 'json'],
            )
        output = run.stdout + '\n' + run.stderr
        result = parse_result(run.stdout) or result_file(SKILL, deck_id, started.timestamp())
        if run.returncode == 0 and result and result.get('status') == 'ok':
            if result.get('request_id') not in {None, f'D{deck_id}'}:
                raise ValueError('DECK_RESULT_WRONG_REQUEST')
            validate_success(result)
            payload = {'status': 'sent', 'notion_url': result['notion_url'],
                       'drive_dir': result['drive_dir'], 'files': result['files'], 'error': None,
                       'completed_at': datetime.now(timezone.utc).isoformat()}
        elif USAGE.search(output) or (result and result.get('reason') == 'USAGE'):
            if job['attempts'] > KAIROS_DECK_USAGE_RETRIES:
                payload['error'] = 'USAGE'
            else:
                payload = {'status': 'pending', 'error': 'USAGE', 'claimed_at': None, 'completed_at': None,
                           'retry_after': (datetime.now(timezone.utc) + timedelta(minutes=KAIROS_DECK_RETRY_MINUTES)).isoformat()}
        else:
            payload['error'] = (result or {}).get('reason', 'CLAUDE_EXIT' if run.returncode else 'RESULT_MISSING')
    except TimeoutTreeUncertain:
        payload = {"status": "working", "error": "TIMEOUT_TREE_UNCERTAIN"}
    except subprocess.TimeoutExpired:
        payload['error'] = 'TIMEOUT'
    except Exception as exc:
        payload['error'] = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
    # Persist before DB update. A crash leaves working, blocking duplicate execution.
    (STATE / f'D{deck_id}.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    updated = client.table('kairos_deck_requests').update(payload).eq('id', deck_id).eq('status', 'working').execute()
    if not updated.data:
        raise RuntimeError('DECK_REMOTE_STATUS_CHANGED')
    return {'id': deck_id, **payload}


if __name__ == '__main__':
    try:
        result = run_once()
    except Exception as exc:
        result = {"status": "error", "error": type(exc).__name__}
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "worker.json").write_text(json.dumps({
        "checked_at": datetime.now(timezone.utc).isoformat(), **result
    }, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
