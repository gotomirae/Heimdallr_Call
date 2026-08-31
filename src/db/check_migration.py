# PRD Ref: §6 · traps.md T18
"""마이그레이션 적용 여부를 **컬럼 단위로** 확인한다.

    python -m src.db.check_migration

★ `init.py`는 테이블 존재만 본다. 컬럼이 빠진 것은 못 잡는다 —
  그런데 이 프로젝트에서 실제로 문제가 된 건 **테이블이 아니라 컬럼**이었다
  (`ret_5d` 하나 때문에 시세 수집이 크래시했다, T62).

★ 없는 컬럼을 발견하면 **붙여 넣을 SQL을 그대로 출력한다.**
  "무엇이 없다"만 알려주고 방법을 안 알려주면 매번 문서를 찾아야 한다.
"""

from __future__ import annotations

from src.db.supabase_client import get_client
from src.utils.console import enable_utf8_stdout

#: (테이블, 컬럼, SQL 타입, 왜 필요한가). schema.sql의 마이그레이션 절과 같아야 한다.
EXPECTED_COLUMNS: tuple[tuple[str, str, str, str], ...] = (
    ("price_snapshots", "ret_5d", "NUMERIC", "발굴 목록의 '최근 5일 상승률' 열"),
    ("price_snapshots", "rel_ret_6m", "NUMERIC", "상세화면 6개월 지수대비 수익률"),
    ("price_snapshots", "rel_ret_12m", "NUMERIC", "상세화면 12개월 지수대비 수익률"),
    ("quarter_prices", "close", "—", "상세화면 9분기 차트의 주가 라인 (테이블)"),
    ("weekly_prices", "close", "—", "상세화면 실제 주간 종가 차트 (테이블)"),
    ("consensus_snapshots", "per", "NUMERIC", "네이버 최근 확정 PER"),
    ("consensus_snapshots", "fwd_per", "NUMERIC", "네이버 연간 (E) 선행 PER"),
    ("outcome_tracking", "ret_dm5", "NUMERIC", "발표 전 5일 수익률"),
    ("outcome_tracking", "excess_dm5", "NUMERIC", "발표 전 5일 초과수익"),
    ("outcome_tracking", "ret_d0", "NUMERIC", "발표 당일 수익률"),
    ("outcome_tracking", "excess_d0", "NUMERIC", "발표 당일 초과수익"),
)

#: 있으면 좋지만 **없어도 화면이 정상 동작하는** 컬럼.
#: 대시보드가 읽는 시점에 계산하므로 마이그레이션이 필수가 아니다(T71).
OPTIONAL_COLUMNS: tuple[tuple[str, str, str, str], ...] = (
    ("krx_universe", "sector", "TEXT",
     "투자 섹터 (없어도 industry·products로 즉석 분류된다)"),
)

MISSING_COLUMN = "42703"
MISSING_TABLE = "PGRST205"


def probe(client, table: str, column: str) -> tuple[bool | None, str]:
    """(있는가, 사유). ``None``은 연결 실패 등 **판정 불가**다."""
    try:
        client.table(table).select(column).limit(1).execute()
        return True, ""
    except Exception as exc:
        code = str(getattr(exc, "code", "") or "")
        if code == MISSING_COLUMN:
            return False, "컬럼 없음"
        if code == MISSING_TABLE:
            return False, "테이블 없음"
        return None, f"판정 불가: {code or type(exc).__name__}"


def sql_for(missing: list[tuple[str, str, str, str]]) -> list[str]:
    """붙여 넣을 SQL. 전부 `IF NOT EXISTS`라 여러 번 실행해도 안전하다."""
    lines: list[str] = []
    for table, column, sqltype, why in missing:
        if table in {"quarter_prices", "weekly_prices"}:
            if table == "weekly_prices":
                lines += [
                    "-- 실제 주간 종가",
                    "CREATE TABLE IF NOT EXISTS weekly_prices (",
                    "  code TEXT NOT NULL, trade_date DATE NOT NULL, close NUMERIC NOT NULL,",
                    "  refreshed_at TIMESTAMPTZ DEFAULT now(),",
                    "  PRIMARY KEY (code, trade_date)",
                    ");",
                    "ALTER TABLE weekly_prices ENABLE ROW LEVEL SECURITY;",
                    "DROP POLICY IF EXISTS anon_select_weekly_prices ON weekly_prices;",
                    "CREATE POLICY anon_select_weekly_prices ON weekly_prices",
                    "  FOR SELECT TO anon USING (true);",
                ]
                continue
            lines += [
                "-- 분기말 종가 (테이블 자체가 없다)",
                "CREATE TABLE IF NOT EXISTS quarter_prices (",
                "  code TEXT NOT NULL, fiscal_year INT NOT NULL, fiscal_quarter INT NOT NULL,",
                "  close NUMERIC, trade_date DATE, refreshed_at TIMESTAMPTZ DEFAULT now(),",
                "  PRIMARY KEY (code, fiscal_year, fiscal_quarter)",
                ");",
                "ALTER TABLE quarter_prices ENABLE ROW LEVEL SECURITY;",
                "DROP POLICY IF EXISTS anon_select_quarter_prices ON quarter_prices;",
                "CREATE POLICY anon_select_quarter_prices ON quarter_prices",
                "  FOR SELECT TO anon USING (true);",
            ]
            continue
        lines.append(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column:<12} {sqltype};"
            f"  -- {why}"
        )
    return lines


def main() -> int:
    enable_utf8_stdout()
    client = get_client()
    line = "═" * 74
    print(line)
    print("마이그레이션 확인 — 컬럼 단위")
    print(line)

    missing: list[tuple[str, str, str, str]] = []
    unavailable: list[tuple[str, str, str]] = []
    print("\n[필수]")
    for row in EXPECTED_COLUMNS:
        table, column, _, why = row
        ok, reason = probe(client, table, column)
        mark = "✓" if ok is True else ("✗" if ok is False else "?")
        print(f"  {mark} {table}.{column:<12} {'' if ok else reason:<12} {why}")
        if ok is False:
            missing.append(row)
        elif ok is None:
            unavailable.append((table, column, reason))

    print("\n[선택 — 없어도 화면이 정상 동작한다]")
    for row in OPTIONAL_COLUMNS:
        table, column, _, why = row
        ok, reason = probe(client, table, column)
        mark = "✓" if ok is True else ("·" if ok is False else "?")
        print(f"  {mark} {table}.{column:<12} {'' if ok else reason:<12} {why}")

    if unavailable:
        print(f"\n{line}")
        print(f"? 필수 항목 {len(unavailable)}개를 확인하지 못했다. 스키마 부재로 판정하지 않는다.")
        print("  네트워크·인증 상태를 복구한 뒤 다시 실행하라. 확인 전에는 DDL을 적용하지 않는다.")
        print(line)
        return 2

    if not missing:
        print(f"\n{line}")
        print("✓ 필수 컬럼이 전부 있다. 마이그레이션이 필요 없다.")
        print(line)
        return 0

    print(f"\n{line}")
    print(f"✗ {len(missing)}개가 없다. 아래를 Supabase → SQL Editor에 붙여 넣고 Run하라.")
    print("  (DDL은 REST로 실행할 수 없어 사람이 적용해야 한다 — docs/MIGRATION.md)")
    print(line)
    print()
    for sql in sql_for(missing):
        print(sql)
    print()
    print("적용 후 다시 이 명령으로 확인하고, 데이터를 채운다:")
    if any(t == "outcome_tracking" for t, _, _, _ in missing):
        print("  python -m src.analysis.outcome_run --save")
    if any(t == "price_snapshots" for t, _, _, _ in missing):
        print("  python -m src.collectors.price_run --save")
    if any(t in {"quarter_prices", "weekly_prices"} for t, _, _, _ in missing):
        print("  python -m src.collectors.quarter_prices --save")
    print(line)
    # ★ 종료코드 1 — CI나 스크립트가 이 상태를 성공으로 착각하면 안 된다.
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
