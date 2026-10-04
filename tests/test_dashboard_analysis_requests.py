# PRD Ref: §7 · §9.1 — 클릭형 LLM 분석 큐
from types import SimpleNamespace
from datetime import datetime, timezone
import pytest

from src.analysis import dashboard_requests as queue


ROW = {"id": 1, "code": "005930", "fiscal_year": 2026, "fiscal_quarter": 2}


@pytest.fixture(autouse=True)
def stored_context(monkeypatch):
    monkeypatch.setattr(queue, "load_previous_analysis", lambda *args: {"next_data_to_watch": ["신규 고객 매출 전환"]})
    monkeypatch.setattr(queue, "load_narrative_history", lambda *args, **kwargs: [])


def test_dashboard_request_analyzes_with_web_search_and_saves(monkeypatch):
    statuses = []
    data = SimpleNamespace(analysis_stage=None)
    result = SimpleNamespace(cost_usd=0.05, payload={})
    monkeypatch.setattr(queue, "pending_rows", lambda limit: [ROW])
    monkeypatch.setattr(queue, "check_budget", lambda: SimpleNamespace(allowed=True, reason=None))
    monkeypatch.setattr(queue, "claim", lambda row: True)
    monkeypatch.setattr(queue, "build_input", lambda *a, **k: data)
    called = {}
    monkeypatch.setattr(queue, "analyze", lambda value, **kwargs: called.update(kwargs) or result)
    monkeypatch.setattr(queue, "validate_payload", lambda payload: [])
    monkeypatch.setattr(queue, "save", lambda value: called.update(saved=value))
    monkeypatch.setattr(queue, "set_status", lambda row_id, status, **kwargs: statuses.append(status))
    assert queue.run(3, 240) == 0
    assert data.analysis_stage == "dashboard_on_demand"
    assert data.previous_analysis["next_data_to_watch"] == ["신규 고객 매출 전환"]
    assert called["web_search"] is True and called["saved"] is result
    assert called["token_budget"] == queue.DASHBOARD_ANALYSIS_INPUT_TOKEN_BUDGET
    assert statuses == ["completed"]


def test_dashboard_request_waits_for_usage_reset(monkeypatch):
    statuses = []
    monkeypatch.setattr(queue, "pending_rows", lambda limit: [ROW])
    monkeypatch.setattr(queue, "check_budget", lambda: SimpleNamespace(allowed=False, reason="daily limit"))
    monkeypatch.setattr(queue, "set_status", lambda row_id, status, **kwargs: statuses.append((status, kwargs["error"])))
    monkeypatch.setattr(queue, "claim", lambda row: (_ for _ in ()).throw(AssertionError("must not claim")))
    assert queue.run(3, 240) == 0
    assert statuses == [("deferred", "daily limit")]


def test_dashboard_request_retries_same_provider_without_search_when_domain_is_blocked(monkeypatch):
    statuses = []
    data = SimpleNamespace(analysis_stage=None)
    result = SimpleNamespace(cost_usd=0.04, payload={})
    calls = []
    monkeypatch.setattr(queue, "pending_rows", lambda limit: [ROW])
    monkeypatch.setattr(queue, "check_budget", lambda: SimpleNamespace(allowed=True, reason=None))
    monkeypatch.setattr(queue, "claim", lambda row: True)
    monkeypatch.setattr(queue, "build_input", lambda *a, **k: data)

    def analyze(value, **kwargs):
        calls.append(kwargs)
        if kwargs["web_search"]:
            raise RuntimeError("The following domains are not accessible to our user agent: ['blocked.example']")
        return result

    monkeypatch.setattr(queue, "analyze", analyze)
    monkeypatch.setattr(queue, "validate_payload", lambda payload: [])
    monkeypatch.setattr(queue, "save", lambda value: None)
    monkeypatch.setattr(queue, "set_status", lambda row_id, status, **kwargs: statuses.append(status))
    assert queue.run(3, 240) == 0
    assert [call["web_search"] for call in calls] == [True, False]
    assert statuses == ["completed"]


def test_dashboard_request_compacts_excerpt_after_free_token_preflight(monkeypatch):
    statuses = []
    data = SimpleNamespace(analysis_stage=None, excerpt="공시" * 1000)
    result = SimpleNamespace(cost_usd=0.06, payload={})
    calls = []
    monkeypatch.setattr(queue, "pending_rows", lambda limit: [ROW])
    monkeypatch.setattr(queue, "check_budget", lambda: SimpleNamespace(allowed=True, reason=None))
    monkeypatch.setattr(queue, "claim", lambda row: True)
    monkeypatch.setattr(queue, "build_input", lambda *a, **k: data)

    def analyze(value, **kwargs):
        calls.append((value, kwargs))
        if len(calls) <= 2:
            raise queue.AnalysisError("005930: 입력 23,059토큰이 상한 16,000을 넘었다.")
        return result

    monkeypatch.setattr(queue, "analyze", analyze)
    monkeypatch.setattr(queue, "validate_payload", lambda payload: [])
    monkeypatch.setattr(queue, "save", lambda value: None)
    monkeypatch.setattr(queue, "set_status", lambda row_id, status, **kwargs: statuses.append(status))
    assert queue.run(3, 240) == 0
    assert [call[1]["web_search"] for call in calls] == [True, True, False]
    assert len(calls[1][0].excerpt) == queue.DASHBOARD_ON_DEMAND_EXCERPT_MAX_CHARS
    assert len(calls[2][0].excerpt) == queue.DASHBOARD_ON_DEMAND_EXCERPT_MAX_CHARS
    assert len(data.excerpt) == queue.DASHBOARD_ON_DEMAND_EXCERPT_MAX_CHARS
    assert statuses == ["completed"]


def test_dashboard_request_repairs_invalid_web_payload_with_strict_contract(monkeypatch):
    statuses = []
    data = SimpleNamespace(analysis_stage=None, excerpt="공시")
    invalid = SimpleNamespace(cost_usd=0.06, payload={"earnings_change": "flattened"})
    repaired = SimpleNamespace(cost_usd=0.03, payload={"valid": True})
    saved = []
    monkeypatch.setattr(queue, "pending_rows", lambda limit: [ROW])
    monkeypatch.setattr(queue, "check_budget", lambda: SimpleNamespace(allowed=True, reason=None))
    monkeypatch.setattr(queue, "claim", lambda row: True)
    monkeypatch.setattr(queue, "build_input", lambda *a, **k: data)
    calls = []
    monkeypatch.setattr(queue, "analyze", lambda value, **kwargs: calls.append(kwargs) or (invalid if kwargs["web_search"] else repaired))
    monkeypatch.setattr(queue, "validate_payload", lambda payload: [] if payload.get("valid") else ["type:earnings_change"])
    monkeypatch.setattr(queue, "save", lambda value: saved.append(value))
    monkeypatch.setattr(
        queue,
        "set_status",
        lambda row_id, status, **kwargs: statuses.append((status, kwargs.get("error"))),
    )

    assert queue.run(3, 240) == 0
    assert saved == [repaired]
    assert [call["web_search"] for call in calls] == [True, False]
    assert statuses[0][0] == "completed"


def test_dashboard_request_repairs_truncated_web_output_once(monkeypatch):
    statuses = []
    data = SimpleNamespace(analysis_stage=None, excerpt="공시" * 1000)
    result = SimpleNamespace(cost_usd=0.03, payload={})
    calls = []
    monkeypatch.setattr(queue, "pending_rows", lambda limit: [ROW])
    monkeypatch.setattr(queue, "check_budget", lambda: SimpleNamespace(allowed=True, reason=None))
    monkeypatch.setattr(queue, "claim", lambda row: True)
    monkeypatch.setattr(queue, "build_input", lambda *a, **k: data)

    def analyze(value, **kwargs):
        calls.append((value, kwargs))
        if kwargs["web_search"]:
            raise queue.AnalysisError("005930: max_tokens(16384)에 걸려 잘렸다. 비용 $0.17")
        return result

    monkeypatch.setattr(queue, "analyze", analyze)
    monkeypatch.setattr(queue, "validate_payload", lambda payload: [])
    monkeypatch.setattr(queue, "save", lambda value: None)
    monkeypatch.setattr(queue, "set_status", lambda row_id, status, **kwargs: statuses.append(status))
    assert queue.run(1, 240) == 0
    assert [call[1]["web_search"] for call in calls] == [True, False]
    assert statuses == ["completed"]


def test_recoverable_failure_is_not_retried_after_automatic_repair_failed():
    assert queue.recoverable_failed_error("max_tokens(16384)에 걸려 잘렸다")
    assert queue.recoverable_failed_error("유료 응답 구조 검증 실패")
    assert not queue.recoverable_failed_error("자동복구 실패 — max_tokens(16384)")


def test_provider_usage_limit_waits_until_exact_utc_resume_time():
    row = {"error": "You have reached your specified API usage limits. You will regain access on 2026-10-01 at 00:00 UTC."}
    assert not queue.deferred_ready(row, now=datetime(2026, 9, 30, 23, 59, tzinfo=timezone.utc))
    assert queue.deferred_ready(row, now=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc))


def test_strict_repair_provider_usage_limit_is_deferred(monkeypatch):
    statuses = []
    data = SimpleNamespace(analysis_stage=None, excerpt="공시")
    limit_message = (
        "You have reached your specified API usage limits. "
        "You will regain access on 2026-10-01 at 00:00 UTC."
    )
    monkeypatch.setattr(queue, "pending_rows", lambda limit: [ROW])
    monkeypatch.setattr(queue, "check_budget", lambda: SimpleNamespace(allowed=True, reason=None))
    monkeypatch.setattr(queue, "claim", lambda row: True)
    monkeypatch.setattr(queue, "build_input", lambda *a, **k: data)

    def analyze(value, **kwargs):
        if kwargs["web_search"]:
            raise queue.AnalysisError("005930: max_tokens(16384)에 걸려 잘렸다. 비용 $0.17")
        raise RuntimeError(limit_message)

    monkeypatch.setattr(queue, "analyze", analyze)
    monkeypatch.setattr(
        queue,
        "set_status",
        lambda row_id, status, **kwargs: statuses.append((status, kwargs.get("error"))),
    )

    assert queue.run(1, 240) == 0
    assert statuses[0][0] == "deferred"
    assert limit_message in statuses[0][1]
