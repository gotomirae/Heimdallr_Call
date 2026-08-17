# PRD Ref: §8, §13 (P8 검증)
"""P8 텔레그램 발송 실행.

    python -m src.notify.run --preview                # 렌더만 (발송 안 함)
    python -m src.notify.run --send --code 005930     # 실제 발송 1건
    python -m src.notify.run --send --code 005930     # 다시 → 중복 차단 확인
"""

from __future__ import annotations

import argparse
import json
from datetime import date

from src.config.constants import DASHBOARD_URL_DEFAULT, NOTIFY_GRADES
from src.finance.derive import (
    op_surprise_label,
    op_surprise_pct,
    revenue_surprise_pct,
)
from src.db.supabase_client import select_all
from src.notify.telegram import (
    MAX_MESSAGE_CHARS,
    TelegramClient,
    TelegramMethodNotAllowed,
    already_sent,
    send_once,
    truncate,
)
from src.analysis.analyze import sanitize_payload
from src.notify.links import dart_report_url, naver_stock_url
from src.notify.templates import KIND_DAILY, KIND_FLASH, daily_digest, flash_message
from src.utils.console import enable_utf8_stdout
from src.utils.env import optional_env

FUND_COLUMNS = (
    "code,fiscal_year,fiscal_quarter,revenue,op,np,revenue_yoy,op_yoy,np_yoy,opm,"
    "opm_yoy_delta,ttm_opm_delta,is_estimate,source,delta_from_preliminary"
)
SCREEN_COLUMNS = (
    "code,fiscal_year,fiscal_quarter,gate_detail,base_effect_warning,"
    "score_flash,score_a,score_b,score_c,score_d,has_consensus,pri,pri_detail,grade,"
    "raw_a1,raw_a2,raw_a3,raw_a4,raw_b1,raw_b2,raw_b3,raw_b4,"
    "raw_c1,raw_c2,raw_d1,raw_d2,raw_d3,raw_d4"
)
#: 축별 배점. 미측정 축은 분모에서 빠진다(ADR 2) — 0점 처리가 아니다.
AXIS_WEIGHTS = {"a": 35, "b": 32, "c": 15, "d": 18}


def ttm_net_income(funds: list[dict], year: int, quarter: int) -> float | None:
    """해당 분기까지의 4분기 누적 순이익. **PER을 다시 계산하기 위한 분모다.**

    ★ KIS가 주는 `per`은 과거 12개월 EPS 기준(후행)이라 실적이 급가속하면 크게 과대평가된다.
      실측: 삼성전자 후행 PER 40.83 (EPS 6,564원 기준) — 그런데 2026.1Q 순이익만
      472,253억이다. 이 시스템이 겨냥하는 구간이 정확히 그 왜곡이 가장 큰 구간이므로,
      후행 PER만 보여주면 "이미 반영됐다"는 정반대 결론으로 읽힌다.
    ★ 4개 분기가 다 모이지 않으면 **추정하지 않고 None**을 준다(연율화 금지).
    """
    index = year * 4 + (quarter - 1)
    by_index = {f["fiscal_year"] * 4 + (f["fiscal_quarter"] - 1): f for f in funds}
    values = [by_index.get(index - o, {}).get("np") for o in range(4)]
    if any(v is None for v in values):
        return None
    return sum(float(v) for v in values)


def per_by_quarter(funds: list[dict], market_cap: float | None) -> list[dict]:
    """분기별 PER — **현재 시총 기준**의 TTM 순이익 PER 궤적.

    ★ 과거 주가를 저장하지 않으므로 '그때의 PER'이 아니다.
      "지금 사면 그 분기까지의 이익 대비 몇 배인가"이고, 이익이 따라붙으면서
      배수가 내려오는 모습을 보여준다. **이 구분을 화면에 밝혀야 한다** —
      안 밝히면 과거 밸류에이션으로 잘못 읽힌다.
    """
    if not market_cap:
        return []
    out: list[dict] = []
    for row in funds:
        ttm = ttm_net_income(funds, row["fiscal_year"], row["fiscal_quarter"])
        out.append({
            "fiscal_year": row["fiscal_year"],
            "fiscal_quarter": row["fiscal_quarter"],
            "per": (market_cap / ttm) if ttm and ttm > 0 else None,
        })
    return out


def forward_per(consensus: dict | None, market_cap: float | None) -> float | None:
    """컨센서스 순이익 추정으로 만든 F.PER.

    ★ `price_snapshots.fwd_per`은 전 행이 비어 있어(미수집) 쓸 수 없다.
      컨센서스가 있는 종목(2026.2Q 207종목)만 계산되고 나머지는 None이다 —
      **없는 값을 만들지 않는다.**
    ★ 분기 추정이라 연율화(×4)하지 않는다. 계절성이 강해 왜곡된다(ADR 7).
      대신 직전 3분기 실적 + 이번 분기 추정으로 TTM을 만든다.
    """
    if not consensus or not market_cap:
        return None
    np_est = consensus.get("np_est")
    if np_est is None or np_est <= 0:
        return None
    return None if not consensus.get("ttm_with_estimate") else (
        market_cap / consensus["ttm_with_estimate"]
    )


def market_cap_rank(uni: dict, code: str) -> tuple[int | None, int]:
    """같은 시장 안에서의 시총 순위. 서술형 설명에 쓴다.

    ★ 순위는 '큰 회사인가'를 한 마디로 알려준다 — 1,552조원이라는 숫자만으로는
      그게 1위인지 10위인지 모른다.
    """
    row = uni.get(code) or {}
    board, cap = row.get("board"), row.get("market_cap_krw")
    peers = [
        u["market_cap_krw"] for u in uni.values()
        if u.get("board") == board and u.get("market_cap_krw")
    ]
    if not cap or not peers:
        return None, len(peers)
    return sum(1 for c in peers if c > cap) + 1, len(peers)


def build_flash_context(code: str, year: int, quarter: int) -> dict:
    uni = {u["code"]: u for u in select_all(
        "krx_universe",
        "code,name,board,industry,products,market_cap_krw,sector_caveat")}
    row = uni.get(code) or {}
    cap_rank, peer_count = market_cap_rank(uni, code)

    funds = [f for f in select_all("quarterly_fundamentals", FUND_COLUMNS)
             if f["code"] == code]
    funds.sort(key=lambda f: (f["fiscal_year"], f["fiscal_quarter"]))
    cur = next((f for f in funds
                if f["fiscal_year"] == year and f["fiscal_quarter"] == quarter), {})
    prev = funds[funds.index(cur) - 1] if cur in funds and funds.index(cur) > 0 else {}

    screen = next(
        (s for s in select_all("screen_results", SCREEN_COLUMNS)
         if s["code"] == code and s["fiscal_year"] == year and s["fiscal_quarter"] == quarter),
        {},
    )

    # 최신 시세 스냅샷 1건 — PER/PBR의 출처를 여기 하나로 고정한다.
    snaps = sorted(
        (p for p in select_all("price_snapshots", "code,snap_date,per,pbr,market_cap_krw")
         if p["code"] == code),
        key=lambda p: p["snap_date"],
    )
    price = snaps[-1] if snaps else {}
    ttm_np = ttm_net_income(funds, year, quarter)
    cap_for_per = price.get("market_cap_krw") or row.get("market_cap_krw")
    per_ttm = (
        float(cap_for_per) / ttm_np
        if ttm_np and ttm_np > 0 and cap_for_per else None
    )

    # ── 컨센서스 ──────────────────────────────────────────────
    # ★ 분기를 반드시 맞춘다. 다른 분기 추정치로 서프라이즈를 계산하면 조용히 틀린다.
    cons = next(
        (c for c in select_all(
            "consensus_snapshots",
            "code,fiscal_year,fiscal_quarter,n_estimates,revenue_est,op_est,np_est")
         if c["code"] == code and c["fiscal_year"] == year
         and c["fiscal_quarter"] == quarter),
        {},
    )
    rev_surprise = revenue_surprise_pct(cur.get("revenue"), cons.get("revenue_est"))
    op_surprise = op_surprise_pct(cur.get("op"), cons.get("op_est"))
    op_surprise_lbl = op_surprise_label(cur.get("op"), cons.get("op_est"))

    # ── Forward PER — **다음 분기부터 4분기**의 추정 순이익 기준 ──────────
    #
    # ★ 재료는 **연간 컨센서스**다(`fiscal_quarter = 0`). 분기 컨센은 한 분기뿐이라
    #   "향후 4분기"를 만들 수 없다.
    # ★ 연간 추정에서 **이미 발표된 분기를 빼면** 남은 분기의 추정이 나온다.
    #   그것만으로는 4분기가 안 되므로, 모자란 만큼은 **연간 추정의 분기 평균**으로
    #   이어 붙인다 — 다음 해 추정치는 수집하지 않기 때문이다.
    #   이건 추정 위의 추정이라 `fwd_per_basis`로 근거를 함께 넘겨 화면에 밝힌다.
    annual = next(
        (c for c in select_all(
            "consensus_snapshots",
            "code,fiscal_year,fiscal_quarter,np_est,source")
         if c["code"] == code and c["fiscal_quarter"] == 0
         and c["fiscal_year"] >= year),
        {},
    )
    fwd_per, fwd_basis = None, None
    annual_np = annual.get("np_est")
    if annual_np and annual_np > 0 and cap_for_per:
        by_index = {f["fiscal_year"] * 4 + (f["fiscal_quarter"] - 1): f for f in funds}
        fy = annual["fiscal_year"]
        # 그 회계연도에서 이미 발표된 분기 순이익 합
        reported = [
            by_index.get(fy * 4 + (q - 1), {}).get("np") for q in (1, 2, 3, 4)
        ]
        done = [v for v in reported if v is not None]
        remaining_quarters = 4 - len(done)
        if remaining_quarters > 0:
            remaining_np = float(annual_np) - sum(float(v) for v in done)
            per_quarter = remaining_np / remaining_quarters
            # 다음 4분기 = 남은 분기 + 그 다음 해 초반(연간 분기평균으로 이어 붙임)
            next4 = remaining_np + per_quarter * (4 - remaining_quarters)
            fwd_per = (float(cap_for_per) / next4) if next4 > 0 else None
            fwd_basis = f"{fy}년 컨센 {annual_np / 1e8:,.0f}억 기준"
        else:
            # 그 해가 다 발표됐으면 연간 추정 자체가 다음 4분기다
            fwd_per = float(cap_for_per) / float(annual_np)
            fwd_basis = f"{fy}년 컨센 기준"

    analysis = next(
        (a for a in select_all("analyses", "code,fiscal_year,fiscal_quarter,payload")
         if a["code"] == code and a["fiscal_year"] == year and a["fiscal_quarter"] == quarter),
        None,
    )
    # ★ 저장 시점에도 걷어내지만(T61) **이미 저장된 행**이 있으므로 읽는 쪽에서도 막는다.
    #   태그가 새면 esc()가 escape해 발송은 성공하고 화면에만 `&lt;/…&gt;`가 남는다 —
    #   에러가 없어서 알아채지 못한다.
    payload = sanitize_payload((analysis or {}).get("payload") or {})

    yoy = cur.get("revenue_yoy")
    yoy_prev = prev.get("revenue_yoy")
    delta = (float(yoy) - float(yoy_prev)) if yoy is not None and yoy_prev is not None else None
    cap = row.get("market_cap_krw")

    pri_detail = screen.get("pri_detail") or {}
    parts = pri_detail.get("parts") or {}
    measured_parts = " · ".join(
        f"{k.upper()} {v:.0f}" for k, v in parts.items() if v is not None
    )
    if screen.get("pri") is not None:
        pri_parts = measured_parts
    elif measured_parts:
        # 측정된 항목이 있는데도 PRI가 없다 = 분모가 하한에 못 미쳐 판정을 보류했다.
        # 이 사실을 숨기면 "반영도 0"과 구분이 안 된다.
        pri_parts = (
            f"{measured_parts} — 분모 {pri_detail.get('denominator', 0)}점으로 부족해 판정 보류"
            f" (3개월 상대수익률 미수집)"
        )
    else:
        pri_parts = "전 항목 미측정 — 시세 스냅샷 없음"

    return {
        "code": code, "name": row.get("name"), "board": row.get("board"),
        "industry": row.get("industry"),
        "products": row.get("products"), "sector_caveat": row.get("sector_caveat"),
        # ★ 제품별 비중은 아직 수집하지 않는다. `products`는 이름 나열뿐이고
        #   비중은 DART 사업보고서 §II '매출 실적' 표에 있다(별도 수집기 필요).
        #   없는 값을 만들지 않고 None으로 둔다 — 템플릿이 그 사실을 화면에 밝힌다.
        "product_mix": None,
        "market_cap_label": (
            f"{cap / 1e12:,.1f}조" if cap and cap >= 1e12
            else (f"{cap / 1e8:,.0f}억" if cap else "—")
        ),
        "market_cap_rank": cap_rank, "peer_count": peer_count,
        "fiscal_year": year, "fiscal_quarter": quarter,
        # ★ 잠정을 우선 보여주고, 확정이 들어오면 자동으로 확정으로 바뀐다.
        #   `is_estimate`는 그 분기 행의 실제 상태다 — 우리가 고르지 않는다.
        "is_estimate": bool(cur.get("is_estimate")),
        "source": cur.get("source"),
        # 확정치가 잠정과 얼마나 달라졌는가. 나빠졌으면 그 자체가 경고다(T4).
        "confirmed_delta": cur.get("delta_from_preliminary") or {},
        "revenue": cur.get("revenue"), "revenue_yoy": yoy,
        "revenue_yoy_prev": yoy_prev, "yoy_delta_pp": delta,
        "op": cur.get("op"), "op_yoy": cur.get("op_yoy"),
        # 가속은 매출만이 아니라 **영업이익·OPM도** 전분기와 견준다.
        "op_yoy_prev": prev.get("op_yoy"), "opm_prev": prev.get("opm"),
        "np": cur.get("np"), "np_yoy": cur.get("np_yoy"),
        "opm": cur.get("opm"), "opm_yoy_delta": cur.get("opm_yoy_delta"),
        "ttm_opm_delta": cur.get("ttm_opm_delta"),
        # 분기 추이 — 가속을 눈으로 따라가게 한다.
        "quarters": [
            {k: f.get(k) for k in
             ("fiscal_year", "fiscal_quarter", "revenue", "revenue_yoy", "opm",
              "is_estimate")}
            for f in funds
        ],
        # 컨센서스 — 잠정·확정이 나온 종목은 최대한 붙인다.
        "n_estimates": cons.get("n_estimates"),
        "revenue_est": cons.get("revenue_est"), "op_est": cons.get("op_est"),
        "revenue_surprise": rev_surprise, "op_surprise": op_surprise,
        "op_surprise_label": op_surprise_lbl,
        # 등급이 None이면 PRI 판정 불가(시세 결측)라는 뜻이다. 발송 전에 걸러야 한다.
        "grade": screen.get("grade"),
        "score": screen.get("score_flash"),
        "score_a": screen.get("score_a"), "score_b": screen.get("score_b"),
        "score_c": screen.get("score_c"), "score_d": screen.get("score_d"),
        # 항목별 원점수 — A/B/C/D가 각각 무엇을 재서 몇 점인지 메시지에 펼친다.
        "raw": {k[4:]: screen[k] for k in screen if k.startswith("raw_")},
        "raw_sum": sum(
            float(screen[f"score_{a}"]) for a in AXIS_WEIGHTS
            if screen.get(f"score_{a}") is not None
        ),
        # 측정된 축의 배점 합. 미측정 축은 여기서 빠진다 — 0점 처리가 아니다(ADR 2).
        "denominator": sum(
            w for a, w in AXIS_WEIGHTS.items() if screen.get(f"score_{a}") is not None
        ),
        "per": price.get("per"), "pbr": price.get("pbr"),
        "per_ttm": per_ttm, "ttm_np": ttm_np,
        "fwd_per": fwd_per, "fwd_per_basis": fwd_basis,
        # 분기별 PER 궤적 — **현재가 기준**이다(과거 주가를 저장하지 않는다).
        "per_by_quarter": per_by_quarter(funds, cap_for_per),
        "has_consensus": screen.get("has_consensus"),
        "base_effect_warning": screen.get("base_effect_warning"),
        "base_effect_measurable": bool(
            (screen.get("gate_detail") or {}).get("base_effect_measurable", True)
        ),
        "pri": screen.get("pri"), "pri_parts": pri_parts,
        # PRI 항목별 원점수 — 어디가 반영됐고 어디가 안 됐는지 보여준다.
        "pri_parts_detail": parts,
        "thesis": payload.get("one_line_thesis"),
        "sustainability_quarters": (payload.get("acceleration_quality") or {}).get(
            "sustainability_quarters"),
        "triggers": [
            f"{t.get('event')} — {t.get('verifiable_metric')} ({t.get('expected_date')})"
            for t in ((payload.get("triggers") or {}).get("within_3m") or [])
        ],
        "top_risk": next(
            (f"{r.get('risk')} · 발생 {r.get('likelihood')} / 영향 {r.get('impact')}"
             for r in (payload.get("risks") or [])), None),
        "url": f"{optional_env('DASHBOARD_BASE_URL', DASHBOARD_URL_DEFAULT)}"
               f"/stock/{code}",
        # ★ 텔레그램은 폰에서 열린다 — 네이버는 모바일 주소를 준다.
        "naver_url": naver_stock_url(code, mobile=True),
        # ★ 접수번호가 없으면 None이다. 회사명 검색 주소를 대신 넣지 않는다(T58).
        "dart_url": dart_report_url(latest_rcept_no(code)),
    }


def latest_rcept_no(code: str) -> str | None:
    """그 종목의 **가장 최근 공시 접수번호**. 없으면 None.

    ★ 없을 때 회사명으로 DART 검색 주소를 만들면 안 된다 — 200이 뜨고 검색창에
      이름까지 채워지지만 검색이 실행되지 않아 **빈 화면**이 나온다.
      실측(2026-08-17): 파라미터가 있는 응답과 없는 응답의 차이가 input의
      `value=` 24바이트뿐이었다.
    """
    rows = [
        r for r in select_all(
            "earnings_disclosures", "code,rcept_no,disclosed_at")
        if r["code"] == code and r.get("rcept_no")
    ]
    if not rows:
        return None
    rows.sort(key=lambda r: (r.get("disclosed_at") or "", r["rcept_no"]), reverse=True)
    return rows[0]["rcept_no"]


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="P8 텔레그램")
    parser.add_argument("--code", default="005930")
    parser.add_argument("--quarter", default="2026.1")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--kind", default=KIND_FLASH, choices=[KIND_FLASH, KIND_DAILY])
    args = parser.parse_args()

    year, quarter = (int(x) for x in args.quarter.split("."))
    line = "═" * 72
    print(line)
    print(f"P8 텔레그램 — {args.kind} · {args.code} {year}.{quarter}Q")
    print(line)

    print("\n[1] 웹훅 차단 확인 (traps.md T13)")
    client = TelegramClient()
    # ★ 봇 분리 후에도 웹훅류는 영구 차단이다. `getUpdates`는 수신용이라
    #   전용 봇에서만 허용되므로 여기서 차단을 기대하면 안 된다(T44).
    for method in ("setWebhook", "deleteWebhook", "getWebhookInfo"):
        try:
            client.call(method, {})
            print(f"    ✗ {method} — 차단되지 않았다")
            return 1
        except TelegramMethodNotAllowed:
            print(f"    ✓ 차단 {method}")
    print(f"    수신(getUpdates): 전용 봇 {client.is_dedicated_bot} → "
          f"{'허용' if client.is_dedicated_bot else '차단'}")

    ctx = build_flash_context(args.code, year, quarter)
    text = flash_message(ctx) if args.kind == KIND_FLASH else daily_digest(
        {"date": date.today().isoformat(), "rows": [], "counts": {}})

    truncated_text, was_truncated = truncate(text)
    print(f"\n[2] 메시지 렌더 {len(text):,}자 / 상한 {MAX_MESSAGE_CHARS:,} "
          f"{'✗ 잘림' if was_truncated else '✓'}")
    print(f"    발송 등급 기준: {NOTIFY_GRADES} · 이 종목 등급 {ctx.get('grade')!r}")

    print("\n" + "-" * 72)
    print(truncated_text)
    print("-" * 72)

    dup = already_sent(args.code, year, quarter, args.kind)
    print(f"\n[3] 중복 상태: {'이미 발송됨 — 차단된다' if dup else '미발송'}")

    if not args.send:
        print("\n(--send 미지정 — 발송하지 않았다)")
        print(line)
        return 0

    # ★ 등급이 ★/○가 아니면 보내지 않는다. **None도 보내지 않는다** —
    #   None은 "등급이 낮다"가 아니라 "PRI를 판정하지 못했다"는 뜻이라(T35),
    #   보내면 반영도를 모르는 종목을 추천한 셈이 된다.
    grade = ctx.get("grade")
    if grade not in NOTIFY_GRADES:
        reason = "PRI 판정 불가 — 시세 미수집" if grade is None else f"발송 대상 등급이 아니다"
        print(f"\n[4] 발송 안 함 — 등급 {grade!r} ({reason})")
        print(f"    발송 대상은 {NOTIFY_GRADES} 뿐이다. △·는 대시보드에만 남는다.")
        print(line)
        return 0

    print("\n[4] 발송...")
    ok = send_once(
        client,
        code=args.code, fiscal_year=year, fiscal_quarter=quarter,
        kind=args.kind, text=truncated_text,
        payload={"grade": ctx.get("grade"), "score": ctx.get("score")},
    )
    s = client.stats
    print(f"    결과: {'✓ 발송' if ok else '✗ 발송 안 됨'}")
    print(f"    sent={s.sent} · 중복차단={s.blocked_duplicate} · 실패={s.failed} "
          f"· 429백오프={s.rate_limit_hits} · 잘림={s.truncated}")
    if s.errors:
        print(f"    오류: {json.dumps(s.errors, ensure_ascii=False)}")
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
