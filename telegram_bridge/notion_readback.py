# PRD Ref: §8.7 G-3
"""Validate the agent's saved Notion connector reread, before publishing a JARVIS URL."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

from src.config.constants import KAIROS_READBACK_MAX_AGE_MINUTES

PARENTS = {'company': '3d29c770aa6180469edceca9fb363529',
           'industry': '3e69c770aa61808aa0e8e136d62dc59a'}


def compact_id(value):
    return str(value).replace('-', '').lower()


def validate_readback(job_id: int, url: str, kind: str, path: Path) -> None:
    if not path.is_file():
        raise RuntimeError('NOTION_READBACK_REQUIRED')
    proof = json.loads(path.read_text(encoding='utf-8'))
    page = proof.get('page', {})
    blocks = proof.get('blocks', {})
    checked = datetime.fromisoformat(proof['checked_at'].replace('Z', '+00:00'))
    if checked.tzinfo is None or not timedelta(0) <= datetime.now(timezone.utc) - checked <= timedelta(minutes=KAIROS_READBACK_MAX_AGE_MINUTES):
        raise ValueError('NOTION_READBACK_EXPIRED')
    id_match = re.search(r'([0-9a-fA-F]{32})(?:[?#].*)?$', url.replace('-', ''))
    parent_ids = {compact_id(p.get('id', '')) for p in proof.get('ancestors', [])}
    if (proof.get('request_id') != job_id or not id_match or compact_id(page.get('id')) != id_match[1].lower()
        or PARENTS[kind] not in parent_ids or page.get('archived') or page.get('in_trash')
        or not blocks.get('results') or blocks.get('has_more') is not False
        or not all(proof.get(k) is True for k in ('template_verified', 'sources_verified', 'target_verified'))):
        raise ValueError('NOTION_READBACK_INVALID')
