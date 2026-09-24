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
                      "scope": "공시 주요계약 수주잔고(전체 아님)"}
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
