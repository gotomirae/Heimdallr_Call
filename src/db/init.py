# PRD Ref: §6, §13 (P0 검증 게이트) · traps.md T16
"""P0 검증 게이트: `python -m src.db.init`

schema.sql을 Supabase SQL Editor에 적용한 뒤 실행한다.
이 스크립트는 DDL을 실행하지 않는다 — Supabase REST로는 불가능하다.
하는 일은 "적용이 실제로 됐는지"를 확인하는 것뿐이다.

확인 항목
  1. SUPABASE_URL의 프로젝트 ref (HermesCall과 다른지 눈으로 대조 — ADR 8)
  2. EXPECTED_TABLES가 전부 존재하는지 (service key)
  3. anon(publishable) 키로 SELECT가 실제로 되는지 — 추측하지 말 것 (T16)
  4. cost_log가 anon에게 닫혀 있는지

하나라도 실패하면 exit code 1. 성공해야 P1로 넘어간다.
"""

from __future__ import annotations

import sys

from src.db.supabase_client import get_anon_client, get_client, project_ref
from src.utils.console import enable_utf8_stdout

# schema.sql과 반드시 동기화할 것.
EXPECTED_TABLES = (
    "krx_universe",
    "quarterly_fundamentals",
    "consensus_snapshots",
    "earnings_disclosures",
    "disclosure_excerpts",
    "price_snapshots",
    "quarter_prices",
    "index_snapshots",
    "screen_results",
    "analyses",
    "outcome_tracking",
    "notifications",
    "cost_log",
)

# anon SELECT가 허용되어야 하는 테이블 (cost_log만 제외)
ANON_READABLE = tuple(t for t in EXPECTED_TABLES if t != "cost_log")


#: PostgREST 오류코드 → 사람이 읽을 원인. 원인을 뭉뚱그리면 엉뚱한 곳을 고치게 된다.
_ERROR_HINTS = {
    "PGRST205": "테이블 없음 — schema.sql을 SQL Editor에 적용하지 않았다",
    "PGRST204": "컬럼 없음(쓰기) — 증분 마이그레이션 미적용 (traps.md T18)",
    "42703": "컬럼 없음(조회) — 증분 마이그레이션 미적용 (traps.md T18)",
    "42501": "권한 거부 — RLS 정책 확인",
    "PGRST301": "인증 실패 — 키 값을 확인하라",
}


def _probe(client, table: str) -> tuple[bool, str, str]:
    """(성공 여부, 오류코드, 메시지). 1행만 읽어 테이블 접근 가능성을 본다."""
    try:
        res = client.table(table).select("*").limit(1).execute()
    except Exception as exc:  # supabase-py의 APIError 계층에 의존하지 않는다
        code = str(getattr(exc, "code", "") or "")
        hint = _ERROR_HINTS.get(code, f"{type(exc).__name__}: {exc}")
        return False, code, hint
    return True, "", f"rows={len(res.data or [])}"


def main() -> int:
    enable_utf8_stdout()  # cp949 파이프에서 ★·═ 출력에 죽지 않도록 (src/utils/console.py)
    failures: list[str] = []

    print("═" * 62)
    print("Heimdallr_Call — DB 초기화 검증")
    print("═" * 62)

    try:
        ref = project_ref()
    except Exception as exc:
        print(f"✗ 환경변수 문제: {exc}")
        return 1

    print(f"\n[1] Supabase 프로젝트 ref : {ref}")
    print("    ★ 이 값이 HermesCall의 ref와 다른지 눈으로 대조하라 (ADR 8 · T16).")
    print("      같다면 지금 즉시 멈춰라 — HermesCall DB에 테이블이 생긴다.")

    print(f"\n[2] 테이블 존재 확인 (service key) — {len(EXPECTED_TABLES)}개")
    service = get_client()
    missing: list[str] = []
    for table in EXPECTED_TABLES:
        ok, code, msg = _probe(service, table)
        print(f"    {'✓' if ok else '✗'} {table:<24} {msg}")
        if not ok:
            (missing if code == "PGRST205" else failures).append(table)
    if missing:
        failures.append(
            f"테이블 {len(missing)}개 없음 ({', '.join(missing)}) "
            "— src/db/schema.sql을 Supabase SQL Editor에 붙여넣어 실행하라"
        )

    print(f"\n[3] anon(publishable) SELECT 확인 — {len(ANON_READABLE)}개")
    anon = get_anon_client()
    for table in ANON_READABLE:
        ok, code, msg = _probe(anon, table)
        print(f"    {'✓' if ok else '✗'} {table:<24} {msg}")
        if not ok and table not in missing:
            failures.append(f"anon SELECT 실패: {table} ({msg})")

    print("\n[4] cost_log가 anon에게 닫혀 있는지")
    ok, _code, msg = _probe(anon, "cost_log")
    if ok:
        # RLS는 켜져 있고 정책이 없으면 에러가 아니라 0행이 온다.
        leaked = msg != "rows=0"
        print(f"    {'✗ 노출됨' if leaked else '✓ 0행 (정상)'} cost_log  {msg}")
        if leaked:
            failures.append("cost_log가 anon에게 노출됐다 — anon SELECT 정책을 제거하라")
    else:
        print(f"    ✓ 차단됨 cost_log  {msg}")

    print("\n" + "═" * 62)
    if failures:
        print(f"✗ 실패 {len(failures)}건 — P1로 넘어가지 마라")
        for f in failures:
            print(f"   · {f}")
        return 1
    print("✓ P0 검증 게이트 통과. P1(유니버스)로 진행 가능.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
