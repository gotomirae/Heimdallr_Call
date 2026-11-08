# PRD Ref: §8 (외부 연동) · JARVIS NEXUS NXD-7 (2026-11-08)
"""Heimdallr 분기 분석 → 노션 「2_5. 소스 DB」(원장 #1).

    python -m src.notify.notion_export              # 최근 3일 분석, 노션에 쓴다
    python -m src.notify.notion_export --days 30    # 처음 한 번 밀린 것까지
    python -m src.notify.notion_export --dry-run    # 쓰지 않고 무엇을 쓸지 출력

왜 필요한가
  Heimdallr가 발굴한 '실적 가속 + 미반영' 종목과 LLM 해석은 Supabase·텔레그램·대시보드에만
  남아, 노션을 읽는 아티팩트(국내 기업 분석·관심종목 Thesis)와 옵시디언이 볼 수 없었다.

무엇을 쓰는가
  `analyses`(LLM 해석이 끝난 종목·분기) 중 **발송 등급(NOTIFY_GRADES, ★·○) 이거나
  노션 관심종목**인 것만 1행씩. 텔레그램으로 보내는 범위와 같다 — 그보다 넓히면
  2_5가 매 분기 수백 행으로 덮여 다른 출처가 묻힌다.
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

#: JARVIS 노션 L1 코드 → 노션 2_5 '산업' 선택지 이름. 코드 정본은 JARVIS taxonomy.
#: '1l'(자동차)·'ETC'는 2_5에 맞는 칸이 없어 비워 둔다(추측해서 넣지 않는다).
L1_TO_NOTION: dict[str, str] = {
    "1a": "AI", "1b": "반도체", "1c": "전력인프라", "1d": "바이오",
    "1e": "화장품_미용기기", "1f": "엔터", "1g": "우주항공방산", "1h": "조선",
    "1i": "2차 전지", "2a": "Robot", "2b": "IT", "2c": "헬스케어",
    "2d": "소비재", "2e": "여행", "2f": "금융", "2g": "건설", "3c": "양자컴퓨터",
}

GRADE_SIGNAL = {"★": "5", "○": "4", "△": "3", "·": "2"}


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
        "영향": ns.p_select("긍정" if positive else "중립", allowed.get("영향")),
        "신호강도": ns.p_select(GRADE_SIGNAL.get(grade or "", "2"), allowed.get("신호강도")),
        "논지 영향": ns.p_select(("강화" if positive else "중립") if is_watch else None,
                               allowed.get("논지 영향")),
    })


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
    watch = allowed.get("기업") or set()

    failures = picked = 0
    for r in rows:
        code, fy, fq = r["code"], r["fiscal_year"], r["fiscal_quarter"]
        try:
            uni = _one(db, "krx_universe", "name,sector", code=code)
            name = uni.get("name") or code
            screen = _one(db, "screen_results", "grade,score_final,score_flash",
                          code=code, fiscal_year=fy, fiscal_quarter=fq)
            grade = screen.get("grade")
            if grade not in NOTIFY_GRADES and name not in watch:
                continue
            picked += 1
            fund = (_one(db, "quarterly_fundamentals",
                         "revenue_yoy,op_yoy,op_status_label,opm,opm_yoy_delta",
                         code=code, fiscal_year=fy, fiscal_quarter=fq, fs_div="CFS")
                    or _one(db, "quarterly_fundamentals",
                            "revenue_yoy,op_yoy,op_status_label,opm,opm_yoy_delta",
                            code=code, fiscal_year=fy, fiscal_quarter=fq, fs_div="OFS"))
            disc = (db.table("earnings_disclosures").select("rcept_no,disclosed_at")
                    .eq("code", code).eq("fiscal_year", fy).eq("fiscal_quarter", fq)
                    .order("disclosed_at", desc=True).limit(1).execute().data or [{}])[0]
            dashboard = f"{base}/stock/{code}"
            link = dart_report_url(disc.get("rcept_no")) or f"{dashboard}?q={fy}.{fq}"
            status = sink.create(
                ns.SOURCE_DB,
                build_row(code=code, name=name, fy=fy, fq=fq, payload=r.get("payload") or {},
                          grade=grade, score=screen.get("score_final") or screen.get("score_flash"),
                          fund=fund, sector=uni.get("sector"),
                          day=disc.get("disclosed_at") or r.get("created_at"),
                          link=link, dashboard=dashboard, allowed=allowed),
                dedup=ns.url_equals("원문 링크", link))
            logger.info("2_5 %s %s %d.%dQ (%s): %s", code, name, fy, fq, grade, status)
        except Exception as exc:  # noqa: BLE001 — 한 종목 실패가 나머지를 막지 않게
            failures += 1
            logger.error("노션 내보내기 실패 %s %s.%s: %s: %s", code, fy, fq, type(exc).__name__, exc)

    logger.info("노션 내보내기 끝: 분석 %d · 대상 %d · 새 행 %d · 이미 있음 %d · 실패 %d",
                len(rows), picked, sink.created, sink.skipped, failures)
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
