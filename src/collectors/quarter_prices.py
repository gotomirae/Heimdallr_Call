# PRD Ref: §9.1-3 (상세화면 9분기 차트) · traps.md T11, T49
"""분기말 종가 수집 — 상세화면 차트에 **주가를 실적과 겹쳐** 그리기 위한 것.

왜 별도 수집기인가:
  `price_snapshots`는 '오늘의 스냅샷'이라 과거를 알지 못한다(실측 2일치뿐).
  9분기 차트에 주가를 얹으려면 **분기별로 되짚어야** 한다.

왜 네이버인가:
  `siseJson.naver`는 **1콜로 2.5년치 일봉**을 준다(실측 삼성전자 638봉).
  KIS 일봉은 조회 구간이 짧아 분기마다 나눠 불러야 해서 콜이 9배가 된다.
  지수 일봉에 이미 쓰고 있는 경로라 새 의존성도 아니다.

★ 분기말 종가는 **그 분기의 마지막 거래일** 종가다. 분기 마지막 날짜(3/31 등)로
  찍으면 그날이 휴장이면 값이 통째로 빈다 — 실제 거래일로 되짚어야 한다.
  어느 날 종가인지를 `trade_date`에 같이 저장해 나중에 검증할 수 있게 한다.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date

from src.db.supabase_client import get_client, select_all
from src.utils.console import enable_utf8_stdout
from src.utils.http import http_get

NAVER_DAILY_URL = "https://api.finance.naver.com/siseJson.naver"

#: 차트가 9분기를 그리므로 여유를 두고 3년치를 받는다.
LOOKBACK_YEARS = 3
CHUNK_ROWS = 500


def quarter_of(yyyymmdd: str) -> tuple[int, int]:
    """'20260814' → (2026, 3). **달력 분기**다.

    ★ 비12월 결산 기업의 회계분기와 다를 수 있다. 주가는 회계연도를 모르므로
      달력 분기로 찍고, 화면에서 실적 분기 라벨과 맞춰 붙인다.
    """
    year, month = int(yyyymmdd[:4]), int(yyyymmdd[4:6])
    return year, (month - 1) // 3 + 1


def fetch_daily_closes_naver(code: str, begin: str, end: str) -> dict[str, float]:
    """{'YYYYMMDD': 종가}. 네이버는 JS 배열이라 따옴표를 고쳐 파싱한다."""
    resp = http_get(
        NAVER_DAILY_URL,
        params={
            "symbol": code, "requestType": 1,
            "startTime": begin, "endTime": end, "timeframe": "day",
        },
        headers={"Referer": "https://finance.naver.com/"},
        timeout=30.0,
    )
    text = resp.text.strip().replace("'", '"')
    try:
        rows = json.loads(text)
    except json.JSONDecodeError:
        return {}
    out: dict[str, float] = {}
    for row in rows[1:]:  # 첫 행은 헤더
        # [날짜, 시가, 고가, 저가, 종가, 거래량, 외국인소진율]
        if len(row) >= 5 and isinstance(row[0], str) and len(row[0]) == 8:
            try:
                close = float(row[4])
            except (TypeError, ValueError):
                continue
            if close > 0:
                out[row[0]] = close
    return out


def quarter_end_closes(closes: dict[str, float]) -> dict[tuple[int, int], tuple[str, float]]:
    """일별 종가 → {(연, 분기): (거래일, 종가)}. **분기의 마지막 거래일**을 고른다.

    손계산 대조:
      {'20260330': 100, '20260331': 110, '20260401': 120}
        → (2026,1) = ('20260331', 110)   ← 3/31이 마지막 거래일
        → (2026,2) = ('20260401', 120)
      휴장으로 3/31이 없으면 3/30이 그 분기의 마지막 거래일이 된다.
    """
    out: dict[tuple[int, int], tuple[str, float]] = {}
    for day in sorted(closes):
        out[quarter_of(day)] = (day, closes[day])  # 오름차순이라 마지막이 남는다
    return out


def _iso(yyyymmdd: str) -> str:
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def save(limit: int | None, *, all_codes: bool) -> int:
    """게이트 통과 종목만 채운다 — 상세화면을 여는 종목이 거기이기 때문이다."""
    universe = select_all("krx_universe", "code,name,is_excluded")
    by_code = {u["code"]: u for u in universe}

    if all_codes:
        targets = [u["code"] for u in universe if not u["is_excluded"]]
    else:
        screens = select_all("screen_results", "code,fiscal_year,fiscal_quarter,gate_passed")
        latest: dict[str, dict] = {}
        for row in screens:
            key = row["code"]
            index = row["fiscal_year"] * 4 + row["fiscal_quarter"]
            if key not in latest or index > latest[key]["fiscal_year"] * 4 + latest[key]["fiscal_quarter"]:
                latest[key] = row
        targets = [c for c, r in latest.items() if r["gate_passed"] is True and c in by_code]
    targets.sort()
    if limit:
        targets = targets[:limit]

    today = date.today()
    begin = f"{today.year - LOOKBACK_YEARS}{today:%m%d}"
    end = f"{today:%Y%m%d}"
    print(f"대상 {len(targets)}종목 · 구간 {begin}~{end} · 종목당 1콜")

    db = get_client()
    payload: list[dict] = []
    saved = ok = empty = failed = 0
    started = time.monotonic()

    for index, code in enumerate(targets, 1):
        try:
            closes = fetch_daily_closes_naver(code, begin, end)
        except Exception:
            failed += 1
            continue
        if not closes:
            empty += 1
            continue
        ok += 1
        for (year, quarter), (day, close) in quarter_end_closes(closes).items():
            payload.append({
                "code": code, "fiscal_year": year, "fiscal_quarter": quarter,
                "close": close, "trade_date": _iso(day),
            })
        if len(payload) >= CHUNK_ROWS:
            saved += _flush(db, payload)
            payload.clear()
        if index % 100 == 0:
            print(f"    {index}/{len(targets)} · {time.monotonic() - started:.0f}초 "
                  f"· 성공 {ok} · 빈응답 {empty} · 실패 {failed} · 저장 {saved}행")
        time.sleep(0.12)  # 네이버에 대한 예의 — 초당 8콜 남짓

    saved += _flush(db, payload)
    elapsed = time.monotonic() - started
    print(f"\n✓ quarter_prices {saved}행 · {elapsed:.0f}초")
    print(f"  성공 {ok} · 빈 응답 {empty} · 실패 {failed}")
    if empty or failed:
        print("  ⚠ 빈 응답/실패 종목은 차트에서 주가 라인만 빠진다 — 실적 라인은 그대로다.")
    return 0


def _flush(db, rows: list[dict]) -> int:
    for i in range(0, len(rows), 500):
        db.table("quarter_prices").upsert(
            rows[i : i + 500], on_conflict="code,fiscal_year,fiscal_quarter"
        ).execute()
    return len(rows)


def check() -> int:
    """실호출 1종목으로 파싱·분기 접기를 눈으로 확인한다."""
    line = "═" * 74
    print(line)
    print("분기말 종가 검증 — 네이버 일봉")
    print(line)

    today = date.today()
    begin, end = f"{today.year - LOOKBACK_YEARS}{today:%m%d}", f"{today:%Y%m%d}"
    closes = fetch_daily_closes_naver("005930", begin, end)
    print(f"\n[1] 삼성전자 일봉 {len(closes)}봉 · {min(closes, default='—')}~{max(closes, default='—')}")

    quarters = quarter_end_closes(closes)
    print(f"\n[2] 분기말 종가 {len(quarters)}분기 (최근 9개)")
    for (year, quarter), (day, close) in sorted(quarters.items())[-9:]:
        print(f"    {year}.{quarter}Q  {day}  {close:>12,.0f}원")

    print(f"\n[3] 마지막 거래일 확인 — 분기 말일이 휴장이면 그 앞 거래일이어야 한다")
    for (year, quarter), (day, _) in sorted(quarters.items())[-4:]:
        last_month = quarter * 3
        print(f"    {year}.{quarter}Q 말일 {year}-{last_month:02d}-말 → 실제 {day}")
    print(line)
    return 0


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="분기말 종가 수집")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--all", action="store_true",
                        help="게이트 통과분이 아니라 전 종목")
    args = parser.parse_args()
    if args.save:
        return save(args.limit, all_codes=args.all)
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
