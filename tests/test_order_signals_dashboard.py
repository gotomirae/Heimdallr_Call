# PRD Ref: §9.1 · traps.md T99/T100
"""종목 상세의 수주 공시 신호가 조용히 과장되지 않는지 검증한다."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard"
SCRIPT = DASHBOARD / "scripts" / "order_signal_cases.mjs"


pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (DASHBOARD / "node_modules" / "jiti").exists(),
    reason="node 또는 dashboard/node_modules/jiti가 없다 (npm install 필요)",
)


def _run(cases: list[dict]) -> list[dict | None]:
    proc = subprocess.run(
        [shutil.which("node") or "node", str(SCRIPT)],
        input=json.dumps(cases, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=DASHBOARD,
        timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"order_signal_cases.mjs 실패:\n{proc.stderr[-2000:]}")
    return json.loads(proc.stdout)


def test_order_reports_are_plotted_without_fundamental_rows():
    # 손계산: 재무 0행이어도 100→150의 같은 범위 연속 잔고 QoQ는 +50%다.
    rows = _run([{"orderReportPoints": True, "points": [], "reports": [
        {"year": 2026, "quarter": 1, "backlogEok": 100, "newOrdersEok": 30, "scope": "별도 합계", "newOrdersPeriod": "보고기간 누적"},
        {"year": 2026, "quarter": 2, "backlogEok": 150, "newOrdersEok": 80, "scope": "별도 합계", "newOrdersPeriod": "보고기간 누적"},
    ]}])[0]
    assert len(rows) == 2
    assert rows[0]["revenue"] is None
    assert rows[1]["newOrders"] == 50  # 반기 80 - 1분기 30
    assert rows[1]["orderBacklogQoq"] == 50


def test_verified_shipbuilding_ir_cumulative_orders_reach_real_chart_contract():
    from src.collectors.order_ir import format_ir_metric
    manifest = json.loads((DASHBOARD.parent / "src/config/order_ir_verified.json").read_text(encoding="utf-8"))
    cases = []
    for code in ("042660", "062040", "329180", "012450"):
        facts = [f for f in manifest if f['code'] == code]
        rows = []
        for f in facts:
            # 검증 장부의 원문 누적값을 실제 저장 문자열→실제 대시보드 계산으로 재생.
            rows.append({'code': code, 'rcept_no': f"{f['year']}0{f['quarter']}14000001", 'fiscal_year': f['year'],
                         'fiscal_quarter': f['quarter'], 'sections': {'공시 수주지표 확인': '완료',
                         '공식 IR 수주지표': {'series': [format_ir_metric(f)]}}})
        cases.append({'companyAudit': True, 'company': {'code': code, 'name': code}, 'rows': rows})
    ocean, sanil, hhi, aero = _run(cases)
    # 손계산: Ocean (38.0−19.1)×100=1890백만USD, HHI 14771−6119=8652백만USD.
    assert ocean['series'][0]['complete'] and ocean['series'][0]['newOrders'] == 1890
    assert ocean['series'][0]['qoq'] == pytest.approx((25250 / 26020 - 1) * 100)
    assert sanil['series'][0]['complete'] and sanil['series'][0]['newOrders'] == 2435
    assert sanil['series'][0]['history'] == {'backlog': 8, 'newOrders': 8, 'qoq': 7, 'complete': 7}
    assert hhi['series'][0]['complete'] and hhi['series'][0]['newOrders'] == 8652
    assert hhi['series'][0]['qoq'] == pytest.approx((45177 / 41173 - 1) * 100)
    # 주요 계약 합계나 잔고 차액으로 전체 신규를 만들어 완전하다고 표시하지 않는다.
    assert aero['series'][0]['newOrders'] is None and aero['series'][0]['complete'] is False
    assert aero['series'][0]['qoq'] == pytest.approx((383000 / 382000 - 1) * 100)


def test_verified_acquisition_scope_survives_report_recollection():
    def row(q, backlog):
        end = "2026-03-31" if q == 1 else "2026-06-30"
        return {"code": "082740", "rcept_no": f"20260{q}14000001", "fiscal_year": 2026, "fiscal_quarter": q,
                "sections": {"공시 수주지표 확인": "완료", "공시 보고기간": {"end": end, "closingMonth": 12, "fiscalYear": 2026, "fiscalQuarter": q, "reportKind": "분기보고서" if q == 1 else "반기보고서"},
                             "공시 수주지표": f"범위 | 회사 공시 합계\n단위 | 억원\n수주잔고 | {backlog}"}}
    first, second = row(1, 52430), row(2, 59789)
    second["sections"]["수주 범위 변경 근거"] = {
        "effectivePeriodEnd": "2026-06-30", "fromScope": "회사 공시 합계",
        "toScope": "연결 공시 합계 (2026Q2 SEAM 편입 이후)",
        "sourceUrl": "https://www.hanwha-engine.com/attach/download/report", "sha256": "a" * 64,
    }
    [audit] = _run([{"companyAudit": True, "company": {"code": "082740", "name": "한화엔진"}, "rows": [first, second]}])
    # 59,789 / 52,430 - 1 ≈ 14.04%는 인수 범위가 달라 계산하지 않는다.
    current = next(s for s in audit["series"] if s["period"] == "2026-06")
    assert current["scope"] == "연결 공시 합계 (2026Q2 SEAM 편입 이후)"
    assert current["qoq"] is None
    assert len(audit["series"]) == 2


def test_company_classification_is_independent_from_metric_coverage():
    base = {"code": "123456", "rcept_no": "20260814000001", "fiscal_year": 2026, "fiscal_quarter": 2,
            "sections": {"공시 수주지표 확인": "완료", "order_business_evidence": {"status": "confirmed", "basis": "수주 내역 비공개", "evidence": "기밀"}}}
    result = _run([{"companyAudit": True, "company": {"code": "123456", "name": "장비사"}, "rows": [base]}])[0]
    assert result["status"] == "confirmed"
    assert result["series"] == []


def test_company_audit_uses_same_scope_and_latest_report_period():
    def row(q, backlog, cumulative):
        return {"code": "123456", "rcept_no": f"20260{q}14000001", "fiscal_year": 2026, "fiscal_quarter": q,
                "sections": {"공시 수주지표 확인": "완료", "공시 수주지표":
                             f"단위 | 억원\n범위 | 연결 전체\n수주잔고 | {backlog}\n신규수주 | {cumulative}\n신규수주 기간 | 보고기간 누적"}}
    # 손계산: Q2 신규 80-30=50, 잔고 QoQ=(150/100-1)*100=50.
    rows = [row(1, 100, 30), row(2, 150, 80)]
    complete = _run([{"companyAudit": True, "company": {"code": "123456", "name": "장비사"}, "rows": rows}])[0]
    assert complete["series"][0]["complete"] is True
    assert complete["series"][0]["newOrders"] == 50
    assert complete["series"][0]["qoq"] == 50
    latest = {"code": "123456", "rcept_no": "20261114000001", "fiscal_year": 2026, "fiscal_quarter": 3,
              "sections": {"공시 수주지표 확인": "완료"}}
    stale = _run([{"companyAudit": True, "company": {"code": "123456", "name": "장비사"}, "rows": [*rows, latest]}])[0]
    assert stale["series"][0]["complete"] is False


def test_new_orders_are_quarterized_only_with_comparable_cumulative_sources():
    base = {"year": 2026, "scope": "연결 전체", "backlogEok": 100,
            "newOrdersPeriod": "보고기간 누적"}
    reports = [{**base, "quarter": q, "newOrdersEok": amount}
               for q, amount in enumerate([30, 80, 120, 170], 1)]
    cases = [reports, [reports[0], reports[2]],
             [reports[0], {**reports[1], "scope": "별도 전체"}],
             [reports[0], {**reports[1], "newOrdersEok": 20}],
             [{**reports[1], "newOrdersPeriod": "당분기"}],
             [{**reports[1], "newOrdersPeriod": None}],
             [reports[0], {**reports[1], "amountUnit": "백만USD", "newOrdersAmount": 80}]]
    result = _run([{"orderReportPoints": True, "points": [], "reports": rows} for rows in cases])
    # 손계산: 누적 30/80/120/170 → 단독 30/50/40/50. 범위/통화/기간 혼합 금지.
    assert [p["newOrders"] for p in result[0]] == [30, 50, 40, 50]
    assert result[0][1]["newOrdersCumulative"] == 80
    for index in (1, 2, 3, 5, 6):
        assert result[index][-1]["newOrders"] is None
    assert result[4][0]["newOrders"] == 80


def test_official_ir_metrics_keep_their_source_and_dart_scope_separate():
    row = {"rcept_no": "20260814000001", "code": "267260", "fiscal_year": 2026, "fiscal_quarter": 2,
           "sections": {"공시 수주지표": "범위 | 별도 합계\n단위 | 억원\n수주잔고 | 100",
                        "공식 IR 수주지표": {"series": ["범위 | 공식 IR 연결 전체\n단위 | 백만USD\n수주잔고 | 8490\n신규수주 | 1440\n신규수주 기간 | 당분기\n출처 | https://www.hd-hyundaielectric.com/ir.pdf\n출처 페이지 | 4\n자료명 | 공식 IR"]}}}
    result = _run([{"metrics": True, "row": row}])[0]
    assert len(result) == 2 and result[0]["backlogEok"] == 100
    assert result[1]["backlogEok"] is None and result[1]["backlogAmount"] == 8490
    assert result[1]["sourcePage"] == "4" and result[1]["sourceUrl"].startswith("https://www.hd-hyundaielectric.com/")


def test_business_scopes_are_preserved_without_replacing_or_adding_totals():
    metrics = _run([{"metrics": True, "row": {"rcept_no": "20260814003496", "fiscal_year": 2026,
        "fiscal_quarter": 2, "sections": {"공시 수주지표 목록": {"series": [
            "범위 | 조선부문\n단위 | 억원\n수주잔고 | 19,043",
            "범위 | 건설부문\n단위 | 백만원\n수주잔고 | 8,330,749"]}}}}])[0]
    assert [(r["scope"], r["backlogEok"]) for r in metrics] == [("조선부문", 19043), ("건설부문", 83307.49)]


def test_foreign_backlog_is_not_misrepresented_as_won():
    result = _run([{"metric": True, "row": {"rcept_no": "1", "fiscal_year": 2026, "fiscal_quarter": 2,
        "sections": {"공시 수주지표": "범위 | 최소구매물량\n단위 | 백만USD\n수주잔고 | 9,923"}}}])[0]
    assert result['backlogEok'] is None and result['backlogAmount'] == 9923 and result['amountUnit'] == '백만USD'


def test_small_dollar_new_orders_keep_cents_through_conversion_chart_and_display():
    # 우리기술 원문: H1 $2,414.24 − Q1 $2,053.46 = Q2 $360.78.
    rows = [{"rcept_no": str(q), "fiscal_year": 2026, "fiscal_quarter": q,
             "sections": {"공시 수주지표": f"범위 | 수출계약\n단위 | USD\n수주잔고 | 18638870.25\n신규수주 | {amount}\n신규수주 기간 | 보고기간 누적"}}
            for q, amount in [(1, "2053.46"), (2, "2414.24")]]
    reports = _run([{"metric": True, "row": row} for row in rows])
    assert reports[1]["newOrdersAmount"] == pytest.approx(0.00241424)
    chart = _run([{"orderReportPoints": True, "points": [], "reports": reports}])[0]
    assert chart[1]["newOrders"] == pytest.approx(0.00036078)
    assert _run([{"orderAmount": True, "value": value} for value in
                 [chart[1]["newOrders"], 0, None, 840.30367877]]) == ["0.00036078", "0.00", "—", "840.30"]


def test_latest_complete_order_chart_precedes_backlog_only_without_promoting_stale_series():
    def point(year, quarter, backlog, new):
        return {"fiscalYear": year, "fiscalQuarter": quarter, "orderScope": "연결", "orderBacklog": backlog, "newOrders": new}
    series = [{"scope": "현재 잔고만", "points": [point(2026, 1, 100, None), point(2026, 2, 120, None)]},
              {"scope": "과거 완전", "points": [point(2025, 1, 100, 0), point(2025, 2, 120, 30)]},
              {"scope": "현재 완전", "points": [point(2026, 1, 100, 0), point(2026, 2, 120, 30)]}]
    result = _run([{"orderSeries": True, "series": series}])[0]
    assert [s["scope"] for s in result] == ["현재 완전", "현재 잔고만", "과거 완전"]
    assert sum(len(s["points"]) for s in result) == 6


def test_contract_window_starts_after_actual_period_not_announcement_or_current_quarter():
    rows = [{"disclosedAt": day} for day in ["2026-06-30", "2026-07-01", "2026-08-01", "2026-10-02", "2026-10-04"]]
    result = _run([{"periodWindow": True, "rows": rows, "basisDate": "2026-10-03", "periodEnd": "2026-06-30"}])[0]
    assert [r["disclosedAt"] for r in result] == ["2026-07-01", "2026-08-01", "2026-10-02"]
    assert _run([{"periodWindow": True, "rows": rows, "basisDate": "2026-10-03", "periodEnd": None}])[0] == []
    assert _run([{"periodName": True, "reportName": "반기보고서 (2026.06)"},
                 {"periodName": True, "reportName": "사업보고서 (2026.02)"},
                 {"periodName": True, "reportName": "[첨부정정]반기보고서 (2026.06)"}]) == ["2026-06-30", "2026-02-28", None]


def test_quarter_study_uses_actual_periods_and_breaks_missing_margin_comparisons():
    # 손계산: GPM 20→25는 +5%p, Q2→Q4 사이 누락은 비교 불가.
    points = [{"label": f"Q{q}", "fiscalYear": 2026, "fiscalQuarter": q,
               "revenue": 100, "op": 10, "gpm": gpm, "opm": 10,
               "revenueYoy": 5, "opYoy": None, "opStatusLabel": "흑전"}
              for q, gpm in [(1, 20), (2, 25), (4, 30)]]
    result = _run([{"quarterStudy": True, "points": points + [{**points[-1], "isCurrentQuarter": True}]}])[0]
    assert len(result["rows"]) == 3
    assert "GPM +5.0%p" in result["rows"][1]["characteristic"]
    assert "GPM 비교 불가" in result["rows"][2]["characteristic"]
    assert "흑전" in result["rows"][1]["characteristic"]
    assert "계절성 판단을 보류" in result["seasonality"]


def test_old_contract_correction_is_not_a_new_contract_amount():
    # 실제 399720 10/1 정정공시: 계약 체결일은 2025/12/24, 정정 총액은 증가분이 아니다.
    row = {"rcept_no": "20261001900382", "sections": {"단일판매·공급계약": {
        "report_name": "[기재정정]단일판매ㆍ공급계약체결",
        "contract_date": "2025-12-24", "disclosed_at": "2026-10-01",
        "amount_krw": 17880400000,
    }}}
    result = _run([{"contract": True, "row": row}])[0]
    assert result["isCorrection"] is True
    assert result["amountEok"] == 178.804
    source = (DASHBOARD / "app" / "stock" / "[code]" / "page.tsx").read_text(encoding="utf-8")
    assert 'item.status === "terminated" || item.isCorrection' in source


def test_only_attachment_correction_is_excluded_from_business_report_date():
    assert _run([{"attachmentCorrection": True, "reportName": name} for name in (
        "[첨부정정]반기보고서 (2026.06)", "[기재정정]반기보고서 (2026.06)",
        "[첨부추가]반기보고서 (2026.06)", "반기보고서 (2026.06)", None,
    )]) == [True, False, False, False, False]


def test_non_calendar_order_metric_and_charts_keep_actual_period_end():
    period = {"end": "2026-05-31", "closingMonth": 11, "fiscalYear": 2026,
              "fiscalQuarter": 2, "reportKind": "반기보고서"}
    row = {"rcept_no": "20260715000001", "fiscal_year": None, "fiscal_quarter": None,
           "sections": {"공시 보고기간": period, "공시 수주지표": "단위 | 억원\n범위 | 회사 전체\n수주잔고 | 120"}}
    metric = _run([{"metric": True, "row": row}])[0]
    assert metric["periodEnd"] == "2026-05-31"
    assert metric["periodLabel"] == "26-05(반기)"
    assert _run([{"summary": True, "row": row}])[0]["periodLabel"] == "26-05(반기)"
    reports = [{**metric, "backlogEok": 100, "quarter": 1, "periodEnd": "2026-02-28", "periodLabel": "26-02(분기)"}, metric]
    points = _run([{"orderReportPoints": True, "points": [], "reports": reports}])[0]
    assert len(points) == 2
    assert points[1]["orderBacklogQoq"] == pytest.approx(20)
    changed = [{**reports[0], "closingMonth": 12}, reports[1]]
    assert _run([{"orderReportPoints": True, "points": [], "reports": changed}])[0][1]["orderBacklogQoq"] is None
    malformed = {**row, "sections": {**row["sections"], "공시 보고기간": {**period, "end": "2026-05-99"}}}
    assert _run([{"metric": True, "row": malformed}]) == [None]


def test_order_signal_requires_same_quarter_and_actual_order_language():
    cases = [
        {
            "row": {
                "fiscal_year": 2026,
                "fiscal_quarter": 2,
                "sections": {"매출 및 수주상황": "신규 수주 350억원을 확보했다."},
            },
            "year": 2026,
            "quarter": 2,
        },
        {
            "row": {
                "fiscal_year": 2026,
                "fiscal_quarter": 1,
                "sections": {"매출 및 수주상황": "수주잔고 900억원"},
            },
            "year": 2026,
            "quarter": 2,
        },
        {
            "row": {
                "fiscal_year": 2026,
                "fiscal_quarter": 2,
                "sections": {"매출 및 수주상황": "제품별 매출 실적을 기재한다."},
            },
            "year": 2026,
            "quarter": 2,
        },
        {
            "row": {
                "fiscal_year": 2026,
                "fiscal_quarter": 2,
                "sections": {"원재료 및 생산설비": "원재료 장기공급계약을 체결했다."},
            },
            "year": 2026,
            "quarter": 2,
        },
    ]

    found, wrong_quarter, heading_only, procurement_contract = _run(cases)
    assert found is not None
    assert found["status"] == "evidence"
    assert found["sourceLabel"] == "2026년 2분기 정기보고서"
    assert "350억원" in found["evidence"]
    assert wrong_quarter is None
    assert heading_only is None
    assert procurement_contract is None


def test_structured_disclosure_backlog_preserves_major_contract_scope():
    body = "범위 | 주요계약(전체 회사 아님)\n단위 | 백만원\n수주잔고 | 10,561,864"
    base = {"rcept_no": "20260814004047", "fiscal_year": 2026, "fiscal_quarter": 2,
            "sections": {"공시 수주지표": body}}
    actual, ambiguous = _run([
        {"metric": True, "row": base},
        {"metric": True, "row": {**base, "sections": {"공시 수주지표": body.replace("백만원", "단위 불명")}}},
    ])
    assert actual == {"year": 2026, "quarter": 2, "rceptNo": "20260814004047",
                      "backlogEok": 105618.64, "newOrdersEok": None,
                      "scope": "주요계약(전체 회사 아님)", "newOrdersPeriod": None}
    assert ambiguous is None


def test_nondisclosure_and_truncation_are_exposed_not_inferred():
    limited, clipped = _run(
        [
            {
                "row": {
                    "fiscal_year": 2026,
                    "fiscal_quarter": 2,
                    "sections": {"매출 및 수주상황": "수주잔고는 영업상 비공개입니다."},
                },
                "year": 2026,
                "quarter": 2,
            },
            {
                "row": {
                    "fiscal_year": 2026,
                    "fiscal_quarter": 2,
                    "sections": {
                        "매출 및 수주상황": "수주잔고 관련 내용 …(이하 1,240자 생략)"
                    },
                },
                "year": 2026,
                "quarter": 2,
            },
        ]
    )

    assert limited is not None and limited["status"] == "limited"
    assert limited["truncated"] is False
    assert clipped is not None and clipped["truncated"] is True


def test_every_fetched_report_has_an_explicit_order_status():
    private, unmentioned = _run([
        {"summary": True, "row": {"rcept_no": "1", "code": "000001",
          "fiscal_year": 2026, "fiscal_quarter": 2,
          "sections": {"매출 및 수주상황": "수주잔고는 영업상 비공개입니다."}}},
        {"summary": True, "row": {"rcept_no": "2", "code": "000002",
          "fiscal_year": 2026, "fiscal_quarter": 2,
          "sections": {"매출 및 수주상황": "제품별 매출 실적을 기재한다."}}},
    ])
    assert private["status"] == "private" and private["statusLabel"] == "비공개·기재 생략"
    assert unmentioned["status"] == "unmentioned"
    assert unmentioned["backlogEok"] is None and unmentioned["newOrdersEok"] is None


def test_single_sales_contract_is_kept_separate_from_total_new_orders():
    contract, periodic = _run([
        {"contract": True, "row": {"rcept_no": "20260924000001", "sections": {
            "단일판매·공급계약": {
                "disclosed_at": "2026-09-24", "contract_name": "HBM 검사장비 공급",
                "amount_krw": 12340000000, "sales_ratio_pct": 12.34,
                "counterparty": "Global Customer", "start_date": "2026-10-01",
                "end_date": "2027-03-31",
            }}}},
        {"summary": True, "row": {"rcept_no": "20260924000001", "code": "000001",
            "fiscal_year": None, "fiscal_quarter": None,
            "sections": {"단일판매·공급계약": {"amount_krw": 12340000000}}}},
    ])
    assert contract["amountEok"] == 123.4
    assert contract["contractName"] == "HBM 검사장비 공급"
    assert periodic is None  # 수시공시 금액을 정기보고서 신규수주로 둔갑시키지 않는다.


def test_order_backlog_qoq_requires_consecutive_quarters_and_same_scope():
    [points] = _run([{"chartQoq": True, "points": [
        {"fiscalYear": 2025, "fiscalQuarter": 1, "orderBacklog": 100, "orderScope": "회사 공시 합계"},
        {"fiscalYear": 2025, "fiscalQuarter": 2, "orderBacklog": 125, "orderScope": "회사 공시 합계"},
        {"fiscalYear": 2025, "fiscalQuarter": 3, "orderBacklog": 150, "orderScope": "주요계약(전체 아님)"},
        {"fiscalYear": 2025, "fiscalQuarter": 4, "orderBacklog": None, "orderScope": None},
        {"fiscalYear": 2026, "fiscalQuarter": 1, "orderBacklog": 180, "orderScope": "주요계약(전체 아님)"},
        {"fiscalYear": 2026, "fiscalQuarter": 2, "orderBacklog": 198, "orderScope": "주요계약(전체 아님)"},
    ]}])
    values = [row["orderBacklogQoq"] for row in points]
    assert values[:1] == [None]
    assert values[1] == pytest.approx(25)
    assert values[2:5] == [None, None, None]
    assert values[5] == pytest.approx(10)


def test_company_total_scope_and_reported_new_order_period_are_preserved():
    body = ("범위 | 회사 공시 단일행\n단위 | 백만원\n수주잔고 | 65,266\n"
            "신규수주 | 76,122\n신규수주 기간 | 보고기간 누적")
    [metric] = _run([{"metric": True, "row": {
        "rcept_no": "20260814003218", "fiscal_year": 2026, "fiscal_quarter": 2,
        "sections": {"공시 수주지표": body},
    }}])
    assert metric["scope"] == "회사 공시 단일행"
    assert metric["backlogEok"] == 652.66
    assert metric["newOrdersEok"] == 761.22
    assert metric["newOrdersPeriod"] == "보고기간 누적"


def test_first_quarter_standalone_is_valid_prior_for_half_year_cumulative():
    base = {"year": 2026, "scope": "연결 전체", "backlogEok": 100}
    reports = [{**base, "quarter": 1, "newOrdersEok": 628.61, "newOrdersPeriod": "당분기"},
               {**base, "quarter": 2, "newOrdersEok": 1412.76, "newOrdersPeriod": "보고기간 누적"}]
    half, third = _run([
        {"orderReportPoints": True, "points": [], "reports": reports},
        {"orderReportPoints": True, "points": [], "reports": [
            {**reports[0], "quarter": 2}, {**reports[1], "quarter": 3}]},
    ])
    # 손계산: 1Q 단독은 1Q 누적과 동일 → 2Q=1412.76−628.61=784.15.
    assert half[1]["newOrders"] == pytest.approx(784.15)
    assert third[1]["newOrders"] is None  # 2Q 단독은 반기 누적이 아니다.


def test_contract_window_is_six_months_post_report_and_current_quarter():
    rows = [
        {"rceptNo": "1", "disclosedAt": "2026-07-02"},
        {"rceptNo": "2", "disclosedAt": "2026-08-13"},
        {"rceptNo": "3", "disclosedAt": "2026-08-14"},
        {"rceptNo": "4", "disclosedAt": "2026-09-30"},
        {"rceptNo": "5", "disclosedAt": "2026-10-01"},
    ]
    [filtered] = _run([{
        "contractWindow": True, "rows": rows, "basisDate": "2026-09-30",
        "latestPeriodicReportDate": "2026-08-13",
    }])
    assert [row["rceptNo"] for row in filtered] == ["3", "4"]


def test_verified_ir_amount_survives_storage_without_scientific_notation_or_rounding():
    from src.collectors.order_ir import format_ir_metric
    # 실제 현대건설 26Q2 1,039,831억원은 :g 기본 정밀도에서 지수 문자열로 바뀐다.
    fact = {"scope": "공식 IR 연결", "unit": "억원", "backlog": 1039831,
            "new_orders": 228230.12, "new_orders_period": "보고기간 누적",
            "source_url": "https://www.hdec.kr/ir.pdf", "source_page": 8}
    [metric] = _run([{"metric": True, "row": {
        "rcept_no": "20260814003360", "fiscal_year": 2026, "fiscal_quarter": 2,
        "sections": {"공시 수주지표": format_ir_metric(fact)},
    }}])
    assert metric["backlogEok"] == 1039831
    assert metric["newOrdersEok"] == 228230.12
