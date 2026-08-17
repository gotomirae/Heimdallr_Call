# PRD Ref: §3, §5.1(L0), 부록 B · traps.md T5~T8
"""P1 유니버스 구축 — KIND + 네이버 시총 + DART corp_code 조인.

    python -m src.universe.build            # 수집 + 검증 리포트 (DB 미기록)
    python -m src.universe.build --save     # + krx_universe upsert

DB 없이도 수집·판정·검증 수치를 전부 볼 수 있게 분리했다.
스키마 적용 전에도 P1 검증이 가능해야 하기 때문이다.
"""

from __future__ import annotations

import argparse
import collections
from dataclasses import asdict, dataclass
from datetime import date

from src.config.constants import MARKET_CAP_FLOOR_KRW, MIN_QUARTERS_HISTORY
from src.universe.corp_code import fetch_corp_code_map
from src.universe.kind_listing import KindFetchReport, fetch_kind_listing
from src.universe.market_cap import fetch_admin_issues, fetch_market_caps
from src.universe.sector_filter import classify, quarters_since
from src.utils.console import enable_utf8_stdout

# DART 조회 확인용 (phases.md P1 검증 4)
SPOT_CHECK_CODES = {"005930": "삼성전자", "058470": "리노공업", "403870": "HPSP"}


@dataclass
class UniverseRow:
    code: str
    symbol: str
    name: str
    board: str
    industry: str | None
    industry_code: str | None
    products: str | None
    market_cap_krw: int
    corp_code: str | None
    listed_at: date | None
    is_admin_issue: bool
    is_spac: bool
    is_excluded: bool
    exclude_reason: str | None
    sector_caveat: bool

    def to_db(self) -> dict:
        row = asdict(self)
        row["listed_at"] = self.listed_at.isoformat() if self.listed_at else None
        return row


def build_universe(
    *, floor_krw: int = MARKET_CAP_FLOOR_KRW, today: date | None = None
) -> tuple[list[UniverseRow], KindFetchReport, dict]:
    today = today or date.today()

    listing, kind_report = fetch_kind_listing()
    caps = fetch_market_caps(floor_krw)
    admin_issues = fetch_admin_issues()
    corp_map = fetch_corp_code_map()

    rows: list[UniverseRow] = []
    for item in listing:
        cap = caps.caps.get(item.code)
        if cap is None:  # 시총 하한 미만 또는 시세 없음 → 유니버스 밖
            continue

        verdict = classify(
            industry=item.industry,
            products=item.products,
            is_spac=item.is_spac,
            is_admin_issue=item.code in admin_issues,
            is_trade_stopped=item.code in caps.trade_stopped,
            quarters_since_listing=quarters_since(item.listed_at, today),
            min_quarters=MIN_QUARTERS_HISTORY,
        )
        rows.append(
            UniverseRow(
                code=item.code,
                symbol=item.symbol,
                name=item.name,
                board=item.board,
                industry=item.industry,
                industry_code=None,  # KIND는 업종코드를 주지 않는다. 업종명으로 판정한다.
                products=item.products,
                market_cap_krw=cap,
                corp_code=corp_map.get(item.code),
                listed_at=item.listed_at,
                is_admin_issue=item.code in admin_issues,
                is_spac=item.is_spac,
                is_excluded=verdict.is_excluded,
                exclude_reason=verdict.exclude_reason,
                sector_caveat=verdict.sector_caveat,
            )
        )

    rows.sort(key=lambda r: r.market_cap_krw, reverse=True)
    meta = {
        "admin_issue_total": len(admin_issues),
        "trade_stopped": len(caps.trade_stopped),
        "corp_map_size": len(corp_map),
        "naver_scanned": caps.scanned,
        "naver_pages": caps.pages_read,
        "caps_above_floor": len(caps.caps),
    }
    return rows, kind_report, meta


def _dart_stock_code(corp_code: str) -> str | None:
    """corp_code로 DART에 되물어 실제 종목코드를 받는다 (traps.md T22 왕복 대조)."""
    from src.config.constants import DART_BASE_URL
    from src.utils.env import require_env
    from src.utils.http import http_get

    resp = http_get(
        f"{DART_BASE_URL}/company.json",
        params={"crtfc_key": require_env("OPENDART_API_KEY"), "corp_code": corp_code},
        timeout=30.0,
    )
    body = resp.json()
    if body.get("status") != "000":
        return None
    return (body.get("stock_code") or "").strip() or None


def _report(rows: list[UniverseRow], kind: KindFetchReport, meta: dict) -> None:
    line = "═" * 68
    print(line)
    print(f"P1 유니버스 검증 리포트 — {date.today()} (시총 하한 {MARKET_CAP_FLOOR_KRW:,}원)")
    print(line)

    print("\n[1] KIND 원문 대조 (traps.md T5 — lxml 회귀 감지)")
    for board in kind.raw_tr_counts:
        raw, parsed, valid = (
            kind.raw_tr_counts[board],
            kind.parsed_row_counts[board],
            kind.rows_by_board[board],
        )
        print(f"    {board:6} 원문<tr>={raw:5}  파싱={parsed:5}  유효데이터행={valid:5}")
    print(f"    중복 종목코드 제거 {len(kind.duplicate_codes)}건 (T6)")
    print(f"    비표준 종목코드 제외 {len(kind.nonstandard_codes)}건: "
          f"{', '.join(kind.nonstandard_codes[:4])}")

    print("\n[2] 시총 하한 이상 종목 수")
    by_board = collections.Counter(r.board for r in rows)
    for board in ("KOSPI", "KOSDAQ"):
        print(f"    {board:6} {by_board[board]:5}종목   "
              f"(네이버 {meta['naver_pages'].get(board, 0)}페이지 / "
              f"{meta['naver_scanned'].get(board, 0)}종목 스캔)")
    print(f"    합계   {len(rows):5}종목   "
          f"(네이버 하한 이상 {meta['caps_above_floor']} − KIND 미조인분)")

    print("\n[3] corp_code 매칭 (P2 배치 수집의 키)")
    missing = [r for r in rows if not r.corp_code]
    rate = (len(rows) - len(missing)) / len(rows) * 100 if rows else 0.0
    print(f"    DART corpCode 레코드 {meta['corp_map_size']:,}건")
    print(f"    매칭 {len(rows) - len(missing)}/{len(rows)} = {rate:.2f}%  "
          f"{'✓ (≥98% 통과)' if rate >= 98 else '✗ 98% 미달 — 원인 규명 필요'}")
    if missing:
        print(f"    실패 {len(missing)}건: "
              f"{', '.join(f'{r.name}({r.code})' for r in missing[:10])}")

    print("\n[4] 업종 제외 판정 (부록 B / G3)")
    excluded = [r for r in rows if r.is_excluded]
    print(f"    제외 {len(excluded)}종목 / 잔여 {len(rows) - len(excluded)}종목")
    for reason, n in collections.Counter(r.exclude_reason for r in excluded).most_common():
        sample = next(r.name for r in excluded if r.exclude_reason == reason)
        print(f"      {reason:26} {n:4}  예: {sample}")
    caveat = [r for r in rows if r.sector_caveat and not r.is_excluded]
    print(f"    주의(sector_caveat, 제외 아님) {len(caveat)}종목")
    print(f"    관리종목 원본 {meta['admin_issue_total']}건 · 거래정지 {meta['trade_stopped']}건")
    print("    ⚠ 투자주의환기종목(코스닥)은 미수집 — KIND investwarn 엔드포인트 404 (2026-08-13)")

    print("\n[5] 스팟 체크 — DART 왕복 대조 (매칭률만으로는 T22를 잡지 못한다)")
    by_code = {r.code: r for r in rows}
    for code, name in SPOT_CHECK_CODES.items():
        row = by_code.get(code)
        if row is None:
            print(f"    ✗ {name}({code}) 유니버스에 없음")
            continue
        if not row.corp_code:
            print(f"    ✗ {name}({code}) corp_code 없음")
            continue
        # corp_code로 DART에 되물어 stock_code가 원래 종목코드와 같은지 본다.
        got = _dart_stock_code(row.corp_code)
        ok = got == code
        print(f"    {'✓' if ok else '✗'} {name}({code}) corp_code={row.corp_code} "
              f"→ DART stock_code={got!r} {'일치' if ok else '★불일치 — 매핑이 어긋났다'} "
              f"· 시총 {row.market_cap_krw / 1e8:,.0f}억 · 제외={row.exclude_reason or '-'}")

    print("\n[6] 시총 상위 5 / 하위 5")
    for r in rows[:5]:
        print(f"    {r.market_cap_krw / 1e8:>10,.0f}억  {r.code} {r.name}")
    print("    ...")
    for r in rows[-5:]:
        print(f"    {r.market_cap_krw / 1e8:>10,.0f}억  {r.code} {r.name}")
    print(line)


def save(rows: list[UniverseRow]) -> int:
    """krx_universe upsert. 1,000행 초과이므로 청크로 나눠 보낸다."""
    from src.db.supabase_client import get_client

    db = get_client()
    payload = [r.to_db() for r in rows]
    written = 0
    for i in range(0, len(payload), 500):
        chunk = payload[i : i + 500]
        db.table("krx_universe").upsert(chunk, on_conflict="code").execute()
        written += len(chunk)
    return written


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="P1 유니버스 구축")
    parser.add_argument("--save", action="store_true", help="krx_universe에 upsert")
    args = parser.parse_args()

    rows, kind_report, meta = build_universe()
    _report(rows, kind_report, meta)

    if args.save:
        try:
            written = save(rows)
            print(f"\n✓ krx_universe upsert {written}행")
        except Exception as exc:
            print(f"\n✗ 저장 실패: {exc}")
            print("  schema.sql을 Supabase SQL Editor에 적용했는지 확인하라.")
            return 1
    else:
        print("\n(--save 미지정 — DB에 기록하지 않았다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
