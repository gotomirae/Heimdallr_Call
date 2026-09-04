# PRD Ref: §7, §9, §10 — 정정 후 갱신·변경 없는 재실행을 함께 검증한다.
from datetime import date

from src.analysis.freshness import facts_hash, render_excerpt, select_excerpt
from src.analysis import batch
from src.collectors import excerpt_run
from src.finance.backfill import recent_periodic_targets


def test_hash_ignores_collection_time_but_detects_financial_change():
    q = {"fiscal_year": 2026, "fiscal_quarter": 2, "revenue": 100}
    assert facts_hash([q], None) == facts_hash([{**q, "revenue": 100.0, "updated_at": "later"}], None)
    assert facts_hash([q], None) != facts_hash([{**q, "revenue": 110}], None)
    assert facts_hash([q], None) != facts_hash([q], "정정된 계약")


def test_correction_selected_regardless_of_db_order_and_future_excluded():
    old = {"fiscal_year": 2026, "fiscal_quarter": 2, "rcept_no": "20260814001", "sections": {"사업": "옛 계약"}}
    new = {**old, "rcept_no": "20260904002", "sections": {"사업": "정정 계약"}}
    future = {**new, "fiscal_quarter": 3, "rcept_no": "20261114001"}
    for rows in ([old, new, future], [future, new, old]):
        assert select_excerpt(rows, 2026, 2) == new
    assert "정정 계약" in render_excerpt(new, 2026, 2)


def test_collector_fetches_correction_once_then_stops(monkeypatch):
    old = {"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 2, "rcept_no": "20260814001", "report_nm": "반기보고서"}
    new = {**old, "rcept_no": "20260904002", "report_nm": "[기재정정]반기보고서"}
    tables = {"earnings_disclosures": [old, new], "disclosure_excerpts": [old]}
    monkeypatch.setattr(excerpt_run, "select_all", lambda table, *a, **k: tables[table])
    monkeypatch.setattr(excerpt_run, "attractiveness_rank", lambda: {})
    assert excerpt_run.targets(10, ["000001"]) == [new]
    tables["disclosure_excerpts"].append(new)
    assert excerpt_run.targets(10, ["000001"]) == []


def test_analysis_refreshes_changed_facts_once(monkeypatch):
    q = {"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 2, "revenue": 100, "is_estimate": False}
    a = {**q, "payload": {"_heimdallr": {"analysis_stage": "final", "facts_hash": facts_hash([q], None)}}}
    tables = {"analyses": [a], "quarterly_fundamentals": [q], "disclosure_excerpts": []}
    monkeypatch.setattr(batch, "select_all", lambda table, *a, **k: tables[table])
    assert ("000001", 2026, 2) in batch.already_analyzed(refresh_finalized=True)
    q["revenue"] = 110
    assert not batch.already_analyzed(refresh_finalized=True)
    a["payload"]["_heimdallr"]["facts_hash"] = facts_hash([q], None)
    assert ("000001", 2026, 2) in batch.already_analyzed(refresh_finalized=True)


def test_same_day_correction_detected_after_original_collection(monkeypatch):
    today = date.today().isoformat()
    d = {"code": "000001", "doc_type": "periodic", "fiscal_year": 2026, "fiscal_quarter": 2,
         "disclosed_at": today, "detected_at": today + "T08:00:00+00:00"}
    f = {**d, "is_estimate": False, "updated_at": today + "T07:00:00+00:00"}
    tables = {"earnings_disclosures": [d], "quarterly_fundamentals": [f]}
    monkeypatch.setattr("src.finance.backfill.select_all", lambda table, *a, **k: tables[table])
    assert recent_periodic_targets(7) == [d]
    f["updated_at"] = today + "T09:00:00+00:00"
    assert recent_periodic_targets(7) == []


def test_outcome_refresh_preserves_original_judgment_and_measured_return(monkeypatch):
    from src.analysis import outcome_run
    from src.analysis.outcome import Outcome

    old = {"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 2,
           "grade_at_announce": "○", "score_at_announce": 70, "pri_at_announce": 20,
           "ret_d5": 12, "excess_d5": 10}
    captured = []

    class DB:
        def table(self, name):
            return self
        def upsert(self, rows, **kwargs):
            captured.extend(rows)
            return self
        def execute(self):
            return None

    monkeypatch.setattr(outcome_run, "select_all", lambda *a, **k: [old])
    monkeypatch.setattr(outcome_run, "get_client", lambda: DB())
    outcome_run.save([Outcome(code="000001", fiscal_year=2026, fiscal_quarter=2,
                             announce_date="2026-08-14", grade_at_announce="★",
                             score_at_announce=95, pri_at_announce=5, horizons={})])
    assert captured[0]["grade_at_announce"] == "○"
    assert captured[0]["score_at_announce"] == 70
    assert captured[0]["ret_d5"] == 12
    assert captured[0]["excess_d5"] == 10


def test_refresh_workflows_cover_consensus_and_changed_analysis():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    workflows = root / ".github" / "workflows"
    daily = (workflows / "universe_daily.yml").read_text(encoding="utf-8")
    assert "src.collectors.consensus_run --save" in daily
    assert daily.index("src.collectors.consensus_run") < daily.index("src.screener.run")
    assert "--refresh-finalized" in (workflows / "llm_batch.yml").read_text(encoding="utf-8")
    poll = (workflows / "disclosure_poll.yml").read_text(encoding="utf-8")
    assert "vars.SEASON_MODE" not in poll
    assert 'cron: "*/30 0-14 * * *"' in poll
