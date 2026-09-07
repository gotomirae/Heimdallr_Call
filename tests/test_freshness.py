# PRD Ref: §7, §9, §10 — 정정 후 갱신·변경 없는 재실행을 함께 검증한다.
from datetime import date

from src.analysis.freshness import (
    facts_hash,
    render_excerpt,
    report_refresh_decision,
    select_excerpt,
)
from src.analysis import batch
from src.collectors import excerpt_run
from src.finance.backfill import recent_periodic_targets


def test_hash_ignores_collection_time_but_detects_financial_change():
    q = {"fiscal_year": 2026, "fiscal_quarter": 2, "revenue": 100}
    assert facts_hash([q], None) == facts_hash([{**q, "revenue": 100.0, "updated_at": "later"}], None)
    assert facts_hash([q], None) != facts_hash([{**q, "revenue": 110}], None)
    assert facts_hash([q], None) != facts_hash([q], "정정된 계약")


def test_report_refresh_waits_for_five_actual_market_sessions():
    rows = [{
        "fiscal_year": 2026,
        "fiscal_quarter": 0,
        "op_est": 100,
        "source": "naver",
        "snapshot_at": "2026-09-04T08:00:00+09:00",
    }]
    four_sessions = ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10"]
    assert not report_refresh_decision(
        rows,
        four_sessions,
        filing_at="2026-09-04",
        year=2026,
        quarter=2,
        trading_days=5,
    ).ready


def test_report_refresh_requires_actual_consensus_change():
    base = {
        "fiscal_year": 2026,
        "fiscal_quarter": 0,
        "op_est": 100,
        "source": "naver",
    }
    sessions = ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"]
    unchanged = report_refresh_decision(
        [
            {**base, "snapshot_at": "2026-09-04T08:00:00+09:00"},
            {**base, "snapshot_at": "2026-09-11T08:00:00+09:00"},
        ],
        sessions,
        filing_at="2026-09-04",
        year=2026,
        quarter=2,
        trading_days=5,
    )
    changed = report_refresh_decision(
        [
            {**base, "snapshot_at": "2026-09-04T08:00:00+09:00"},
            {**base, "op_est": 120, "snapshot_at": "2026-09-11T08:00:00+09:00"},
        ],
        sessions,
        filing_at="2026-09-04",
        year=2026,
        quarter=2,
        trading_days=5,
    )
    assert unchanged.ready and not unchanged.changed
    assert changed.ready and changed.changed
    assert changed.context and changed.context["changes"][0]["before"]["op_est"] == "1E+2"
    assert changed.context["changes"][0]["after"]["op_est"] == "1.2E+2"
    search = unchanged.context["report_search"]
    assert search["published_from"] == "2026-09-04"
    assert search["published_through"] == "2026-09-11"
    assert [c["url"] for c in search["priority_channels"]] == [
        "https://t.me/s/sunstudy1234",
        "https://t.me/s/DOC_POOL",
    ]


def test_report_final_plan_searches_once_even_without_consensus_change(monkeypatch):
    picked = [{"code": "000001", "fiscal_year": 2026, "fiscal_quarter": 2}]
    tables = {
        "analyses": [{
            **picked[0],
            "created_at": "2026-09-04T09:00:00+09:00",
            "payload": {"_heimdallr": {"analysis_stage": "filing"}},
        }],
        "earnings_disclosures": [{
            **picked[0], "doc_type": "periodic", "disclosed_at": "2026-09-04",
        }],
        "consensus_snapshots": [],
        "index_snapshots": [
            {"index_name": "KOSPI", "snap_date": day}
            for day in ("2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11")
        ],
    }
    monkeypatch.setattr(batch, "select_all", lambda table, *args, **kwargs: tables[table])

    pending, closures = batch.report_final_plan(picked)

    assert len(pending) == 1
    assert pending[0]["_analysis_stage"] == "report_final"
    assert pending[0]["_consensus_changed"] is False
    assert closures == []


def test_report_refresh_ignores_price_driven_per_change():
    """PER은 주가만 움직여도 바뀐다 — 리포트 변화나 유료 호출 근거가 아니다."""
    base = {
        "fiscal_year": 2026,
        "fiscal_quarter": 0,
        "np_est": 100,
        "fwd_per": 12,
        "source": "naver",
    }
    decision = report_refresh_decision(
        [
            {**base, "snapshot_at": "2026-09-04T08:00:00+09:00"},
            {**base, "fwd_per": 15, "snapshot_at": "2026-09-11T08:00:00+09:00"},
        ],
        ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"],
        filing_at="2026-09-04",
        year=2026,
        quarter=2,
        trading_days=5,
    )
    assert decision.ready and not decision.changed


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


def test_legacy_analysis_is_not_mass_refreshed_by_collection_timestamp(monkeypatch):
    """메타 보강일은 새 실적 이벤트가 아니다 — 레거시 전량 재결제를 막는다."""
    q = {
        "code": "000001",
        "fiscal_year": 2026,
        "fiscal_quarter": 2,
        "revenue": 100,
        "is_estimate": False,
        "updated_at": "2026-09-05T09:00:00+00:00",
        "delta_from_preliminary": None,
    }
    a = {
        "code": "000001",
        "fiscal_year": 2026,
        "fiscal_quarter": 2,
        "created_at": "2026-08-20T09:00:00+00:00",
        "payload": {"why_now": "기존 분석"},
    }
    tables = {"analyses": [a], "quarterly_fundamentals": [q], "disclosure_excerpts": []}
    monkeypatch.setattr(batch, "select_all", lambda table, *a, **k: tables[table])
    assert ("000001", 2026, 2) in batch.already_analyzed(refresh_finalized=True)


def test_same_failed_evidence_is_not_paid_again(monkeypatch):
    q = {
        "code": "000001",
        "fiscal_year": 2026,
        "fiscal_quarter": 2,
        "revenue": 100,
        "is_estimate": False,
    }
    evidence_hash = facts_hash([q], None)
    a = {
        "code": "000001",
        "fiscal_year": 2026,
        "fiscal_quarter": 2,
        "created_at": "2026-09-05T09:00:00+00:00",
        "payload": {
            "_heimdallr": {
                "last_attempt": {
                    "stage": "filing",
                    "evidence_hash": evidence_hash,
                    "status": "failed",
                }
            }
        },
    }
    tables = {"analyses": [a], "quarterly_fundamentals": [q], "disclosure_excerpts": []}
    monkeypatch.setattr(batch, "select_all", lambda table, *a, **k: tables[table])
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
    manual = (workflows / "llm_batch.yml").read_text(encoding="utf-8")
    assert "schedule:" not in manual
    assert "--notify-only" in manual
    poll = (workflows / "disclosure_poll.yml").read_text(encoding="utf-8")
    assert "--refresh-finalized --notify-only" in poll
    assert "vars.SEASON_MODE" not in poll
    assert 'cron: "*/30 0-14 * * *"' in poll
    assert "--report-final --notify-only" in daily
