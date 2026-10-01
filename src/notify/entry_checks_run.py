# PRD Ref: §8.8, §10 — JARVIS 진입 필수 조건 M1·M2·M5 일일 계산 + 🔵 K1 기록
"""`entry_checks` 테이블을 매일 채운다. JARVIS가 anon SELECT로 읽는다.

    python -m src.notify.entry_checks_run                  # 읽기 전용 dry-run
    python -m src.notify.entry_checks_run --save           # entry_checks upsert + K1 기록/발송
    python -m src.notify.entry_checks_run --probe-kis 005930   # KIS 수급 응답 필드 실호출 대조

계산 순서(비용 최소화 · INTEGRATION_TASKS B-2):
  1. 전 종목 — DB만으로 M1 재무 조건 + PRI < 50
  2. 1단계 통과 종목만 — KIS 투자자별 매매(M5)
  3. 1단계 통과 종목만 — 네이버 확정 일봉으로 M1 가격 조건·M2 MACD·무효화선
     ★ M5 탈락 종목도 일봉을 본다. JARVIS 🟡 관찰은 M1∧M2에 M3·M4·M5 중 2개라
       M5 없이도 성립한다 — M5 탈락으로 M2를 비우면 🟡가 구조적으로 사라진다(ADR 24).
결과는 통과·탈락 모두 저장한다. 1단계 탈락 행은 m2_detail·m5_detail이 null이다.
멱등: 같은 `check_date`는 upsert로 덮는다. 선별에 LLM을 쓰지 않는다(ADR 3).
"""

from __future__ import annotations

import argparse
import collections
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from src.config.constants import (
    ENTRY_DAILY_LOOKBACK_CALENDAR_DAYS,
    ENTRY_M1_PRI_MAX,
    K1_GRADES,
    K1_LOOKBACK_TRADING_DAYS,
    TECHNICAL_MIN_DAILY_FETCH_RATE,
    TECHNICAL_TELEGRAM_ENABLED,
)
from src.screener.entry_checks import (
    Bar,
    all_of,
    confirmed_bars,
    first_session_after,
    invalidation,
    k1_breakout,
    m1_fundamental,
    m1_price,
    m2_check,
    m5_check,
)
from src.utils.console import enable_utf8_stdout

KST = ZoneInfo("Asia/Seoul")
TABLE = "entry_checks"
KIND_BREAKOUT = "earnings_breakout"
SCREEN_COLUMNS = "code,fiscal_year,fiscal_quarter,grade,pri,base_effect_warning"
FUNDAMENTAL_COLUMNS = (
    "code,fiscal_year,fiscal_quarter,revenue,op,revenue_yoy,op_yoy,op_status_label,"
    "ttm_revenue,ttm_op"
)
UPSERT_CHUNK = 500


def _qi(year: int, quarter: int) -> int:
    return year * 4 + quarter - 1


def _iso(day: str) -> str:
    return f"{day[:4]}-{day[4:6]}-{day[6:8]}"


# ═══ DB 행 → 판정 입력 (순수) ══════════════════════════════════════
def fundamental_series(rows: list[dict]) -> dict[str, dict[int, dict]]:
    out: dict[str, dict[int, dict]] = collections.defaultdict(dict)
    for row in rows:
        if row.get("fiscal_year") is None or row.get("fiscal_quarter") is None:
            continue
        quarter = int(row["fiscal_quarter"])
        if not 1 <= quarter <= 4:
            continue
        out[str(row["code"])][_qi(int(row["fiscal_year"]), quarter)] = row
    return out


def latest_screens(rows: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for row in rows:
        if row.get("fiscal_year") is None or row.get("fiscal_quarter") is None:
            continue
        code = str(row.get("code") or "")
        key = _qi(int(row["fiscal_year"]), int(row["fiscal_quarter"]))
        if code not in latest or key > _qi(
            int(latest[code]["fiscal_year"]), int(latest[code]["fiscal_quarter"])
        ):
            latest[code] = row
    return latest


def annual_consensus_by_code(rows: list[dict], year: int) -> dict[str, dict]:
    """올해(KST) 네이버 연간 전망의 최신 스냅샷. `fiscal_quarter=0`이 연간이다."""
    latest: dict[str, dict] = {}
    for row in rows:
        if row.get("source") != "naver" or int(row.get("fiscal_quarter") or -1) != 0:
            continue
        if int(row.get("fiscal_year") or 0) != year:
            continue
        code = str(row.get("code") or "")
        if code not in latest or str(row.get("snapshot_at") or "") > str(latest[code].get("snapshot_at") or ""):
            latest[code] = row
    return latest


def prior_year_actual(series: dict[int, dict], year: int) -> tuple[float | None, float | None] | None:
    """전년(회계연도 `year`) 4개 분기 매출·영업이익 합. 한 분기라도 없으면 None.

    TTM 칸을 쓰지 않는 이유: 4Q 행의 TTM은 그 시점 재작성이 반영되지 않을 수 있고,
    분기 합은 연간 사업보고서 − 3Q 누적(T1)으로 이미 분해된 같은 원천이다.
    """
    rows = [series.get(_qi(year, quarter)) for quarter in (1, 2, 3, 4)]
    if any(row is None for row in rows):
        return None
    revenue = [row.get("revenue") for row in rows if row]
    op = [row.get("op") for row in rows if row]
    if any(value is None for value in (*revenue, *op)):
        return None
    return float(sum(float(v) for v in revenue)), float(sum(float(v) for v in op))


def first_announcements(rows: list[dict]) -> dict[tuple[str, int, int], str]:
    """회계분기별 첫 실적 공시일(YYYY-MM-DD). 날짜가 없으면 추측하지 않는다."""
    out: dict[tuple[str, int, int], str] = {}
    for row in rows:
        if row.get("fiscal_year") is None or row.get("fiscal_quarter") is None:
            continue
        day = str(row.get("disclosed_at") or "")[:10].replace("/", "-")
        if len(day) == 8 and day.isdigit():
            day = _iso(day)
        if len(day) != 10:
            continue
        key = (str(row["code"]), int(row["fiscal_year"]), int(row["fiscal_quarter"]))
        if key not in out or day < out[key]:
            out[key] = day
    return out


def stage1(
    code: str, screen: dict | None, series: dict[int, dict], *,
    annual: dict | None, year: int,
) -> dict:
    """DB만으로 판정하는 M1 재무 + PRI. 일봉·수급을 부를지 여기서 정한다."""
    if screen is None:
        return {"pass": None, "reason": "no_screen_result"}
    index = _qi(int(screen["fiscal_year"]), int(screen["fiscal_quarter"]))
    fin = m1_fundamental(
        series, index,
        base_effect_warning=screen.get("base_effect_warning"),
        annual_consensus=annual,
        prior_year_actual=prior_year_actual(series, year - 1),
    )
    pri = screen.get("pri")
    pri_ok = None if pri is None else float(pri) < ENTRY_M1_PRI_MAX
    fin["fiscal_year"] = int(screen["fiscal_year"])
    fin["fiscal_quarter"] = int(screen["fiscal_quarter"])
    fin["grade"] = screen.get("grade")
    fin["pri_ok"] = pri_ok
    fin["stage1_pass"] = fin["pass"] is True and pri_ok is True
    return fin


def compose_row(
    code: str, check_date: str, fin: dict, *,
    bars: list[Bar] | None, flow: dict | None, announcement_date: str | None,
    pri: float | None, notes: list[str], computed_at: str,
) -> dict:
    """한 종목의 `entry_checks` 행. 측정하지 않은 단계는 null로 남긴다."""
    m1_detail = {key: value for key, value in fin.items() if key != "pass"}
    m1_detail["stage"] = "price" if bars else "fundamental"
    m1_detail["pri"] = pri
    # 가격 조건(조정·횡보 ∧ PRI<50)은 확정 일봉이 오늘 것일 때만 판정한다.
    # 일봉을 안 봤거나(1단계 탈락) 못 봤으면 PRI만으로 탈락 여부를 가린다.
    price_pass: bool | None = fin.get("pri_ok") if fin.get("pri_ok") is False else None
    m2_pass = m2_detail = None
    lows = {"low_10d": None, "low_20d": None, "invalidation_price": None}
    if bars:
        price = m1_price(bars, announcement_date=announcement_date, pri=pri)
        m1_detail.update({key: value for key, value in price.items() if key not in ("pass", "checks")})
        m1_detail["price_checks"] = price["checks"]
        m1_detail["bars_as_of"] = bars[-1].date
        lows = invalidation(bars, price["price_state"])
        if bars[-1].date != check_date:
            notes.append("stale_bars")  # 거래정지·일봉 지연 — 오늘 판정이 아니다
        else:
            price_pass = price["pass"]
            m2 = m2_check(bars)
            if m2 is not None:
                m2_pass = m2.pop("pass")
                m2_detail = m2
    m1_pass = all_of([fin.get("pass"), price_pass])
    m5_pass = m5_detail = None
    if flow is not None:
        m5_detail = dict(flow)
        m5_pass = m5_detail.pop("pass")
        if m5_detail.get("as_of") != check_date:
            notes.append("stale_flow")
            m5_pass = None
    if notes:
        m1_detail["notes"] = sorted(set(notes))
    return {
        "code": code,
        "check_date": _iso(check_date),
        "fiscal_year": fin.get("fiscal_year"),
        "fiscal_quarter": fin.get("fiscal_quarter"),
        "m1_pass": m1_pass,
        "m1_detail": m1_detail,
        "m2_pass": m2_pass,
        "m2_detail": m2_detail,
        "m5_pass": m5_pass,
        "m5_detail": m5_detail,
        "invalidation_price": lows["invalidation_price"],
        "low_10d": lows["low_10d"],
        "low_20d": lows["low_20d"],
        "computed_at": computed_at,
    }


def to_bars(rows: list[tuple[str, float, float, float, float, float]]) -> list[Bar]:
    return [
        Bar(day, open_ or None, high or None, low or None, close, volume)
        for day, open_, high, low, close, volume in rows
    ]


def k1_targets(
    disclosures: list[dict], screens: list[dict], sessions: list[str], check_date: str,
) -> list[dict]:
    """잠정실적 공시 중 ★·○ · 기저효과 경고 없음 · D0가 최근 N거래일 안인 것."""
    by_key = {
        (str(row["code"]), int(row["fiscal_year"]), int(row["fiscal_quarter"])): row
        for row in screens
        if row.get("fiscal_year") is not None and row.get("fiscal_quarter") is not None
    }
    recent = [day for day in sessions if day <= check_date][-K1_LOOKBACK_TRADING_DAYS:]
    targets: dict[tuple[str, int, int], dict] = {}
    for row in disclosures:
        if row.get("doc_type") != "provisional" or row.get("fiscal_year") is None:
            continue
        key = (str(row["code"]), int(row["fiscal_year"]), int(row["fiscal_quarter"] or 0))
        screen = by_key.get(key)
        if not screen or screen.get("grade") not in K1_GRADES or screen.get("base_effect_warning") is not False:
            continue
        disclosed = str(row.get("disclosed_at") or "")[:10].replace("-", "")
        if len(disclosed) != 8:
            continue
        detected = row.get("detected_at")
        detected_kst = None
        if detected:
            try:
                detected_kst = datetime.fromisoformat(str(detected).replace("Z", "+00:00")).astimezone(KST)
            except ValueError:
                detected_kst = None
        d0 = first_session_after(disclosed, detected_kst, sessions)
        if d0 is None or d0 not in recent:
            continue
        if key not in targets or str(row.get("rcept_no")) < str(targets[key].get("rcept_no")):
            targets[key] = {
                "code": key[0], "fiscal_year": key[1], "fiscal_quarter": key[2],
                "d0": d0, "grade": screen.get("grade"), "rcept_no": row.get("rcept_no"),
                "disclosed_on": disclosed,
            }
    return sorted(targets.values(), key=lambda item: (item["d0"], item["code"]))


def k1_message(name: str, target: dict, result: dict) -> str:
    from src.notify.telegram import PREFIX, esc

    return "\n".join([
        f"{PREFIX}<b>🔵 실적 돌파 관찰 — 진입 신호 아님</b>",
        f"{esc(name)} <code>{target['code']}</code> · {target['grade']} · "
        f"{target['fiscal_year']}.{target['fiscal_quarter']}Q 잠정실적",
        f"D0 {_iso(target['d0'])} · 시가 갭 {result['gap_open_pct']:+.1f}% · "
        f"종가 {result['close_return_pct']:+.1f}% · 거래량 ×{result['volume_mult']:.1f} · "
        f"종가위치 {result['close_location']:.2f}",
        f"무장 기준 D0 저가 {result['d0_low']:,.0f}원 — 이후 M1~M5 통과 시 PEAD_PB 후보",
    ])


# ═══ I/O ═══════════════════════════════════════════════════════════
def trading_sessions(now_kst: datetime) -> list[str]:
    """KOSPI 지수 확정 일봉의 날짜 = 한국 거래일 달력(휴장일 추측 없음)."""
    from src.collectors.kis_prices import fetch_index_closes

    begin = (now_kst - timedelta(days=ENTRY_DAILY_LOOKBACK_CALENDAR_DAYS)).strftime("%Y%m%d")
    closes = fetch_index_closes("KOSPI", begin, now_kst.strftime("%Y%m%d"))
    bars = confirmed_bars([Bar(day, None, None, None, close) for day, close in closes.items()], now_kst)
    return [bar.date for bar in bars]


def fetch_flow(client, code: str) -> dict | None:
    from src.collectors.kis_prices import fetch_investor_daily_kis, fetch_investor_daily_naver

    source = "kis"
    rows: list[tuple[str, int, int]] = []
    if client is not None:
        try:
            rows = fetch_investor_daily_kis(client, code)
        except Exception:
            rows = []  # KIS 장애(토큰·유량·HTTP)는 네이버로 폴백하고 `source`로 드러낸다(PRD §5.4)
    if not rows:
        source = "naver"
        rows = fetch_investor_daily_naver(code)
    return m5_check(rows, source=source)


def _kis_client():
    from src.collectors.kis_client import KisClient
    from src.utils.env import optional_env

    if not optional_env("KIS_APP_KEY") or not optional_env("KIS_APP_SECRET"):
        return None
    return KisClient()


def probe_kis(code: str) -> int:
    """KIS 투자자 응답의 실제 필드를 1회 출력한다(PRD §5.4 — 필드명은 실호출로 확정)."""
    from src.collectors.kis_prices import INVESTOR_PATH, parse_kis_investor_rows
    from src.config.constants import KIS_TR_INVESTOR

    client = _kis_client()
    if client is None:
        print("KIS_APP_KEY/KIS_APP_SECRET 미설정")
        return 1
    body = client.get(
        INVESTOR_PATH, tr_id=KIS_TR_INVESTOR,
        params={"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
    )
    output = body.get("output") or []
    print(f"rt_cd={body.get('rt_cd')} msg={body.get('msg1')} rows={len(output)}")
    if output:
        print("첫 행 필드:", ", ".join(sorted(output[0])))
        for row in output[:3]:
            print({k: row.get(k) for k in ("stck_bsop_date", "frgn_ntby_qty", "orgn_ntby_qty", "prsn_ntby_qty")})
    parsed = parse_kis_investor_rows(body)
    print(f"파싱 {len(parsed)}행 · 최신 {parsed[:3]}")
    return 0 if parsed else 1


def _write_summary(path: str | None, summary: dict) -> None:
    if path:
        Path(path).write_text(json.dumps(summary, ensure_ascii=False) + "\n", encoding="utf-8")


def run(*, save: bool, send: bool, codes: list[str] | None = None, summary_path: str | None = None) -> int:
    from src.collectors.quarter_prices import fetch_daily_ohlcv_naver
    from src.db.supabase_client import get_client, select_all, upsert_tolerating_missing_columns

    now = datetime.now(KST)
    sessions = trading_sessions(now)
    if not sessions:
        print("⚠ KOSPI 거래일 달력을 받지 못했다 — 계산 중단")
        _write_summary(summary_path, {"date": now.date().isoformat(), "status": "calendar_failed"})
        return 1
    check_date = sessions[-1]
    computed_at = datetime.now(timezone.utc).isoformat()
    print(f"entry_checks · check_date {_iso(check_date)} (확정 종가 기준) · 실행 {now:%Y-%m-%d %H:%M} KST")

    universe = {
        str(row["code"]): row for row in select_all("krx_universe", "code,name,is_excluded")
        if row.get("is_excluded") is not True
    }
    screen_rows = select_all("screen_results", SCREEN_COLUMNS)
    screens = latest_screens(screen_rows)
    series = fundamental_series(select_all("quarterly_fundamentals", FUNDAMENTAL_COLUMNS))
    consensus = annual_consensus_by_code(
        select_all(
            "consensus_snapshots", "code,fiscal_year,fiscal_quarter,revenue_est,op_est,source,snapshot_at",
            filters={"fiscal_quarter": 0},
        ),
        now.year,
    )
    disclosures = select_all(
        "earnings_disclosures", "code,fiscal_year,fiscal_quarter,disclosed_at,detected_at,doc_type,rcept_no",
    )
    announcements = first_announcements(disclosures)
    targets = sorted(code for code in universe if code in screens)
    if codes:
        targets = [code for code in targets if code in set(codes)]

    funnel = collections.Counter()
    stage1_rows: dict[str, dict] = {}
    for code in targets:
        fin = stage1(code, screens.get(code), series.get(code, {}), annual=consensus.get(code), year=now.year)
        stage1_rows[code] = fin
        funnel["evaluated"] += 1
        funnel["m1_fundamental"] += fin.get("pass") is True
        funnel["stage1"] += bool(fin.get("stage1_pass"))
    passed = [code for code in targets if stage1_rows[code].get("stage1_pass")]
    print(f"1단계(DB) 평가 {funnel['evaluated']} · M1 재무 통과 {funnel['m1_fundamental']} · +PRI<{ENTRY_M1_PRI_MAX} {len(passed)}")

    client = _kis_client() if passed else None
    flows: dict[str, dict | None] = {}
    flow_failed = 0
    for code in passed:
        try:
            flows[code] = fetch_flow(client, code)
        except Exception as exc:
            flow_failed += 1
            flows[code] = None
            print(f"  ⚠ {code} 수급: {type(exc).__name__}")
    funnel["m5"] = sum(1 for flow in flows.values() if flow and flow.get("pass"))
    sources = collections.Counter((flow or {}).get("source") for flow in flows.values() if flow)
    print(f"2단계(KIS 수급) {len(passed)}종목 · M5 통과 {funnel['m5']} · 원천 {dict(sources)} · 실패 {flow_failed}")

    begin = (now - timedelta(days=ENTRY_DAILY_LOOKBACK_CALENDAR_DAYS)).strftime("%Y%m%d")
    bars_by_code: dict[str, list[Bar]] = {}
    bar_failed = 0

    def bars_of(code: str) -> list[Bar] | None:
        nonlocal bar_failed
        if code in bars_by_code:
            return bars_by_code[code]
        try:
            bars = confirmed_bars(to_bars(fetch_daily_ohlcv_naver(code, begin, now.strftime("%Y%m%d"))), now)
        except Exception as exc:
            bar_failed += 1
            print(f"  ⚠ {code} 일봉: {type(exc).__name__}")
            return None
        finally:
            time.sleep(0.12)
        bars_by_code[code] = bars
        return bars

    rows: list[dict] = []
    for code in targets:
        fin = stage1_rows[code]
        screen = screens[code]
        notes: list[str] = []
        bars = bars_of(code) if fin.get("stage1_pass") else None
        if fin.get("stage1_pass") and not bars:
            notes.append("daily_fetch_failed")
        announcement = announcements.get((code, int(screen["fiscal_year"]), int(screen["fiscal_quarter"])))
        rows.append(compose_row(
            code, check_date, fin, bars=bars, flow=flows.get(code),
            announcement_date=announcement, pri=screen.get("pri"),
            notes=notes, computed_at=computed_at,
        ))
    funnel["m1"] = sum(1 for row in rows if row["m1_pass"] is True)
    funnel["m2"] = sum(1 for row in rows if row["m2_pass"] is True)
    funnel["m1_m2"] = sum(1 for row in rows if row["m1_pass"] is True and row["m2_pass"] is True)
    funnel["m1_m2_m5"] = sum(
        1 for row in rows if row["m1_pass"] is True and row["m2_pass"] is True and row["m5_pass"] is True
    )
    print(
        f"3단계(확정 일봉) {len(bars_by_code)}종목 · M1 {funnel['m1']} · M2 {funnel['m2']} · "
        f"M1∧M2 {funnel['m1_m2']} · M1∧M2∧M5 {funnel['m1_m2_m5']} · 일봉 실패 {bar_failed}"
    )
    for row in rows:
        if row["m1_pass"] is True and row["m2_pass"] is True:
            name = universe.get(row["code"], {}).get("name") or row["code"]
            detail = row["m1_detail"]
            print(
                f"  ✓ {name}({row['code']}) {detail.get('price_state')} · PRI {detail.get('pri')} · "
                f"M2 {row['m2_detail'].get('state')} · M5 {row['m5_pass']} "
                f"{(row['m5_detail'] or {}).get('path')} · 무효화 {row['invalidation_price']}"
            )

    # 🔵 K1 — 잠정실적 D0 돌파. 진입 신호가 아니며 notifications에 기록한다.
    k1_list = k1_targets(disclosures, screen_rows, sessions, check_date)
    breakouts: list[tuple[dict, dict]] = []
    for target in k1_list:
        bars = bars_of(target["code"])
        result = k1_breakout(bars or [], target["d0"])
        if result is not None and result["pass"] is True:
            breakouts.append((target, result))
    print(f"🔵 K1 대상 {len(k1_list)} · 돌파 {len(breakouts)}")

    attempted = len(passed) + len(k1_list)
    summary = {
        "date": now.date().isoformat(), "check_date": _iso(check_date), "status": "complete",
        "funnel": dict(funnel), "k1_targets": len(k1_list), "k1_breakouts": len(breakouts),
        "saved": 0, "k1_recorded": 0,
    }
    if attempted and bar_failed / attempted > 1 - TECHNICAL_MIN_DAILY_FETCH_RATE:
        print(f"⚠ 일봉 실패율 {bar_failed / attempted:.1%} — 저장은 하되 실패로 드러낸다")
        summary["status"] = "scan_degraded"

    if not save:
        print("\n(--save 미지정 — entry_checks·notifications 쓰기 0건)")
        _write_summary(summary_path, summary)
        return 0 if summary["status"] == "complete" else 1

    saved, dropped = upsert_tolerating_missing_columns(
        get_client(), TABLE, rows, on_conflict="code,check_date", chunk=UPSERT_CHUNK,
    )
    summary["saved"] = saved
    print(f"✓ {TABLE} {saved}행 upsert (check_date {_iso(check_date)})")
    if dropped:
        print(f"  ⚠ DB에 없는 컬럼을 빼고 저장했다: {', '.join(dropped)} — docs/migrations/entry_checks.sql 적용 필요")

    from src.notify.telegram import TelegramClient, already_sent, record_notification, send_once

    telegram = TelegramClient() if send and TECHNICAL_TELEGRAM_ENABLED and breakouts else None
    for target, result in breakouts:
        key = (target["code"], target["fiscal_year"], target["fiscal_quarter"])
        if already_sent(*key, KIND_BREAKOUT):
            continue
        payload = {
            **result, "grade": target["grade"], "rcept_no": target["rcept_no"],
            "disclosed_on": _iso(target["disclosed_on"]), "entry_signal": False,
            "basis": "K1_kr", "telegram": telegram is not None,
        }
        name = universe.get(target["code"], {}).get("name") or target["code"]
        if telegram is not None:
            ok = send_once(
                telegram, code=key[0], fiscal_year=key[1], fiscal_quarter=key[2],
                kind=KIND_BREAKOUT, text=k1_message(name, target, result), payload=payload,
            )
        else:
            record_notification(*key, KIND_BREAKOUT, payload)
            ok = True
        summary["k1_recorded"] += bool(ok)
    print(f"🔵 K1 기록 {summary['k1_recorded']}건 · 텔레그램 {'켜짐' if TECHNICAL_TELEGRAM_ENABLED else '꺼짐(DB 기록만)'}")
    _write_summary(summary_path, summary)
    return 0 if summary["status"] == "complete" else 1


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="JARVIS entry_checks(M1·M2·M5) + K1 실적 돌파")
    parser.add_argument("--save", action="store_true", help="entry_checks upsert + K1 기록")
    parser.add_argument("--send", action="store_true", help="K1 텔레그램 발송(TECHNICAL_TELEGRAM_ENABLED일 때만)")
    parser.add_argument("--codes", help="쉼표 구분 종목코드만 계산(점검용)")
    parser.add_argument("--summary-path", help="실행 요약 JSON 경로")
    parser.add_argument("--probe-kis", metavar="CODE", help="KIS 투자자 응답 필드 실호출 대조")
    args = parser.parse_args()
    if args.probe_kis:
        return probe_kis(args.probe_kis)
    codes = [code.strip() for code in args.codes.split(",")] if args.codes else None
    return run(save=args.save, send=args.send, codes=codes, summary_path=args.summary_path)


if __name__ == "__main__":
    raise SystemExit(main())
