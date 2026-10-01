# PRD Ref: §6 RLS · JARVIS INTEGRATION_TASKS B-11
"""JARVIS가 anon 키로 읽는 테이블이 **실제로 읽히는지** 확인한다(읽기 전용).

    python -m src.db.check_anon

★ service key로 확인하면 RLS를 우회하므로 항상 성공한다 — 그건 검증이 아니다.
  반드시 publishable/anon 키(`NEXT_PUBLIC_SUPABASE_ANON_KEY`)로 읽는다.
★ 정책이 없으면 PostgREST는 **에러가 아니라 빈 배열**을 준다. 그래서 service key로
  행 수를 함께 세어 "행은 있는데 anon에게 0행"을 정책 누락으로 판정한다.
"""

from __future__ import annotations

from src.utils.console import enable_utf8_stdout

#: JARVIS `lib/ingest/heimdallr.ts`의 HEIMDALLR_TABLES와 같은 목록이다.
JARVIS_TABLES = (
    "screen_results", "price_snapshots", "quarterly_fundamentals", "consensus_snapshots",
    "notifications", "analyses", "outcome_tracking", "krx_universe", "index_snapshots",
    "entry_checks",
)


def classify(anon_rows: int | None, service_rows: int | None, error: str | None) -> str:
    """순수 판정. 표시 문자열을 돌려준다."""
    if error:
        return "테이블 없음(마이그레이션 필요)" if "PGRST205" in error or "42P01" in error else f"오류 {error[:80]}"
    if service_rows and not anon_rows:
        return "정책 누락 — 행은 있는데 anon 0행"
    if not service_rows:
        return "읽기 가능(현재 0행)"
    return "읽기 가능"


def main() -> int:
    enable_utf8_stdout()
    from src.db.supabase_client import get_anon_client, get_client

    anon, service = get_anon_client(), get_client()
    failed = 0
    for table in JARVIS_TABLES:
        error = None
        anon_rows = service_rows = None
        try:
            anon_rows = len(anon.table(table).select("*").limit(1).execute().data or [])
            service_rows = len(service.table(table).select("*").limit(1).execute().data or [])
        except Exception as exc:
            error = str(exc)
        verdict = classify(anon_rows, service_rows, error)
        ok = verdict.startswith("읽기 가능")
        failed += not ok
        print(f"  {'✓' if ok else '✗'} {table:<24}{verdict}")
    print(f"\n{len(JARVIS_TABLES) - failed}/{len(JARVIS_TABLES)} 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
