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














def test_recoverable_failure_is_not_retried_after_automatic_repair_failed():
    assert queue.recoverable_failed_error("max_tokens(16384)에 걸려 잘렸다")
    assert queue.recoverable_failed_error("유료 응답 구조 검증 실패")
    assert not queue.recoverable_failed_error("자동복구 실패 — max_tokens(16384)")


def test_provider_usage_limit_waits_until_exact_utc_resume_time():
    row = {"error": "You have reached your specified API usage limits. You will regain access on 2026-10-01 at 00:00 UTC."}
    assert not queue.deferred_ready(row, now=datetime(2026, 9, 30, 23, 59, tzinfo=timezone.utc))
    assert queue.deferred_ready(row, now=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc))




def test_legacy_dashboard_entrypoint_delegates_to_pro_and_never_calls_api(monkeypatch):
    from unittest.mock import Mock
    import src.analysis.pro_worker as pro
    client = Mock()
    client.table.return_value.select.return_value.in_.return_value.order.return_value.range.return_value.execute.return_value.data = []
    monkeypatch.setattr(queue, "get_client", lambda: client)
    monkeypatch.setattr(queue, "analyze", lambda *args, **kwargs: pytest.fail("Legacy API path"))
    monkeypatch.setattr(pro, "run_once", lambda: {"status": "idle", "model_calls": 0})
    assert queue.run(1, 240) == 0
