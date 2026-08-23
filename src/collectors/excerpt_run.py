# PRD Ref: §5, §7.1 · ADR 4
"""정기보고서 발췌 수집 — LLM 입력 재료를 미리 받아 둔다.

    python -m src.collectors.excerpt_run --limit 20 --save
    python -m src.collectors.excerpt_run --codes 001820,005420 --save

★★ **왜 미리 받나:** 원문 XML은 3.5MB이고 1건에 ~30초 걸린다. 분석할 때마다 받으면
   269종목 배치에 두 시간이 더 붙어 밤 창(3시간)을 통째로 먹는다.
   발췌만 뽑아 저장해 두면 분석은 DB에서 읽어 쓴다.

★ **이미 받은 건은 건너뛴다.** 정기보고서는 한 번 나오면 바뀌지 않는다
   (정정공시는 접수번호가 다르므로 별도 행이 된다).

★ 대상은 **게이트를 통과한 종목의 정기보고서**다. 전 종목을 받으면 1,300건 × 30초 =
   11시간이고, 분석하지 않는 종목의 발췌는 쓰이지 않는다.
"""

from __future__ import annotations

import argparse
import time

from src.collectors.dart_excerpt import ExcerptError, build_excerpt, fetch_report_xml
from src.db.supabase_client import get_client, select_all
from src.utils.console import enable_utf8_stdout

#: 정기보고서만 받는다. 잠정실적 공정공시는 `document.xml`이 안 되고(status 014),
#: 애초에 숫자뿐이라 발췌할 서술이 없다.
PERIODIC_KEYWORDS = ("사업보고서", "반기보고서", "분기보고서")

#: 연속 호출 간격(초). DART는 분당 호출 제한이 있고 원문은 무거우므로 여유를 둔다.
SLEEP_SECONDS = 1.0


def is_periodic(report_nm: str | None) -> bool:
    """정기보고서인가. **정정공시도 포함한다** — `[기재정정]반기보고서`도 원문이 있다."""
    return bool(report_nm) and any(k in report_nm for k in PERIODIC_KEYWORDS)


def targets(limit: int, codes: list[str] | None) -> list[dict]:
    """받을 공시 목록. 게이트 통과 종목 · 최신 정기보고서 우선."""
    disclosures = [
        d for d in select_all(
            "earnings_disclosures",
            "rcept_no,code,report_nm,fiscal_year,fiscal_quarter,disclosed_at",
        )
        if is_periodic(d.get("report_nm"))
    ]
    have = {
        r["rcept_no"] for r in select_all("disclosure_excerpts", "rcept_no")
    }
    disclosures = [d for d in disclosures if d["rcept_no"] not in have]

    if codes:
        wanted = set(codes)
        disclosures = [d for d in disclosures if d["code"] in wanted]
    else:
        # 게이트 통과 종목만. 분석하지 않는 종목의 발췌는 쓰이지 않는다.
        passed = {
            s["code"] for s in select_all("screen_results", "code,gate_passed")
            if s.get("gate_passed") is True
        }
        disclosures = [d for d in disclosures if d["code"] in passed]

    # 종목당 **가장 최근 것 하나**만. 같은 종목의 옛 보고서를 받아 봐야 쓰이지 않는다.
    newest: dict[str, dict] = {}
    for d in disclosures:
        prev = newest.get(d["code"])
        if prev is None or (d.get("disclosed_at") or "") > (prev.get("disclosed_at") or ""):
            newest[d["code"]] = d
    ordered = sorted(
        newest.values(), key=lambda d: d.get("disclosed_at") or "", reverse=True
    )
    return ordered[:limit]


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="정기보고서 발췌 수집")
    parser.add_argument("--limit", type=int, default=20, help="최대 건수")
    parser.add_argument("--codes", help="쉼표로 구분한 종목코드(지정하면 그것만)")
    parser.add_argument("--save", action="store_true", help="DB에 저장")
    args = parser.parse_args()

    codes = [c.strip() for c in args.codes.split(",")] if args.codes else None
    rows = targets(args.limit, codes)
    print(f"발췌 대상 {len(rows)}건 (이미 받은 건은 제외했다)")
    if not rows:
        return 0

    db = get_client() if args.save else None
    ok = failed = 0
    for i, d in enumerate(rows, 1):
        label = f"{d['code']} {d.get('report_nm')}"
        try:
            xml = fetch_report_xml(d["rcept_no"])
            ex = build_excerpt(d["rcept_no"], xml)
        except ExcerptError as exc:
            print(f"  ✗ {label} — {exc}")
            failed += 1
            continue

        chars = sum(len(v) for v in ex.sections.values())
        if not ex.sections:
            # 절을 하나도 못 찾았다. **저장하지 않는다** — 빈 발췌를 넣으면
            # 다음 실행이 '이미 받았다'고 건너뛰어 영영 비어 있게 된다.
            print(f"  ⚠ {label} — 절을 찾지 못했다(원문 {ex.full_chars:,}자) · 저장 안 함")
            failed += 1
            continue

        print(f"  ✓ {label} — {len(ex.sections)}개 절 · {chars:,}자 "
              f"(원문 {ex.full_chars:,}자) · {', '.join(ex.sections)}")
        if db:
            db.table("disclosure_excerpts").upsert({
                "rcept_no": d["rcept_no"],
                "code": d["code"],
                "fiscal_year": d.get("fiscal_year"),
                "fiscal_quarter": d.get("fiscal_quarter"),
                "sections": ex.sections,
                "excerpt_chars": chars,
                "full_chars": ex.full_chars,
            }, on_conflict="rcept_no").execute()
        ok += 1
        if i < len(rows):
            time.sleep(SLEEP_SECONDS)

    print(f"\n✓ 수집 {ok}건 · 실패 {failed}건"
          + ("" if args.save else "  (--save 미지정 — 저장하지 않았다)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
