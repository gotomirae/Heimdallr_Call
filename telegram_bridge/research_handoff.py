# PRD Ref: §8.7 L · SC: 미확보 항목별 Claude 검색·분석 시도 누락 차단
"""Compact evidence handoff and machine checked gap coverage; no provider I/O."""
import json
from pathlib import Path


def validate_package(data: dict, request_id: int) -> None:
    if not isinstance(data, dict) or data.get('request_id') != request_id:
        raise ValueError('HANDOFF_WRONG_REQUEST')
    for key in ('facts', 'gaps'):
        if not isinstance(data.get(key), list):
            raise ValueError('HANDOFF_INCOMPLETE')
        ids = []
        for item in data[key]:
            if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'].strip():
                raise ValueError('HANDOFF_ITEM_INVALID')
            ids.append(item['id'])
            required = ('topic', 'reason', 'attempted_queries') if key == 'gaps' else (
                'statement', 'unit', 'period', 'published_at', 'source_url', 'location', 'verification')
            if any(field not in item for field in required):
                raise ValueError('HANDOFF_ITEM_INCOMPLETE')
            if key == 'gaps' and (not item['topic'] or not item['reason'] or not isinstance(item['attempted_queries'], list)):
                raise ValueError('HANDOFF_ITEM_INVALID')
        if len(ids) != len(set(ids)):
            raise ValueError('HANDOFF_DUPLICATE_ID')


def save_package(path: Path, data: dict, request_id: int) -> None:
    validate_package(data, request_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def validate_gap_review(result: dict, request_key: str, package: Path | None) -> None:
    path = Path(result.get('gap_review_path', ''))
    if not path.is_absolute() or not path.is_file():
        raise ValueError('GAP_REVIEW_REQUIRED')
    review = json.loads(path.read_text(encoding='utf-8'))
    if review.get('request_id') != request_key or not isinstance(review.get('gaps'), list):
        raise ValueError('GAP_REVIEW_INVALID')
    expected = set()
    if package and package.is_file():
        data = json.loads(package.read_text(encoding='utf-8'))
        validate_package(data, data.get('request_id'))
        expected = {item['id'] for item in data['gaps']}
    elif review.get('gap_inventory_checked') is not True:
        raise ValueError('GAP_INVENTORY_REQUIRED')
    seen = set()
    for gap in review['gaps']:
        if (not isinstance(gap, dict) or not isinstance(gap.get('id'), str) or gap['id'] in seen
                or gap.get('status') not in {'resolved', 'unresolved'}
                or not isinstance(gap.get('analysis_attempt'), str) or not gap['analysis_attempt'].strip()
                or not isinstance(gap.get('searches'), list) or not gap['searches']
                or not all(isinstance(s, dict) and isinstance(s.get('query'), str) and s['query'].strip()
                           and isinstance(s.get('outcome'), str) and s['outcome'].strip() for s in gap['searches'])):
            raise ValueError('GAP_ATTEMPT_REQUIRED')
        if gap['status'] == 'resolved' and not gap.get('source_urls'):
            raise ValueError('GAP_SOURCE_REQUIRED')
        seen.add(gap['id'])
    if not expected <= seen:
        raise ValueError('GAP_COVERAGE_INCOMPLETE')
