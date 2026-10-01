# PRD Ref: §5, §7.1 · ADR 4
"""정기보고서 발췌 수집 — LLM 입력 재료를 미리 받아 둔다.

    python -m src.collectors.excerpt_run --limit 20 --save
    python -m src.collectors.excerpt_run --codes 001820,005420 --save

★★ **왜 미리 받나:** 원문 XML은 3.5MB이고 1건에 ~30초 걸린다. 분석할 때마다 받으면
   269종목 배치에 두 시간이 더 붙어 밤 창(3시간)을 통째로 먹는다.
   발췌만 뽑아 저장해 두면 분석은 DB에서 읽어 쓴다.

★ **이미 받은 건은 건너뛴다.** 정기보고서는 한 번 나오면 바뀌지 않는다
   (정정공시는 접수번호가 다르므로 별도 행이 된다).

★ 기본 대상은 게이트 통과 종목이다. `--all-universe`는 대시보드 수주잔고·신규수주를
   전 종목에 최대한 채우는 별도 예약 작업에서만 사용한다. 시간 예산으로 끊고 완료한
   접수번호는 건너뛰므로 여러 날에 걸쳐 누적된다.
"""

from __future__ import annotations

import argparse
import time

from src.config.constants import ORDER_HISTORY_QUARTERS
from src.collectors.dart_excerpt import (
    ORDER_METRIC_MARKER,
    ExcerptError,
    build_excerpt,
    fetch_report_xml,
)
from src.db.supabase_client import get_client, select_all
from src.utils.console import enable_utf8_stdout

#: 정기보고서만 받는다. 잠정실적 공정공시는 `document.xml`이 안 되고(status 014),
#: 애초에 숫자뿐이라 발췌할 서술이 없다.
PERIODIC_KEYWORDS = ("사업보고서", "반기보고서", "분기보고서")

#: 연속 호출 간격(초). DART는 분당 호출 제한이 있고 원문은 무거우므로 여유를 둔다.
SLEEP_SECONDS = 1.0


def is_periodic(report_nm: str | None) -> bool:
    """정기보고서 본문인가. 기재정정은 포함하고 첨부만 바꾼 정정은 제외한다."""
    if not report_nm or "[첨부정정]" in "".join(report_nm.split()):
        return False
    # 첨부추가는 최초 본문의 접수번호에 붙기도 하므로 배제하지 않는다.
    return any(k in report_nm for k in PERIODIC_KEYWORDS)


def targets(
    limit: int,
    codes: list[str] | None,
    *,
    refresh_orders: bool = False,
    all_universe: bool = False,
    history_quarters: int = 1,
) -> list[dict]:
    """받을 공시 목록. 깊이별로 돌며 종목당 최근 N개 정기보고서를 채운다."""
    disclosures = [
        d for d in select_all(
            "earnings_disclosures",
            "rcept_no,code,report_nm,fiscal_year,fiscal_quarter,disclosed_at",
        )
        if is_periodic(d.get("report_nm"))
    ]
    # 완료 표식은 접수번호별로 본다. 같은 분기의 정정공시는 새 접수번호라 다시 받는다.
    have = {
        r["rcept_no"]
        for r in select_all(
            "disclosure_excerpts", "rcept_no,sections"
        )
        if isinstance(r.get("sections"), dict)
        and r["sections"].get("공시 수주지표 확인") == ORDER_METRIC_MARKER
    }

    if codes:
        wanted = set(codes)
        disclosures = [d for d in disclosures if d["code"] in wanted]
    elif not all_universe:
        # 게이트 통과 종목만. 분석하지 않는 종목의 발췌는 쓰이지 않는다.
        passed = {
            s["code"] for s in select_all("screen_results", "code,gate_passed")
            if s.get("gate_passed") is True
        }
        disclosures = [d for d in disclosures if d["code"] in passed]

    # 종목·분기별 최신 정정본만 남긴다. 동일 분기의 구 접수본을 다시 받아 그래프에서
    # 두 점으로 보이는 것을 막되, 정정 접수번호 자체는 놓치지 않는다.
    newest_period: dict[tuple[str, int, int], dict] = {}
    for d in disclosures:
        key = (d["code"], d.get("fiscal_year") or 0, d.get("fiscal_quarter") or 0)
        prev = newest_period.get(key)
        if prev is None or d["rcept_no"] > prev["rcept_no"]:
            newest_period[key] = d

    by_code: dict[str, list[dict]] = {}
    for d in newest_period.values():
        by_code.setdefault(d["code"], []).append(d)
    candidates: list[tuple[int, dict]] = []
    for filings in by_code.values():
        ordered_filings = sorted(
            filings,
            key=lambda row: (row.get("fiscal_year") or 0, row.get("fiscal_quarter") or 0, row["rcept_no"]),
            reverse=True,
        )[:max(1, history_quarters)]
        candidates.extend((depth, row) for depth, row in enumerate(ordered_filings))

    # ★★ **분석과 같은 순서로 받는다**(매력도 순).
    #   실측(2026-08-23): 공시일 순으로 받았더니 매력도 상위 80종목 중 **40종목만**
    #   발췌를 갖고 있었다 — 정작 먼저 분석되는 종목이 숫자표만 보게 된다.
    #   수집이 중간에 끊겨도(시간 예산) **중요한 종목이 먼저** 채워져야 한다.
    rank = attractiveness_rank()
    ordered = sorted(
        ((depth, d) for depth, d in candidates if refresh_orders or d["rcept_no"] not in have),
        # 전 종목의 최신 미수집분을 먼저 채운 뒤 직전 분기로 내려간다. 한 종목 10개를
        # 몰아서 받으면 상위 몇 종목만 그래프가 생기는 편향이 발생한다.
        key=lambda item: (
            item[0],
            -(rank.get(item[1]["code"], float("-inf"))),
            str(item[1].get("disclosed_at") or ""),
        ),
    )
    return [row for _depth, row in ordered[:limit]]


def attractiveness_rank() -> dict[str, float]:
    """종목 → 매력도. **분석 배치와 같은 기준**을 쓴다(`analysis.batch`).

    ★ 여기서 따로 계산하면 두 순서가 조용히 갈라져, 고친 뒤에도 같은 문제가 남는다.
    """
    from src.analysis.batch import attractiveness, targets as analysis_targets

    out: dict[str, float] = {}
    for row in analysis_targets(2000, min_score=0):
        value = attractiveness(row)
        if value is not None:
            out[row["code"]] = value
    return out


def main() -> int:
    enable_utf8_stdout()
    parser = argparse.ArgumentParser(description="정기보고서 발췌 수집")
    parser.add_argument("--limit", type=int, default=20, help="최대 건수")
    parser.add_argument("--codes", help="쉼표로 구분한 종목코드(지정하면 그것만)")
    parser.add_argument("--save", action="store_true", help="DB에 저장")
    parser.add_argument("--refresh-orders", action="store_true", help="--codes의 최신 공시 원문을 다시 읽어 수주 표를 갱신")
    parser.add_argument(
        "--all-universe",
        action="store_true",
        help="전 유니버스 최신 정기보고서를 점진 수집(수주 대시보드 전용 예약 작업)",
    )
    parser.add_argument("--history-quarters", type=int,
                        help="종목당 최근 정기보고서 수(기본: 전 종목 수주 작업은 설정값, 그 외 1)")
    # ★ 건수가 아니라 **시간**으로 끊는다. 원문 크기가 종목마다 3~6MB로 달라
    #   건수만으로는 워크플로가 얼마나 걸릴지 예측할 수 없다.
    parser.add_argument("--max-seconds", type=float, default=0,
                        help="이 시간을 넘기면 남은 건은 다음 실행으로 넘긴다(0=무제한)")
    args = parser.parse_args()

    codes = [c.strip() for c in args.codes.split(",")] if args.codes else None
    if args.refresh_orders and not codes:
        parser.error("--refresh-orders에는 --codes로 갱신할 종목을 지정해야 한다")
    rows = targets(
        args.limit,
        codes,
        refresh_orders=args.refresh_orders,
        all_universe=args.all_universe,
        history_quarters=args.history_quarters or (ORDER_HISTORY_QUARTERS if args.all_universe else 1),
    )
    print(f"발췌 대상 {len(rows)}건 (이미 받은 건은 제외했다)")
    if not rows:
        return 0

    db = get_client() if args.save else None
    ok = failed = 0
    started = time.monotonic()
    for i, d in enumerate(rows, 1):
        # ★ 시간이 다 되면 **남았다는 사실을 밝히고** 멈춘다. 조용히 끝내면
        #   다음 사람이 "다 모였다"고 착각한다.
        if args.max_seconds and time.monotonic() - started > args.max_seconds:
            print(f"  ⏱ 시간 예산 {args.max_seconds:.0f}초 도달 — "
                  f"남은 {len(rows) - i + 1}건은 다음 실행으로 넘긴다")
            break
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
