# PRD Ref: §7 · §9.1 — 클릭형 LLM 분석 큐
from types import SimpleNamespace

from src.analysis import dashboard_requests as queue


ROW = {"id": 1, "code": "005930", "fiscal_year": 2026, "fiscal_quarter": 2}


def test_dashboard_request_analyzes_with_web_search_and_saves(monkeypatch):
    statuses = []
    data = SimpleNamespace(analysis_stage=None)
    result = SimpleNamespace(cost_usd=0.05)
    monkeypatch.setattr(queue, "pending_rows", lambda limit: [ROW])
    monkeypatch.setattr(queue, "check_budget", lambda: SimpleNamespace(allowed=True, reason=None))
    monkeypatch.setattr(queue, "claim", lambda row: True)
    monkeypatch.setattr(queue, "build_input", lambda *a, **k: data)
    called = {}
    monkeypatch.setattr(queue, "analyze", lambda value, **kwargs: called.update(kwargs) or result)
    monkeypatch.setattr(queue, "save", lambda value: called.update(saved=value))
    monkeypatch.setattr(queue, "set_status", lambda row_id, status, **kwargs: statuses.append(status))
    assert queue.run(3, 240) == 0
    assert data.analysis_stage == "dashboard_on_demand"
    assert called["web_search"] is True and called["saved"] is result
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
    result = SimpleNamespace(cost_usd=0.04)
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
    monkeypatch.setattr(queue, "save", lambda value: None)
    monkeypatch.setattr(queue, "set_status", lambda row_id, status, **kwargs: statuses.append(status))
    assert queue.run(3, 240) == 0
    assert [call["web_search"] for call in calls] == [True, False]
    assert statuses == ["completed"]
