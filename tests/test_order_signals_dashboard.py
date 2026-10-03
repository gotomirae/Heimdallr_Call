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
        {"year": 2026, "quarter": 1, "backlogEok": 100, "newOrdersEok": 30, "scope": "별도 합계"},
        {"year": 2026, "quarter": 2, "backlogEok": 150, "newOrdersEok": 80, "scope": "별도 합계"},
    ]}])[0]
    assert len(rows) == 2
    assert rows[0]["revenue"] is None
    assert rows[1]["newOrders"] == 80
    assert rows[1]["orderBacklogQoq"] == 50


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
