# PRD Ref: §5.4, §4.3, §13 (P6 검증) · traps.md T15
"""P6 시세 수집 + PRI 계산.

    python -m src.collectors.price_run --check      # 필드 확정·토큰 캐시·손계산 검증
    python -m src.collectors.price_run --save       # price_snapshots + index_snapshots
    python -m src.collectors.price_run --save --limit 300
"""

from __future__ import annotations

import argparse
import collections
import time
from datetime import date, timedelta

from src.collectors.kis_client import KisClient, KisPathNotAllowed
from src.collectors.kis_prices import (
    PriceStats,
    fetch_avg_value_20d,
    fetch_daily_closes,
    fetch_foreign_flow_5d,
    fetch_index_closes,
    fetch_quote,
    high_52w_drawdown_pct,
    return_from_base_pct,
    rsi_14,
    trailing_return_pct,
    window_relative_return_pp,
    window_return_pct,
)
from src.collectors.quarter_prices import fetch_daily_closes_naver, quarter_end_closes
from src.db.supabase_client import (
    get_client,
    select_all,
    upsert_tolerating_missing_columns,
)
from src.screener.pri import PriInput, compute_pri
from src.utils.console import enable_utf8_stdout

SPOT = {"005930": ("삼성전자", "KOSPI"), "058470": ("리노공업", "KOSDAQ"),
        "403870": ("HPSP", "KOSDAQ")}
INDEX_OF_BOARD = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ"}
CHUNK_ROWS = 200  # 중간 저장 단위 — 중단돼도 여기까지는 남는다


def _qi(year: int, quarter: int) -> int:
    return year * 4 + quarter - 1


def _latest_screen_quarters(rows: list[dict]) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for row in rows:
        value = (int(row["fiscal_year"]), int(row["fiscal_quarter"]))
        previous = out.get(row["code"])
        if previous is None or _qi(*value) > _qi(*previous):
            out[row["code"]] = value
    return out


def _first_announcement_dates(rows: list[dict]) -> dict[tuple[str, int, int], str]:
    """평가 분기의 최초 실적 공시일."""
    out: dict[tuple[str, int, int], str] = {}
    for row in rows:
        if row.get("fiscal_year") is None or row.get("fiscal_quarter") is None:
            continue
        day = str(row.get("disclosed_at") or "")[:10]
        if len(day) != 10:
            continue
        key = (row["code"], int(row["fiscal_year"]), int(row["fiscal_quarter"]))
        if key not in out or day < out[key]:
            out[key] = day
    return out


def per_history_stats(
    net_income_by_quarter: dict[int, float | None],
    quarter_closes: dict[tuple[int, int], tuple[str, float]],
    current_close: float | None,
    current_shares: float | None,
    end_year: int,
    end_quarter: int,
    *,
    lookback: int = 9,
) -> tuple[float | None, float | None, int, float | None]:
    """현재 TTM PER과 과거 최대 9개 분기말 TTM PER 평균/할증률.

    DART 분기 EPS는 실제 적재 10,940행에서 0건이었다(T135). 따라서 화면의
    밸류에이션과 같은 `시가총액 / TTM 순이익`을 쓴다. 네이버 일봉은 수정주가라
    현재 발행주식수를 과거 종가에도 일관되게 적용한다.
    """
    end = _qi(end_year, end_quarter)

    def ttm_net_income(index: int) -> float | None:
        values = [net_income_by_quarter.get(i) for i in range(index - 3, index + 1)]
        if any(v is None for v in values):
            return None
        total = sum(float(v) for v in values if v is not None)
        return total if total > 0 else None

    current_ttm_np = ttm_net_income(end)
    current_market_cap = (
        current_close * current_shares if current_close and current_shares else None
    )
    current_per = (
        current_market_cap / current_ttm_np
        if current_market_cap and current_ttm_np else None
    )
    history: list[float] = []
    for index in range(end - lookback + 1, end + 1):
        ttm_np = ttm_net_income(index)
        year, quarter = index // 4, index % 4 + 1
        close_row = quarter_closes.get((year, quarter))
        if ttm_np and current_shares and close_row and close_row[1] > 0:
            history.append(close_row[1] * current_shares / ttm_np)
    average_per = sum(history) / len(history) if history else None
    premium = (
        (current_per / average_per - 1) * 100
        if current_per is not None and average_per is not None and average_per > 0
        else None
    )
    return current_per, average_per, len(history), premium


#: 마이그레이션 미적용으로 걷어낸 컬럼. 마지막에 화면에 밝힌다 —
#: 조용히 삼키면 "저장은 됐는데 그 값만 영영 비어 있는" 상태를 아무도 모른다.
_DROPPED: set[str] = set()


def _flush(db, rows: list[dict]) -> int:
    """★ 없는 컬럼 하나 때문에 수집 전체가 죽으면 안 된다(T18).

    같은 잡에서 이어 도는 스크리닝까지 함께 멈춘다 — 실측으로 겪었다.
    """
    saved, dropped = upsert_tolerating_missing_columns(
        db, "price_snapshots", rows, on_conflict="code,snap_date"
    )
    _DROPPED.update(dropped)
    return saved


def _window(months: int = 3) -> tuple[str, str]:
    today = date.today()
    return (today - timedelta(days=months * 31)).strftime("%Y%m%d"), today.strftime("%Y%m%d")


def build_return_fields(
    closes: dict[str, float],
    index_closes: dict[str, float],
    cutoffs: dict[str, str],
) -> dict[str, float | None]:
    """한 번 받은 12개월 일봉으로 절대·지수대비 수익률을 모두 만든다."""
    out: dict[str, float | None] = {}
    for window in ("1m", "3m", "6m", "12m"):
        out[f"ret_{window}"] = window_return_pct(closes, cutoffs[window])
    for window in ("3m", "6m", "12m"):
        out[f"rel_ret_{window}"] = window_relative_return_pp(
            closes, index_closes, cutoffs[window]
        )
    return out


def check() -> int:
    line = "═" * 74
    print(line)
    print("P6 검증 — KIS 시세 · PRI")
    print(line)

    client = KisClient()
    client.token()
    print(f"\n[1] 토큰 캐시 (T15)")
    print(f"    이번 실행 발급 횟수 {client.token_issue_count} "
          f"{'✓ 캐시 재사용' if client.token_issue_count == 0 else '(최초 발급)'}")
    print(f"    캐시 파일: {client.cache_path} · 존재 {client.cache_path.exists()}")

    print("\n[2] 주문 API 차단 (화이트리스트 강제)")
    for path in ("/uapi/domestic-stock/v1/trading/order-cash",
                 "/uapi/domestic-stock/v1/trading/inquire-balance"):
        try:
            client.get(path, tr_id="TTTC0802U", params={})
            print(f"    ✗ {path} — 차단되지 않았다")
            return 1
        except KisPathNotAllowed:
            print(f"    ✓ 차단 {path}")

    print("\n[3] 응답 필드 확정 (실호출 · 추정 아님)")
    stats = PriceStats()
    quotes = {}
    for code, (name, _) in SPOT.items():
        quote = fetch_quote(client, code, stats=stats)
        quotes[code] = quote
        if quote is None:
            print(f"    ✗ {name}({code}) 조회 실패")
            continue
        print(f"    {name}({code}) src={quote.source} 종가 {quote.close:,.0f} · "
              f"52주 {quote.low_52w:,.0f}~{quote.high_52w:,.0f} "
              f"(위치 {quote.pos_52w * 100:.0f}%) · PER {quote.per} · "
              f"시총 {quote.market_cap_krw / 1e12:.1f}조" if quote.market_cap_krw
              else f"    {name}({code}) src={quote.source} 종가 {quote.close}")

    print("\n[4] 3·6·12개월 절대·상대수익률 손계산 대조")
    cutoffs = {f"{months}m": _window(months)[0] for months in (1, 3, 6, 12)}
    begin, end = cutoffs["12m"], _window(12)[1]
    indexes = {name: fetch_index_closes(name, begin, end) for name in ("KOSPI", "KOSDAQ")}
    print(f"    구간 {begin}~{end} · KOSPI {len(indexes['KOSPI'])}일 · "
          f"KOSDAQ {len(indexes['KOSDAQ'])}일")
    rel_returns = {}
    for code, (name, board) in SPOT.items():
        closes = fetch_daily_closes_naver(code, begin, end)
        index_closes = indexes[INDEX_OF_BOARD[board]]
        fields = build_return_fields(closes, index_closes, cutoffs)
        common = sorted(
            day for day in set(closes) & set(index_closes) if day >= cutoffs["3m"]
        )
        rel = fields["rel_ret_3m"]
        rel_returns[code] = rel
        if rel is None or len(common) < 2:
            print(f"    ✗ {name}: 공통 거래일 부족")
            continue
        first, last = common[0], common[-1]
        stock = (closes[last] / closes[first] - 1) * 100
        index = (index_closes[last] / index_closes[first] - 1) * 100
        print(f"    {name}({code}) {board}")
        print(f"      종목 {closes[first]:>10,.0f} → {closes[last]:>10,.0f} = {stock:+7.2f}%")
        print(f"      지수 {index_closes[first]:>10,.2f} → {index_closes[last]:>10,.2f} = {index:+7.2f}%")
        print(f"      상대수익률 = {stock:+.2f} − {index:+.2f} = {rel:+.2f}%p "
              f"(공통 거래일 {len(common)}일)")
        print(
            "      "
            + " · ".join(
                f"{window} 절대 {fields[f'ret_{window}']:+.2f}% / "
                f"지수대비 {fields[f'rel_ret_{window}']:+.2f}%p"
                for window in ("3m", "6m", "12m")
                if fields[f"ret_{window}"] is not None
                and fields[f"rel_ret_{window}"] is not None
            )
        )

    print("\n[5] PRI 계산 (현재 수집값으로 측정 가능한 52주 축)")
    for code, (name, _) in SPOT.items():
        quote = quotes.get(code)
        if quote is None:
            continue
        pri = compute_pri(PriInput(
            high_52w_drawdown_pct=high_52w_drawdown_pct(quote.close, quote.high_52w),
        ))
        parts = {k: (round(v, 1) if v is not None else None) for k, v in pri.parts.items()}
        print(f"    {name:8} PRI {pri.pri if pri.pri is not None else '보류'} "
              f"(분모 {pri.denominator}) {parts}")

    print("\n[6] 네이버 폴백 (KIS 강제 실패)")
    fallback_stats = PriceStats()
    quote = fetch_quote(None, "005930", stats=fallback_stats)  # client=None → 폴백 경로
    print(f"    삼성전자 폴백 결과: src={quote.source if quote else None} · "
          f"종가 {quote.close if quote else None} · "
          f"52주 {quote.low_52w}~{quote.high_52w}")
    print(f"    naver_ok={fallback_stats.naver_ok} failed={fallback_stats.failed}")
    print(line)
    return 0


def save(limit: int | None) -> int:
    universe = select_all(
        "krx_universe", "code,name,board,is_excluded,market_cap_krw",
        order="market_cap_krw", desc=True,
    )
    targets = [u for u in universe if not u["is_excluded"]]
    if limit:
        targets = targets[:limit]

    cutoffs = {f"{months}m": _window(months)[0] for months in (1, 3, 6, 12)}
    begin, end = _window(36)[0], _window(12)[1]
    today = date.today().isoformat()
    client = KisClient()
    stats = PriceStats()

    screen_quarters = _latest_screen_quarters(select_all(
        "screen_results", "code,fiscal_year,fiscal_quarter"
    ))
    announcement_dates = _first_announcement_dates(select_all(
        "earnings_disclosures", "code,fiscal_year,fiscal_quarter,disclosed_at"
    ))
    net_income_by_code: dict[str, dict[int, float | None]] = collections.defaultdict(dict)
    for fund in select_all("quarterly_fundamentals", "code,fiscal_year,fiscal_quarter,np"):
        net_income_by_code[fund["code"]][_qi(int(fund["fiscal_year"]), int(fund["fiscal_quarter"]))] = (
            float(fund["np"]) if fund.get("np") is not None else None
        )

    indexes = {name: fetch_index_closes(name, begin, end) for name in ("KOSPI", "KOSDAQ")}
    db = get_client()
    index_rows = [
        {"index_name": name, "snap_date": f"{d[:4]}-{d[4:6]}-{d[6:]}", "close": close}
        for name, closes in indexes.items()
        for d, close in closes.items()
    ]
    for i in range(0, len(index_rows), 500):
        db.table("index_snapshots").upsert(
            index_rows[i : i + 500], on_conflict="index_name,snap_date"
        ).execute()
    print(f"✓ index_snapshots {len(index_rows)}행")

    print(
        f"대상 {len(targets)}종목 · 스로틀 {client.bucket.rate}/초 · "
        "종목당 KIS 2콜(시세+거래대금) + 네이버 일봉 1콜"
    )
    started = time.monotonic()
    payload: list[dict] = []
    measured = collections.Counter()
    ret5_ok = 0
    saved = 0
    for index, row in enumerate(targets, 1):
        quote = fetch_quote(client, row["code"], stats=stats)
        if quote is None:
            continue

        # ★ PRI P1(52주 고점), P2(발표일), P3(9분기 PER), P5(RSI)와
        #   D4(20일 평균 거래대금)는 일봉이 있어야 계산된다.
        return_fields = {
            "ret_1m": None, "ret_3m": None, "ret_6m": None, "ret_12m": None,
            "rel_ret_3m": None, "rel_ret_6m": None, "rel_ret_12m": None,
        }
        avg_value_20d = None
        ret_5d = None
        closes: dict[str, float] = {}
        try:
            # 네이버는 1콜로 12개월 전부를 준다. KIS 일봉은 짧은 구간이라 6·12M를
            # 요청해도 일부만 와 숫자는 그럴듯하지만 기간이 짧아질 수 있다.
            closes = fetch_daily_closes_naver(row["code"], begin, end)
            if closes:
                measured["naver_daily_ok"] += 1
        except Exception:
            closes = {}
        finally:
            time.sleep(0.12)  # quarter_prices와 같은 초당 약 8콜 상한
        if len(closes) < 2:
            try:
                # 장기 일봉 실패 시 기존 3M/5일 경로만 보존한다. 6·12M를 짧은
                # 구간으로 만들어내지는 않는다.
                closes = fetch_daily_closes(
                    client, row["code"], cutoffs["3m"], end
                )
            except Exception:
                closes = {}
        try:
            index_closes = indexes.get(INDEX_OF_BOARD.get(row["board"], "KOSPI"), {})
            return_fields = build_return_fields(closes, index_closes, cutoffs)
            ret_5d = trailing_return_pct(closes, 5)
            if ret_5d is not None:
                ret5_ok += 1
            for field, value in return_fields.items():
                if value is not None:
                    measured[field] += 1
        except Exception:
            pass
        drawdown = high_52w_drawdown_pct(quote.close, quote.high_52w)
        rsi = rsi_14(closes)
        evaluated = screen_quarters.get(row["code"])
        announcement_date = (
            announcement_dates.get((row["code"], *evaluated)) if evaluated else None
        )
        announcement_close = closes.get(announcement_date.replace("-", "")) if announcement_date else None
        announcement_return = return_from_base_pct(quote.close, announcement_close)
        current_per = average_per = premium = None
        average_quarters = 0
        if evaluated:
            current_shares = (
                quote.market_cap_krw / quote.close
                if quote.market_cap_krw and quote.close else None
            )
            current_per, average_per, average_quarters, premium = per_history_stats(
                net_income_by_code.get(row["code"], {}), quarter_end_closes(closes),
                quote.close, current_shares, *evaluated,
            )
        foreign_flow = None
        try:
            foreign_flow = fetch_foreign_flow_5d(row["code"], announcement_date)
        except Exception:
            pass
        pri = compute_pri(PriInput(
            high_52w_drawdown_pct=drawdown,
            announcement_return_pct=announcement_return,
            per_vs_9q_avg_pct=premium,
            foreign_net_ratio_5d_pct=foreign_flow.ratio_pct if foreign_flow else None,
            rsi_14=rsi,
        ))
        for key, value in pri.parts.items():
            if value is not None:
                measured[f"pri_{key}"] += 1
        try:
            avg_value_20d = fetch_avg_value_20d(client, row["code"], begin, end)
        except Exception:
            pass  # 일봉 실패가 시세 스냅샷 전체를 막지 않는다

        payload.append({
            "code": row["code"], "snap_date": today,
            "close": quote.close, "chg_pct": quote.chg_pct,
            "high_52w": quote.high_52w, "low_52w": quote.low_52w,
            "pos_52w": quote.pos_52w,
            "high_52w_drawdown_pct": drawdown,
            **return_fields,
            "ret_5d": ret_5d,
            "market_cap_krw": quote.market_cap_krw,
            "per": quote.per, "pbr": quote.pbr,
            "announcement_date": announcement_date,
            "announcement_close": announcement_close,
            "announcement_return_pct": announcement_return,
            "per_current_ttm": current_per,
            "per_avg_9q": average_per,
            "per_avg_quarters": average_quarters,
            "per_vs_9q_avg_pct": premium,
            "foreign_net_qty_5d": foreign_flow.net_qty if foreign_flow else None,
            "foreign_volume_5d": foreign_flow.volume if foreign_flow else None,
            "foreign_net_ratio_5d": foreign_flow.ratio_pct if foreign_flow else None,
            "rsi_14": rsi,
            # ★ P6에서는 '당일 누적거래대금'을 넣어 과대 추정이었다. 일봉 20일 평균으로 고친다.
            "avg_value_20d": avg_value_20d,
        })
        # ★ 중간 저장. 전 종목 수집은 종목당 2콜 × 1,100종목 ≈ 25분이라 중단될 여지가 크고,
        #   마지막에 한 번만 upsert하면 **끊긴 순간 한 행도 남지 않는다**(실제로 한 번 날렸다).
        #   snap_date로 멱등하므로 재실행해도 중복되지 않는다.
        if len(payload) >= CHUNK_ROWS:
            saved += _flush(db, payload)
            payload.clear()

        if index % 300 == 0:
            print(f"    {index}/{len(targets)} · {time.monotonic() - started:.0f}초 "
                  f"· KIS ok {stats.kis_ok} / 실패 {stats.kis_failed} · 저장 {saved}행")

    saved += _flush(db, payload)

    elapsed = time.monotonic() - started
    print(f"\n✓ price_snapshots {saved}행 · {elapsed:.0f}초 "
          f"({len(targets) / max(elapsed, 1):.1f}건/초)")
    print("  PRI 측정 " + " · ".join(
        f"{key.upper()} {measured[f'pri_{key}']}" for key in ("p1", "p2", "p3", "p4", "p5")
    ))
    print(
        "  기간별 수익률 측정 "
        + " · ".join(
            f"{field} {measured[field]}" for field in (
                "ret_1m", "ret_3m", "ret_6m", "ret_12m",
                "rel_ret_3m", "rel_ret_6m", "rel_ret_12m",
            )
        )
    )
    print(f"  네이버 장기 일봉 성공 {measured['naver_daily_ok']}/{len(targets)}종목")
    print(f"  최근 5거래일 상승률 측정 {ret5_ok}종목 — 발굴 목록의 마지막 열")
    if _DROPPED:
        # ★ 여기서 밝히지 않으면 "저장은 됐는데 그 값만 영영 비어 있는" 상태가 된다.
        print(f"  ⚠ DB에 없는 컬럼을 빼고 저장했다: {', '.join(sorted(_DROPPED))}")
        print(f"    → src/db/schema.sql의 마이그레이션을 SQL Editor에 적용하라 (T18).")
        print(f"    측정은 했지만 **저장되지 않았다** — 0이 아니라 미저장이다.")
    print(f"  KIS 성공 {stats.kis_ok} · KIS 실패 {stats.kis_failed} "
          f"· 네이버 폴백 성공 {stats.naver_ok} · 전부 실패 {stats.failed}")
    print(f"  오류 종류: {stats.errors or '없음'}")
    if "KisError" in stats.errors:
        print("  ⚠ EGW00201(유량 초과)이 섞여 있는지 확인하라 — 스로틀 마진을 낮춰야 한다.")
    return 0


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="P6 시세·PRI")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    if args.save:
        return save(args.limit)
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
