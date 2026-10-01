# PRD Ref: §7.3 · ADR 25 · JARVIS INTEGRATION_TASKS B-14
"""이미 저장된 `analyses.payload`의 표식·자리표시 흔적을 **LLM 호출 없이** 정리한다.

    python -m src.analysis.clean_stored_run          # dry-run (바뀔 행만 출력)
    python -m src.analysis.clean_stored_run --save   # payload 갱신

새 저장분은 `analysis_result_from_response`가 같은 함수로 이미 정리한다. 이 CLI는
그 이전 저장분을 위한 1회성 정리다. 숫자를 새로 만들지 않는다 — 깨진 표식 안의
'단위 있는 숫자'만 꺼내고, 나머지 흔적은 지운다. 근거 재검사는 입력 스냅샷이 없어
할 수 없으므로 꺼낸 숫자는 표식 안에 원래 있던 값 그대로다.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from src.analysis.numeric_grounding import (
    strip_legacy_redaction_markers,
    unwrap_leftover_fact_markers,
)
from src.analysis.schema_validation import is_placeholder, prune_placeholder_items, schema_problems
from src.utils.console import enable_utf8_stdout

META_KEY = "_heimdallr"


def _blank_placeholders(value):
    if is_placeholder(value):
        return ""
    if isinstance(value, dict):
        return {key: _blank_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_blank_placeholders(item) for item in value]
    return value


def scalar_placeholders(payload: dict) -> list[str]:
    """배열 항목 정리 뒤에도 남는 **단일 문자열** 자리표시 경로(예: earnings_change.cause='...')."""
    body = {key: value for key, value in payload.items() if key != META_KEY}
    pruned = prune_placeholder_items(strip_legacy_redaction_markers(unwrap_leftover_fact_markers(body)))
    return [problem.split(":", 1)[1] for problem in schema_problems(pruned) if problem.startswith("placeholder:")]


def clean_payload(payload: dict) -> dict:
    """순수 함수. 메타(`_heimdallr`)는 건드리지 않는다. 남은 문자열 자리표시는 빈 값이 된다."""
    meta = payload.get(META_KEY)
    body = {key: value for key, value in payload.items() if key != META_KEY}
    body = prune_placeholder_items(strip_legacy_redaction_markers(unwrap_leftover_fact_markers(body)))
    body = _blank_placeholders(body)
    if meta is not None:
        body[META_KEY] = meta
    return body


def emptied_required(payload: dict) -> list[str]:
    """정리 뒤 비어 버린 필수 항목. 자리표시만 있던 분석은 살릴 내용이 없다."""
    body = {key: value for key, value in payload.items() if key != META_KEY}
    return [problem for problem in schema_problems(body) if problem.endswith((": empty", ": missing"))]


def changed_fields(before: dict, after: dict) -> list[str]:
    return sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="저장된 LLM 분석의 표식·자리표시 정리(B-14)")
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()

    from src.db.supabase_client import get_client, select_all

    rows = select_all("analyses", "id,code,fiscal_year,fiscal_quarter,payload")
    client = get_client() if args.save else None
    changed = invalidated = 0
    for row in rows:
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        cleaned = clean_payload(payload)
        if cleaned == payload:
            continue
        changed += 1
        fields = changed_fields(payload, cleaned)
        # 원래부터 빈 항목은 세지 않는다 — 정리 때문에 **새로** 비워진 것만 남긴다.
        # 분석 전체를 숨기지 않는다: 리스크가 자리표시였어도 본문 해석은 유효하다(실측 417500).
        emptied = sorted(set(emptied_required(cleaned)) - set(emptied_required(payload)))
        invalidated += bool(emptied)
        # 분석 전체를 숨기지 않는다 — 자리표시 칸만 비우고 어느 칸인지 메타에 남긴다.
        #   숨김 기준(몇 칸 이상?)은 자의적이고, 한 칸 때문에 유효한 해석까지 잃는다.
        scalars = scalar_placeholders(payload)
        note = f" · 정리로 비워짐: {', '.join(emptied)}" if emptied else ""
        note += f" · 문자열 자리표시 {len(scalars)}곳 비움" if scalars else ""
        print(f"  {row['code']} {row.get('fiscal_year')}.{row.get('fiscal_quarter')}Q · {', '.join(fields)}{note}")
        if client is not None:
            meta = dict(cleaned.get(META_KEY) or {})
            meta["b14_cleaned_at"] = datetime.now(timezone.utc).isoformat()
            meta["b14_cleaned_fields"] = fields
            if emptied:
                meta["b14_emptied"] = emptied
            cleaned[META_KEY] = meta
            client.table("analyses").update({"payload": cleaned}).eq("id", row["id"]).execute()
    mode = "저장함" if args.save else "(--save 미지정 — 쓰기 0건)"
    print(f"\n정리 대상 {changed}/{len(rows)}행 · 자리표시만 있던 항목이 비워진 행 {invalidated} · {mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
