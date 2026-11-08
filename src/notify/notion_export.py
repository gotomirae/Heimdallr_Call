# PRD Ref: §8 (외부 연동) · JARVIS NEXUS NXD-7 (2026-11-08)
"""Heimdallr 분기 분석 → 노션 「2_5. 소스 DB」(원장 #1).

    python -m src.notify.notion_export              # 최근 3일 분석, 노션에 쓴다
    python -m src.notify.notion_export --days 30    # 처음 한 번 밀린 것까지
    python -m src.notify.notion_export --dry-run    # 쓰지 않고 무엇을 쓸지 출력

왜 필요한가
  Heimdallr가 발굴한 '실적 가속 + 미반영' 종목과 LLM 해석은 Supabase·텔레그램·대시보드에만
  남아, 노션을 읽는 아티팩트(국내 기업 분석·관심종목 Thesis)와 옵시디언이 볼 수 없었다.

무엇을 쓰는가 (2026-11-08 사용자 지시 "모든 범위를 포함해서 기록")
  `analyses`(LLM 해석이 끝난 종목·분기) **전부**를 1행씩 — 등급(★○△·✕)·관심종목 여부로
  거르지 않는다. 대신 등급이 '신호강도'(★5 ○4 △3 ·2 ✕1)와 '영향'에 그대로 들어가므로
  노션에서 등급으로 걸러 볼 수 있다.
  페이지 **본문**에는 분석 전체를 싣는다: 등급·점수·축별 점수·주가반영도(PRI)·게이트 근거,
  분기 재무(매출·영업이익·순이익·EPS·OPM·TTM·현금흐름, 억원), 그리고 LLM 해석 payload
  전 필드(한 줄 논지·왜 지금·실적 변화·성장 엔진·가속의 질·트리거·주가 위치·시나리오·
  리스크·틀릴 수 있는 이유·글로벌 밸류체인·증권사 리포트·다음 확인 데이터 …). 스키마에
  나중에 붙는 필드도 '기타'로 빠짐없이 남는다.
  재분석으로 내용이 바뀌면 본문을 다시 쓴다(본문 첫 줄의 내보내기 버전으로 판정).
  키(중복 확인) = 원문 링크 = 그 분기 DART 공시 원문(없으면 대시보드 종목 화면 + 분기).

지키는 것
  - 선택지(산업·기업 등)는 노션에 이미 있는 이름만 쓴다(notion_sink 원칙 3).
  - 성장률은 저장된 값만 쓰고, 부호 전환 구간은 status_label 글자로 쓴다(ADR · T12).
  - 실패는 종목 단위로 격리하고, 하나라도 실패하면 종료 코드 1.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from src.config.constants import DASHBOARD_URL_DEFAULT, NOTIFY_GRADES
from src.db.supabase_client import get_client
from src.notify import notion_sink as ns
from src.notify.links import dart_report_url
from src.universe.industry_l1 import resolve_l1
from src.utils.env import optional_env

logger = logging.getLogger("notion_export")

SOURCE_NAME = "Heimdallr Call"
SCREEN_COLUMNS = ("grade,score_final,score_flash,score_delta,score_a,score_b,score_c,score_d,"
                  "pctile_in_quarter,pri,pri_detail,gate_detail,has_consensus,turnaround,"
                  "base_effect_warning")

#: JARVIS 노션 L1 코드 → 노션 2_5 '산업' 선택지 이름. 코드 정본은 JARVIS taxonomy.
#: '1l'(자동차)·'ETC'는 2_5에 맞는 칸이 없어 비워 둔다(추측해서 넣지 않는다).
L1_TO_NOTION: dict[str, str] = {
    "1a": "AI", "1b": "반도체", "1c": "전력인프라", "1d": "바이오",
    "1e": "화장품_미용기기", "1f": "엔터", "1g": "우주항공방산", "1h": "조선",
    "1i": "2차 전지", "2a": "Robot", "2b": "IT", "2c": "헬스케어",
    "2d": "소비재", "2e": "여행", "2f": "금융", "2g": "건설", "3c": "양자컴퓨터",
}

GRADE_SIGNAL = {"★": "5", "○": "4", "△": "3", "·": "2", "✕": "1"}
GRADE_IMPACT = {"★": "긍정", "○": "긍정", "✕": "부정"}

#: payload(§7.2 스키마) 키 → 한국어 라벨. 없는 키는 키 이름 그대로 나온다.
LABELS: dict[str, str] = {
    "one_line_thesis": "한 줄 논지", "why_now": "왜 지금인가", "earnings_change": "실적 변화",
    "cause": "원인", "outlook": "전망", "growth_engine": "성장 엔진",
    "acceleration_quality": "가속의 질", "is_genuine": "진짜 가속인가",
    "structural_or_temporary": "구조적/일시적", "sustainability_quarters": "지속 예상 분기",
    "base_effect_assessment": "기저효과 판단", "triggers": "주가 트리거", "within_3m": "3개월 내",
    "within_6m": "6개월 내", "trigger_list": "트리거", "price_position": "주가 위치",
    "verdict": "판정", "reason": "근거", "price_history": "주가 흐름", "scenarios": "시나리오",
    "scenario": "시나리오", "bull": "Bull", "base": "Base", "bear": "Bear",
    "probability": "확률", "condition": "조건", "implication": "의미", "risks": "리스크",
    "risk": "리스크", "likelihood": "가능성", "impact": "영향", "watch_metric": "확인 지표",
    "how_i_could_be_wrong": "틀릴 수 있는 이유", "next_data_to_watch": "다음 확인 데이터",
    "global_chain": "글로벌 밸류체인", "value_chain": "밸류체인", "upstream": "전방",
    "customers": "고객사", "company": "기업", "company_role": "역할", "drivers": "동인",
    "recent_global_events": "최근 글로벌 이벤트", "event": "이벤트", "date": "날짜",
    "effect": "효과", "channel": "경로", "broker_reports": "증권사 리포트",
    "publisher": "증권사", "published_at": "발간일", "title": "제목", "key_point": "요점",
    "narrative_verification": "내러티브 검증", "claim": "주장", "evidence": "근거",
    "status": "상태", "priced_in": "이미 반영", "not_priced_in": "아직 미반영",
    "expected_date": "예상 시점", "verifiable_metric": "확인 수치", "confidence": "확신도",
    "kind": "종류", "source_title": "출처", "source_date": "출처 날짜", "url": "링크",
    "search_limit": "검색 한계", "items": "항목", "value": "값",
}

#: 재무 칸 → (라벨, 종류). 'won' = 원 → 억원, 'pct' = %, 'pp' = %p, 'num' = 그대로
FUND_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("revenue", "매출", "won"), ("revenue_yoy", "매출 YoY", "pct"), ("revenue_qoq", "매출 QoQ(참고)", "pct"),
    ("op", "영업이익", "won"), ("op_yoy", "영업이익 YoY", "pct"), ("op_status_label", "영업이익 상태", "num"),
    ("np", "순이익", "won"), ("np_yoy", "순이익 YoY", "pct"), ("eps", "EPS(원)", "num"),
    ("eps_yoy", "EPS YoY", "pct"), ("opm", "영업이익률", "pct0"), ("opm_yoy_delta", "OPM YoY", "pp"),
    ("gpm", "매출총이익률", "pct0"), ("npm", "순이익률", "pct0"),
    ("ttm_revenue", "TTM 매출", "won"), ("ttm_op", "TTM 영업이익", "won"),
    ("ttm_opm", "TTM OPM", "pct0"), ("ttm_opm_delta", "TTM OPM 변화", "pp"),
    ("rev_2y_stack", "매출 2년 스택", "pct"), ("cfo", "영업현금흐름", "won"),
    ("ttm_cfo", "TTM 영업현금흐름", "won"), ("capex", "CAPEX", "won"), ("fcf", "FCF", "won"),
    ("receivables", "매출채권", "won"), ("inventory", "재고", "won"),
    ("shares_yoy", "주식수 YoY", "pct"), ("fs_div", "재무제표", "num"), ("source", "출처", "num"),
)


def notion_industries(sector: str | None) -> list[str]:
    codes, _ = resolve_l1(sector)
    return [L1_TO_NOTION[c] for c in codes if c in L1_TO_NOTION]


def growth_text(label: str, value: Any, status: str | None = None) -> str | None:
    if status:                      # 흑전·적전·적자축소·적자확대 — % 계산 금지 구간
        return f"{label} {status}"
    try:
        return f"{label} {float(value):+.1f}%"
    except (TypeError, ValueError):
        return None


def key_numbers(grade: str | None, score: Any, fund: dict) -> str:
    parts = [f"등급 {grade}" if grade else None]
    try:
        parts.append(f"점수 {float(score):.0f}")
    except (TypeError, ValueError):
        pass
    parts.append(growth_text("매출 YoY", fund.get("revenue_yoy")))
    parts.append(growth_text("영업이익 YoY", fund.get("op_yoy"), fund.get("op_status_label")))
    if fund.get("opm") is not None:
        delta = fund.get("opm_yoy_delta")
        tail = f"({float(delta):+.1f}%p)" if delta is not None else ""
        parts.append(f"OPM {float(fund['opm']):.1f}%{tail}")
    return " · ".join(p for p in parts if p)


def build_row(*, code: str, name: str, fy: int, fq: int, payload: dict, grade: str | None,
              score: Any, fund: dict, sector: str | None, day: str | None, link: str,
              dashboard: str, allowed: dict[str, set[str] | None]) -> dict:
    thesis = (payload.get("one_line_thesis") or "").strip()
    cause = ((payload.get("earnings_change") or {}).get("cause") or "").strip()
    price = payload.get("price_position") or {}
    body = [thesis, (payload.get("why_now") or "").strip(),
            f"실적 원인: {cause}" if cause else "",
            f"주가 위치: {price.get('verdict')} — {(price.get('reason') or '')[:200]}"
            if price.get("verdict") else "",
            f"대시보드: {dashboard}"]
    allowed_companies = allowed.get("기업")
    is_watch = bool(allowed_companies and name in allowed_companies)
    positive = grade in NOTIFY_GRADES
    impact = GRADE_IMPACT.get(grade or "", "중립")
    return ns.compact({
        "제목": ns.p_title(f"[Heimdallr] {name} {fy}.{fq}Q — {thesis[:60] or '분기 실적 분석'}"),
        "날짜": ns.p_date(day),
        "출처유형": ns.p_select("IR·실적", allowed.get("출처유형")),
        "등급": ns.p_select("T1 1차 출처", allowed.get("등급")),
        "검증 상태": ns.p_select("미검증", allowed.get("검증 상태")),
        "수집 경로": ns.p_select("예약 작업", allowed.get("수집 경로")),
        "PDF 본문": ns.p_select("미확인", allowed.get("PDF 본문")),
        "출처": ns.p_text(f"{SOURCE_NAME} (DART 분기실적·딥분석)"),
        "원문 링크": ns.p_url(link),
        "내용": ns.p_text("\n".join(b for b in body if b)),
        "핵심 수치": ns.p_text(key_numbers(grade, score, fund)),
        "산업": ns.p_multi(notion_industries(sector), allowed.get("산업")),
        "기업": ns.p_multi([name] if is_watch else [], allowed_companies),
        "영향": ns.p_select(impact, allowed.get("영향")),
        "신호강도": ns.p_select(GRADE_SIGNAL.get(grade or "", "2"), allowed.get("신호강도")),
        "논지 영향": ns.p_select(({"긍정": "강화", "부정": "약화"}.get(impact, "중립")) if is_watch else None,
                               allowed.get("논지 영향")),
    })


def _fund_value(v: Any, kind: str) -> str | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if kind == "won":
        return f"{f / 1e8:,.0f}억원"
    if kind == "pct":
        return f"{f:+.1f}%"
    if kind == "pct0":
        return f"{f:.1f}%"
    if kind == "pp":
        return f"{f:+.1f}%p"
    return f"{f:,.4g}"


def build_page_body(*, code: str, name: str, fy: int, fq: int, payload: dict, screen: dict,
                    fund: dict, sector: str | None, link: str, dashboard: str) -> list[dict]:
    """분석 1건 → 노션 블록. 순수 함수(네트워크 없음)."""
    H, P, B, R = ns.b_heading, ns.b_para, ns.b_bullet, ns.render_value
    out = [P(f"{name} ({code}) · {fy}.{fq}Q · 업종 {sector or '?'} · 공시 {link} · 대시보드 {dashboard}")]

    sc = [f"등급 {screen['grade']}" if screen.get("grade") else None]
    for k, lab in (("score_final", "확정 점수"), ("score_flash", "잠정 점수"), ("score_delta", "점수 변화"),
                   ("score_a", "A 성장"), ("score_b", "B 수익성"), ("score_c", "C 서프라이즈"),
                   ("score_d", "D 질"), ("pctile_in_quarter", "분기 내 백분위"), ("pri", "주가반영도 PRI")):
        val = _fund_value(screen.get(k), "num")
        if val is not None:
            sc.append(f"{lab} {val}")
    for k, lab in (("has_consensus", "컨센서스 있음"), ("turnaround", "흑자전환"),
                   ("base_effect_warning", "기저효과 경고")):
        if screen.get(k) is not None:
            sc.append(f"{lab} {'예' if screen[k] else '아니오'}")
    sc = [x for x in sc if x]
    if sc:
        out += [H("스크리너 판정"), *[B(x) for x in sc]]
    if screen.get("gate_detail"):
        out += [H("게이트 근거", 3), *R(screen["gate_detail"], LABELS)]
    if screen.get("pri_detail"):
        out += [H("주가반영도 근거", 3), *R(screen["pri_detail"], LABELS)]

    lines = [f"{lab}: {txt}" for k, lab, kind in FUND_FIELDS
             if (txt := _fund_value(fund.get(k), kind)) is not None]
    if lines:
        out += [H("분기 재무"), *[B(x) for x in lines]]

    if payload.get("one_line_thesis"):
        out += [H("한 줄 논지"), P(str(payload["one_line_thesis"]))]
    for k, v in payload.items():
        if k == "one_line_thesis" or ns._is_empty(v):
            continue
        if isinstance(v, (dict, list)):
            out += R({k: v}, LABELS, level=2)
        else:   # 최상위 글(왜 지금인가 등)은 제 소제목 아래에 — 앞 절에 붙어 읽히지 않게
            out += [H(LABELS.get(k, k)), P(ns._scalar(v))]
    return out


def page_version(*parts: Any) -> str:
    return ns.content_hash(*parts)


def _one(db, table: str, columns: str, **eq) -> dict:
    query = db.table(table).select(columns)
    for k, v in eq.items():
        query = query.eq(k, v)
    return (query.limit(1).execute().data or [{}])[0]


def run(days: int, dry_run: bool) -> int:
    token = optional_env("NOTION_TOKEN")
    if not token and not dry_run:
        logger.error("NOTION_TOKEN이 없다 — GitHub Secrets에 노션 통합 토큰을 등록할 것")
        return 1
    sink = ns.NotionSink(token, dry_run=dry_run)
    base = (optional_env("DASHBOARD_BASE_URL", DASHBOARD_URL_DEFAULT) or DASHBOARD_URL_DEFAULT).rstrip("/")
    db = get_client()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    # 분석 행은 분기당 수백 건 안쪽이라 1,000행 절단(T7)에 닿지 않는다 — 닿으면 경고한다.
    rows = (db.table("analyses").select("code,fiscal_year,fiscal_quarter,payload,created_at")
            .gte("created_at", since).order("created_at", desc=True).limit(1000).execute().data or [])
    if len(rows) >= 1000:
        logger.warning("분석 행이 1,000건에 닿았다 — --days를 줄여 나눠 돌릴 것(T7)")
    allowed = {p: sink.options(ns.SOURCE_DB, p) for p in
               ("출처유형", "등급", "검증 상태", "수집 경로", "PDF 본문", "산업", "기업",
                "영향", "신호강도", "논지 영향")}

    failures = picked = 0
    for r in rows:
        code, fy, fq = r["code"], r["fiscal_year"], r["fiscal_quarter"]
        try:
            uni = _one(db, "krx_universe", "name,sector", code=code)
            name = uni.get("name") or code
            screen = _one(db, "screen_results", SCREEN_COLUMNS,
                          code=code, fiscal_year=fy, fiscal_quarter=fq)
            grade = screen.get("grade")
            picked += 1   # 2026-11-08: 등급·관심종목으로 거르지 않는다(사용자 지시 "모든 범위")
            fund = (_one(db, "quarterly_fundamentals", "*",
                         code=code, fiscal_year=fy, fiscal_quarter=fq, fs_div="CFS")
                    or _one(db, "quarterly_fundamentals", "*",
                            code=code, fiscal_year=fy, fiscal_quarter=fq, fs_div="OFS"))
            disc = (db.table("earnings_disclosures").select("rcept_no,disclosed_at")
                    .eq("code", code).eq("fiscal_year", fy).eq("fiscal_quarter", fq)
                    .order("disclosed_at", desc=True).limit(1).execute().data or [{}])[0]
            dashboard = f"{base}/stock/{code}"
            link = dart_report_url(disc.get("rcept_no")) or f"{dashboard}?q={fy}.{fq}"
            payload = r.get("payload") or {}
            children = build_page_body(code=code, name=name, fy=fy, fq=fq, payload=payload,
                                       screen=screen, fund=fund, sector=uni.get("sector"),
                                       link=link, dashboard=dashboard)
            status = sink.upsert(
                ns.SOURCE_DB,
                build_row(code=code, name=name, fy=fy, fq=fq, payload=payload,
                          grade=grade, score=screen.get("score_final") or screen.get("score_flash"),
                          fund=fund, sector=uni.get("sector"),
                          day=disc.get("disclosed_at") or r.get("created_at"),
                          link=link, dashboard=dashboard, allowed=allowed),
                children,
                dedup=ns.url_equals("원문 링크", link),
                version=page_version(payload, screen, {k: v for k, v in fund.items()
                                                       if k not in ("updated_at",)}))
            logger.info("2_5 %s %s %d.%dQ (%s): %s", code, name, fy, fq, grade, status)
        except Exception as exc:  # noqa: BLE001 — 한 종목 실패가 나머지를 막지 않게
            failures += 1
            logger.error("노션 내보내기 실패 %s %s.%s: %s: %s", code, fy, fq, type(exc).__name__, exc)

    logger.info("노션 내보내기 끝: 분석 %d · 대상 %d · 새 행 %d · 본문 갱신 %d · 변화 없음 %d · 실패 %d",
                len(rows), picked, sink.created, sink.updated, sink.skipped, failures)
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Heimdallr → 노션 2_5 내보내기")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(run(args.days, args.dry_run))


if __name__ == "__main__":
    main()
