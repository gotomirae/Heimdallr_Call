# PRD Ref: §9.1-3 · §10 — 수주 그래프용 과거 정기보고서 목록 발견
from __future__ import annotations

from datetime import date

from src.collectors import excerpt_run, order_history_run


def test_expected_reports_stops_young_listing_from_repeating_forever():
    today = date(2026, 9, 29)
    assert order_history_run.expected_reports("2026-06-01", today) == 1
    assert order_history_run.expected_reports("2025-09-01", today) == 4
    assert order_history_run.expected_reports("2020-01-01", today) == 10


def test_new_listing_does_not_require_unpublished_september_report():
    assert order_history_run.expected_reports("2024-10-24", date(2026, 10, 2)) == 7
    assert order_history_run.expected_reports("2024-07-29", date(2026, 10, 2)) == 8


def test_non_december_report_period_is_verified_from_annual_month():
    p = order_history_run.report_period("반기보고서 (2026.05)", 11)
    assert p == {"end": "2026-05-31", "closingMonth": 11, "fiscalYear": 2026,
                 "fiscalQuarter": 2, "reportKind": "반기보고서"}
    assert order_history_run.report_period("분기보고서 (2026.06)", 3)["fiscalQuarter"] == 1
    assert order_history_run.report_period("반기보고서 (2026.05)", 12) is None


def test_changed_closing_month_uses_adjacent_annual_not_entire_history():
    annuals = ["사업보고서 (2022.12)", "사업보고서 (2023.06)", "사업보고서 (2024.06)", "사업보고서 (2025.06)"]
    assert order_history_run.verified_report_period("반기보고서 (2024.12)", annuals)["closingMonth"] == 6
    assert order_history_run.verified_report_period("사업보고서 (2022.12)", annuals)["closingMonth"] == 12
    assert order_history_run.verified_report_period("반기보고서 (2025.12)", annuals)["fiscalQuarter"] == 2
    assert order_history_run.verified_report_period("분기보고서 (2021.03)", annuals) is None


def test_non_december_history_is_retained_without_fake_calendar_quarter(monkeypatch):
    class Response:
        def json(self):
            return {"status": "000", "list": [
                {"rcept_no": "20260715000001", "stock_code": "004310", "report_nm": "반기보고서 (2026.05)", "rcept_dt": "20260715"},
                {"rcept_no": "20260228000001", "stock_code": "004310", "report_nm": "사업보고서 (2025.11)", "rcept_dt": "20260228"},
            ]}
    monkeypatch.setattr(order_history_run, "require_env", lambda _name: "fixture")
    monkeypatch.setattr(order_history_run, "http_get", lambda *a, **k: Response())
    found = order_history_run.fetch_periodic_history({"code": "004310", "corp_code": "00000001"}, date(2026, 10, 2))
    assert len(found) == 2
    assert all(r["fiscal_year"] is None and r["fiscal_quarter"] is None for r in found)


def test_discovery_targets_only_codes_missing_expected_periods(monkeypatch):
    universe = [
        {"code": "000001", "name": "A", "corp_code": "00000001", "listed_at": "2020-01-01", "is_excluded": False},
        {"code": "000002", "name": "B", "corp_code": "00000002", "listed_at": "2026-06-01", "is_excluded": False},
    ]
    disclosures = [
        {"code": "000001", "doc_type": "periodic", "fiscal_year": 2024 + index // 4, "fiscal_quarter": index % 4 + 1}
        for index in range(9)
    ] + [{"code": "000002", "doc_type": "periodic", "fiscal_year": 2026, "fiscal_quarter": 2}]
    monkeypatch.setattr(order_history_run, "select_all", lambda table, *a, **k:
                        universe if table == "krx_universe" else disclosures)
    monkeypatch.setattr(excerpt_run, "attractiveness_rank", lambda: {"000001": 80, "000002": 90})
    assert [row["code"] for row in order_history_run.discovery_targets(20, date(2026, 9, 29))] == ["000001"]


def test_fetch_periodic_history_keeps_verified_periods_and_stock_code(monkeypatch):
    class Response:
        def json(self):
            return {"status": "000", "list": [
                {"rcept_no": "20260814000001", "stock_code": "000001", "report_nm": "반기보고서 (2026.06)", "rcept_dt": "20260814"},
                {"rcept_no": "20260514000001", "stock_code": "000001", "report_nm": "분기보고서 (2026.03)", "rcept_dt": "20260514"},
                {"rcept_no": "20260514000002", "stock_code": "999999", "report_nm": "분기보고서 (2026.03)", "rcept_dt": "20260514"},
                {"rcept_no": "20260901000001", "stock_code": "000001", "report_nm": "단일판매ㆍ공급계약체결", "rcept_dt": "20260901"},
            ]}

    monkeypatch.setattr(order_history_run, "require_env", lambda _name: "test-key")
    monkeypatch.setattr(order_history_run, "http_get", lambda *a, **k: Response())
    found = order_history_run.fetch_periodic_history(
        {"code": "000001", "corp_code": "00000001"}, date(2026, 9, 29)
    )
    assert [(row["fiscal_year"], row["fiscal_quarter"]) for row in found] == [(2026, 2), (2026, 1)]
    assert all(row["code"] == "000001" and row["doc_type"] == "periodic" for row in found)
