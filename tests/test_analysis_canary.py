# PRD Ref: §7.4 · ADR 9 · traps.md T7, T84, T106
"""Provider canary 사전 방어 테스트. 외부 API와 DB를 호출하지 않는다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.analysis import run
from src.analysis.analyze import AnalysisInput, AnalysisResult
from src.analysis.canary import (
    CanaryExecutionError,
    CanaryPreflightError,
    CanaryProviderError,
    CanaryResult,
    build_canary_plan,
    run_canary,
)
from src.config.constants import ANALYSIS_MODEL
from src.llm.provider import LLMResponse, NormalizedUsage
from src.llm.request_snapshot import analysis_input_sha256, canonical_sha256
from src.utils.cost_guard import estimate_worst_case_cost_usd


ROOT = Path(__file__).resolve().parents[1]


def test_build_input_filters_every_table_by_code_at_server(monkeypatch):
    """단건 canary가 전체 테이블을 읽으면 호출 수와 데이터 범위를 보장할 수 없다."""
    calls: list[tuple[str, dict | None]] = []

    def fake_select_all(table, _columns="*", **kwargs):
        calls.append((table, kwargs.get("filters")))
        rows = {
            "krx_universe": [
                {
                    "code": "097230",
                    "name": "HJ중공업",
                    "board": "KOSPI",
                    "market_cap_krw": 500_000_000_000,
                }
            ],
            "quarterly_fundamentals": [
                {
                    "code": "097230",
                    "fiscal_year": 2026,
                    "fiscal_quarter": 2,
                    "np": 1_000_000_000,
                }
            ],
            "screen_results": [
                {
                    "code": "097230",
                    "fiscal_year": 2026,
                    "fiscal_quarter": 2,
                    "pri": 7.62,
                    "pri_detail": {"raw_sum": 4.95, "denominator": 65},
                }
            ],
            "consensus_snapshots": [],
            "price_snapshots": [],
            "disclosure_excerpts": [],
            "quarter_prices": [],
            "earnings_disclosures": [],
        }
        return rows[table]

    monkeypatch.setattr(run, "select_all", fake_select_all)
    result = run.build_input("097230", year=2026, quarter=2, allow_fetch=False)

    assert result.code == "097230"
    assert len(calls) == 9
    assert all(filters and filters.get("code") == "097230" for _, filters in calls)
    assert dict(calls)["screen_results"] == {
        "code": "097230",
        "fiscal_year": 2026,
        "fiscal_quarter": 2,
    }
    assert result.pri["pri"] == 7.62
    assert result.pri["raw_sum"] == 4.95


def test_build_input_excludes_quarters_after_requested_period(monkeypatch):
    """과거 replay에 이후 실적이 섞여도 에러가 없어 미래정보 누수가 된다(T112)."""
    def fake_select_all(table, _columns="*", **_kwargs):
        rows = {
            "krx_universe": [{"code": "097230", "name": "HJ중공업", "board": "KOSPI"}],
            "quarterly_fundamentals": [
                {"code": "097230", "fiscal_year": 2025, "fiscal_quarter": 2,
                 "revenue": 100, "op": 10},
                {"code": "097230", "fiscal_year": 2026, "fiscal_quarter": 1,
                 "revenue": 120, "op": 12},
                {"code": "097230", "fiscal_year": 2026, "fiscal_quarter": 2,
                 "revenue": 140, "op": 14},
                {"code": "097230", "fiscal_year": 2026, "fiscal_quarter": 3,
                 "revenue": 999, "op": 999},
            ],
            "screen_results": [],
            "consensus_snapshots": [],
            "price_snapshots": [],
            "disclosure_excerpts": [],
            "quarter_prices": [],
            "earnings_disclosures": [],
        }
        return rows[table]

    monkeypatch.setattr(run, "select_all", fake_select_all)
    result = run.build_input("097230", year=2026, quarter=2, allow_fetch=False)

    periods = [(row["fiscal_year"], row["fiscal_quarter"]) for row in result.quarters]
    assert periods == [(2025, 2), (2026, 1), (2026, 2)]
    assert all(row.get("revenue") != 999 for row in result.quarters)


def test_build_input_uses_latest_consensus_snapshot_regardless_of_api_order(monkeypatch):
    """이력 테이블의 첫 행을 쓰면 PostgREST 반환 순서에 따라 replay가 바뀐다."""
    def fake_select_all(table, _columns="*", **kwargs):
        filters = kwargs.get("filters") or {}
        rows = {
            "krx_universe": [{
                "code": "097230", "name": "HJ중공업", "board": "KOSPI",
                "market_cap_krw": 1_000_000_000_000,
            }],
            "quarterly_fundamentals": [
                {"code": "097230", "fiscal_year": 2025, "fiscal_quarter": 3,
                 "revenue": 100, "op": 10, "np": 10},
                {"code": "097230", "fiscal_year": 2025, "fiscal_quarter": 4,
                 "revenue": 100, "op": 10, "np": 10},
                {"code": "097230", "fiscal_year": 2026, "fiscal_quarter": 1,
                 "revenue": 100, "op": 10, "np": 10},
                {"code": "097230", "fiscal_year": 2026, "fiscal_quarter": 2,
                 "revenue": 100, "op": 10, "np": 10},
            ],
            "screen_results": [],
            "price_snapshots": [{
                "code": "097230", "snap_date": "2026-08-27",
                "market_cap_krw": 1_000_000_000_000,
            }],
            "disclosure_excerpts": [],
            "quarter_prices": [],
            "earnings_disclosures": [],
        }
        if table == "consensus_snapshots":
            if filters.get("fiscal_quarter") == 2:
                return [
                    {"code": "097230", "fiscal_year": 2026, "fiscal_quarter": 2,
                     "revenue_est": 111, "op_est": 11, "n_estimates": 3,
                     "snapshot_at": "2026-07-01T00:00:00+00:00"},
                    {"code": "097230", "fiscal_year": 2026, "fiscal_quarter": 2,
                     "revenue_est": 222, "op_est": 22, "n_estimates": 3,
                     "snapshot_at": "2026-08-01T00:00:00+00:00"},
                ]
            return [
                {"code": "097230", "fiscal_year": 2026, "fiscal_quarter": 0,
                 "np_est": 50_000_000_000, "n_estimates": 3,
                 "snapshot_at": "2026-08-01T00:00:00+00:00"},
                {"code": "097230", "fiscal_year": 2026, "fiscal_quarter": 0,
                 "np_est": 25_000_000_000, "n_estimates": 3,
                 "snapshot_at": "2026-07-01T00:00:00+00:00"},
            ]
        return rows[table]

    monkeypatch.setattr(run, "select_all", fake_select_all)

    result = run.build_input("097230", year=2026, quarter=2, allow_fetch=False)

    assert result.consensus["revenue_est"] == 222
    assert result.consensus["snapshot_at"] == "2026-08-01T00:00:00+00:00"
    assert result.valuation["per_forward"] == pytest.approx(10.0)


def test_select_all_applies_server_filters_before_every_page():
    from src.db.supabase_client import select_all

    seen: list[tuple[str, object]] = []
    executions = 0

    class _Query:
        def select(self, _columns):
            return self

        def eq(self, column, value):
            seen.append((column, value))
            return self

        def range(self, _start, _end):
            return self

        def execute(self):
            nonlocal executions
            executions += 1
            data = [{"code": "097230"}] if executions == 1 else []
            return type("Response", (), {"data": data})()

    client = type("Client", (), {"table": lambda self, name: _Query()})()
    rows = select_all(
        "quarterly_fundamentals",
        "code",
        client=client,
        page_size=1,
        filters={"code": "097230", "fiscal_year": 2026},
    )

    assert rows == [{"code": "097230"}]
    assert seen == [
        ("code", "097230"), ("fiscal_year", 2026),
        ("code", "097230"), ("fiscal_year", 2026),
    ]


def test_select_all_read_budget_stops_before_unapproved_next_http_request():
    from src.db.supabase_client import (
        PostgrestReadBudget,
        ReadBudgetExceeded,
        select_all,
    )

    executions = 0

    class Query:
        def select(self, _columns):
            return self

        def range(self, _start, _end):
            return self

        def execute(self):
            nonlocal executions
            executions += 1
            return type("Response", (), {"data": [{"code": "097230"}]})()

    client = type("Client", (), {"table": lambda self, _name: Query()})()
    budget = PostgrestReadBudget(max_requests=1)

    with pytest.raises(ReadBudgetExceeded, match="1회"):
        select_all(
            "quarterly_fundamentals",
            "code",
            client=client,
            page_size=1,
            read_budget=budget,
        )

    assert executions == 1
    assert budget.used_requests == 1


def test_excerpt_loader_does_not_swallow_read_budget_exhaustion(monkeypatch):
    from src.db.supabase_client import ReadBudgetExceeded

    monkeypatch.setattr(
        run,
        "select_all",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ReadBudgetExceeded("승인 GET 소진")
        ),
    )

    with pytest.raises(ReadBudgetExceeded, match="승인 GET 소진"):
        run.load_excerpt("097230", 2026, 2, allow_fetch=False)


def _fixture_payload() -> dict:
    fixture = json.loads(
        (ROOT / "tests/fixtures/llm_eval/representative_turnaround.json").read_text(
            encoding="utf-8"
        )
    )
    return fixture["cases"][0]["candidates"][0]["payload"]


def _fixture_input() -> AnalysisInput:
    fixture = json.loads(
        (ROOT / "tests/fixtures/llm_eval/representative_turnaround.json").read_text(
            encoding="utf-8"
        )
    )
    return AnalysisInput(**fixture["cases"][0]["input"])


class _Provider:
    name = "anthropic"

    def __init__(self, *, counted: int = 100):
        self.counted = counted
        self.count_calls = 0
        self.generate_calls = 0
        self.request = None

    def count_input_tokens(self, request):
        self.count_calls += 1
        self.request = request
        return self.counted

    def generate_structured(self, request):
        self.generate_calls += 1
        self.request = request
        payload = _fixture_payload()
        # 새 request는 사실 숫자 참조 계약을 강제한다. 이 Provider는 호출 횟수·비용
        # 경계 테스트용이므로 사실 필드에는 숫자를 직접 쓰지 않는다.
        payload["one_line_thesis"] = "실적 개선이 확인됐지만 지속성 검증이 필요하다."
        payload["why_now"] = "최근 공시와 분기 실적에서 개선 방향이 함께 확인됐다."
        payload["earnings_change"]["cause"] = "매출 확대와 수익성 회복이 겹쳤다."
        payload["earnings_change"]["effect"] = "영업 레버리지가 나타났다."
        payload["growth_engine"]["evidence"] = "수주잔고와 매출 흐름이 근거다."
        payload["acceleration_quality"]["base_effect_assessment"] = (
            "기저효과만으로 설명하기 어렵다."
        )
        payload["price_position"]["reason"] = "실적 대비 주가 반영은 제한적이다."
        payload["price_position"]["price_history"] = "주가는 조정 뒤 회복 초입이다."
        payload["price_position"]["priced_in"] = ["단기 실적 개선"]
        payload["price_position"]["not_priced_in"] = ["중기 성장 지속성"]
        return LLMResponse(
            provider=self.name,
            model=request.model,
            payload=payload,
            usage=NormalizedUsage(input_tokens=100, output_tokens=100),
            stop_reason="completed",
            response_id="resp_canary",
        )


def _approved_plan_sha(
    data: AnalysisInput, *, max_output_tokens: int = 1_000
) -> str:
    return build_canary_plan(
        data,
        model=ANALYSIS_MODEL,
        max_output_tokens=max_output_tokens,
    ).plan_sha256


def test_canary_plan_is_offline_and_binds_request_pricing_and_caps():
    data = AnalysisInput(code="097230", name="HJ중공업", board="KOSPI")
    plan = build_canary_plan(
        data,
        model=ANALYSIS_MODEL,
        max_output_tokens=1_000,
    )

    assert plan.payload["external_calls_executed"] == 0
    assert plan.payload["version"] == 2
    assert plan.payload["provider"] == "anthropic"
    assert plan.payload["measurements"]["counted_input_tokens"] is None
    assert "provider token-count endpoint" in plan.payload["measurements"]["note"]
    assert plan.payload["measurements"]["user_message_chars"] > 0
    assert plan.payload["request_sha256"] == canonical_sha256(
        plan.payload["request_snapshot"]
    )
    assert plan.payload["pricing_per_mtok"]["output"] == 10.0
    assert plan.payload["limits"]["max_output_tokens"] == 1_000
    assert plan.plan_sha256 == canonical_sha256(plan.payload)


def test_unapproved_or_drifted_plan_blocks_before_token_count():
    provider = _Provider()
    data = AnalysisInput(code="097230", name="HJ중공업", board="KOSPI")

    with pytest.raises(CanaryPreflightError, match="승인 plan_sha256 불일치"):
        run_canary(
            data,
            provider=provider,
            model=ANALYSIS_MODEL,
            max_output_tokens=1_000,
            approved_plan_sha256="not-the-current-plan",
        )

    assert (provider.count_calls, provider.generate_calls) == (0, 0)


def test_provider_mismatch_blocks_before_token_count():
    provider = _Provider()
    provider.name = "openai"
    data = AnalysisInput(code="097230", name="HJ중공업", board="KOSPI")
    plan = build_canary_plan(data, model=ANALYSIS_MODEL, max_output_tokens=1_000)

    with pytest.raises(CanaryPreflightError, match="Provider.*불일치"):
        run_canary(
            data,
            provider=provider,
            model=ANALYSIS_MODEL,
            max_output_tokens=1_000,
            approved_plan_sha256=plan.plan_sha256,
        )

    assert (provider.count_calls, provider.generate_calls) == (0, 0)


def test_canary_counts_once_generates_once_and_never_records_db_cost(monkeypatch):
    provider = _Provider()
    data = _fixture_input()
    monkeypatch.setattr(
        "src.utils.cost_guard.record_usage",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("DB 비용 로그를 쓰면 안 된다")),
    )

    result = run_canary(
        data,
        provider=provider,
        model=ANALYSIS_MODEL,
        max_output_tokens=1_000,
        approved_plan_sha256=_approved_plan_sha(data),
    )

    assert (provider.count_calls, provider.generate_calls) == (1, 1)
    assert provider.request.max_output_tokens == 1_000
    assert provider.request.effort == "low"
    assert result.response_id == "resp_canary"
    assert result.analysis.cost_usd == pytest.approx(0.0012)
    assert result.request_snapshot["request"]["user_message"] == provider.request.user_message
    assert result.request_sha256 == canonical_sha256(result.request_snapshot)
    assert result.input_sha256 == analysis_input_sha256(
        data
    )
    assert result.plan_sha256 == _approved_plan_sha(data)


def test_canary_blocks_expensive_request_before_generation():
    provider = _Provider()
    data = AnalysisInput(code="097230", name="HJ중공업", board="KOSPI")

    with pytest.raises(CanaryPreflightError, match="계획 최악비용"):
        run_canary(
            data,
            provider=provider,
            model=ANALYSIS_MODEL,
            max_output_tokens=20_000,
            approved_plan_sha256="not-reached",
        )

    assert (provider.count_calls, provider.generate_calls) == (0, 0)


def test_paid_canary_failure_preserves_usage_cost_and_payload():
    provider = _Provider()
    data = AnalysisInput(code="097230", name="HJ중공업", board="KOSPI")

    def invalid(_request):
        provider.generate_calls += 1
        return LLMResponse(
            provider=provider.name,
            model=ANALYSIS_MODEL,
            payload={"one_line_thesis": "불완전"},
            usage=NormalizedUsage(input_tokens=100, output_tokens=50),
            stop_reason="completed",
            response_id="resp_failed",
        )

    provider.generate_structured = invalid
    with pytest.raises(CanaryExecutionError) as raised:
        run_canary(
            data,
            provider=provider,
            model=ANALYSIS_MODEL,
            max_output_tokens=1_000,
            approved_plan_sha256=_approved_plan_sha(data),
        )

    failure = raised.value.failure
    assert failure.response_id == "resp_failed"
    assert failure.actual_cost_usd == pytest.approx(0.0007)
    assert failure.usage == NormalizedUsage(input_tokens=100, output_tokens=50)
    assert failure.payload == {"one_line_thesis": "불완전"}
    assert failure.request_sha256 == canonical_sha256(failure.request_snapshot)
    assert failure.input_sha256
    assert failure.plan_sha256 == _approved_plan_sha(data)


def test_paid_numeric_grounding_failure_preserves_cost_and_raw_payload():
    provider = _Provider()
    data = AnalysisInput(code="097230", name="HJ중공업", board="KOSPI")
    raw_payload = {"why_now": "공시상 수리선 매출은 267억원이다."}

    def converted_unit(_request):
        provider.generate_calls += 1
        return LLMResponse(
            provider=provider.name,
            model=ANALYSIS_MODEL,
            payload=raw_payload,
            usage=NormalizedUsage(input_tokens=100, output_tokens=50),
            stop_reason="completed",
            response_id="resp_grounding_failed",
        )

    provider.generate_structured = converted_unit
    with pytest.raises(CanaryExecutionError, match="입력에 없는 사실 숫자") as raised:
        run_canary(
            data,
            provider=provider,
            model=ANALYSIS_MODEL,
            max_output_tokens=1_000,
            approved_plan_sha256=_approved_plan_sha(data),
        )

    failure = raised.value.failure
    assert failure.response_id == "resp_grounding_failed"
    assert failure.actual_cost_usd == pytest.approx(0.0007)
    assert failure.payload == raw_payload
    assert "267억" in failure.error


def test_provider_http_error_preserves_completed_preflight():
    provider = _Provider()
    data = AnalysisInput(code="097230", name="HJ중공업", board="KOSPI")

    def quota_error(_request):
        provider.generate_calls += 1
        raise RuntimeError("credit_balance_exhausted")

    provider.generate_structured = quota_error
    with pytest.raises(CanaryProviderError) as raised:
        run_canary(
            data,
            provider=provider,
            model=ANALYSIS_MODEL,
            max_output_tokens=1_000,
            approved_plan_sha256=_approved_plan_sha(data),
        )

    assert raised.value.counted_input_tokens == 100
    assert raised.value.worst_case_cost_usd > 0
    assert raised.value.provider_error_type == "RuntimeError"
    assert raised.value.request_sha256 == canonical_sha256(
        raised.value.request_snapshot
    )
    assert raised.value.input_sha256
    assert raised.value.plan_sha256 == _approved_plan_sha(data)


def test_worst_case_cost_uses_cache_write_when_it_is_most_expensive():
    # Sonnet: input $2/M, cache-write $2.5/M, output $10/M.
    cost = estimate_worst_case_cost_usd(
        ANALYSIS_MODEL,
        input_tokens=16_000,
        max_output_tokens=9_100,
    )
    assert cost == pytest.approx(0.131)


def test_prepare_replay_refuses_missing_excerpt_without_dart_fallback(monkeypatch, tmp_path):
    from src.analysis import canary_run

    monkeypatch.setattr(
        canary_run,
        "build_input",
        lambda *a, **k: AnalysisInput(
            code="097230", name="HJ중공업", board="KOSPI",
            quarters=[{"fiscal_year": 2026, "fiscal_quarter": 2}],
            excerpt=None,
            as_of="2026-08-24",
        ),
    )

    with pytest.raises(SystemExit, match="excerpt"):
        canary_run.prepare_replay("097230", 2026, 2, tmp_path / "replay.json")
    assert not (tmp_path / "replay.json").exists()


def test_load_replay_refuses_missing_final_pri(tmp_path):
    from src.analysis.canary_run import load_replay

    path = tmp_path / "stale.json"
    path.write_text(
        json.dumps({
            "input": {
                "code": "097230",
                "name": "HJ중공업",
                "board": "KOSPI",
                "pri": {"raw_sum": 4.95, "denominator": 65},
            }
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="pri.pri"):
        load_replay(path)


def _write_canary_replay(path: Path) -> AnalysisInput:
    data = AnalysisInput(
        code="097230",
        name="HJ중공업",
        board="KOSPI",
        pri={"pri": 7.62},
    )
    path.write_text(
        json.dumps({"input": data.__dict__}, ensure_ascii=False),
        encoding="utf-8",
    )
    return data


def test_canary_cli_writes_request_snapshot_on_success(monkeypatch, tmp_path):
    from src.analysis import canary_run

    replay = tmp_path / "replay.json"
    output = tmp_path / "result.json"
    data = _write_canary_replay(replay)
    snapshot = {"version": 1, "request": {"model": ANALYSIS_MODEL}}
    request_hash = canonical_sha256(snapshot)
    monkeypatch.setattr(
        canary_run,
        "run_canary",
        lambda *_a, **_k: CanaryResult(
            analysis=AnalysisResult(
                code=data.code,
                fiscal_year=None,
                fiscal_quarter=None,
                payload=_fixture_payload(),
                model=ANALYSIS_MODEL,
                cost_usd=0.01,
                input_tokens=1,
                cache_read_tokens=2,
                cache_write_tokens=3,
                output_tokens=4,
            ),
            counted_input_tokens=10,
            worst_case_cost_usd=0.02,
            response_id="resp_saved",
            request_snapshot=snapshot,
            request_sha256=request_hash,
            input_sha256=analysis_input_sha256(data),
            plan_sha256="approved-plan",
        ),
    )

    canary_run.execute_canary(
        replay,
        output,
        model=ANALYSIS_MODEL,
        approved_plan_sha256="approved-plan",
    )

    saved = json.loads(output.read_text(encoding="utf-8"))["candidate"]
    assert saved["request_snapshot"] == snapshot
    assert saved["request_sha256"] == request_hash
    assert saved["input_sha256"] == analysis_input_sha256(data)
    assert saved["plan_sha256"] == "approved-plan"


def test_canary_cli_records_selected_provider(monkeypatch, tmp_path):
    from src.analysis import canary_run

    replay = tmp_path / "replay.json"
    output = tmp_path / "result.json"
    data = _write_canary_replay(replay)
    snapshot = {"version": 1, "request": {"model": ANALYSIS_MODEL}}

    monkeypatch.setattr(
        canary_run,
        "run_canary",
        lambda *_a, **_k: CanaryResult(
            analysis=AnalysisResult(
                code=data.code,
                fiscal_year=None,
                fiscal_quarter=None,
                payload=_fixture_payload(),
                model=ANALYSIS_MODEL,
                cost_usd=0.01,
                input_tokens=1,
                cache_read_tokens=2,
                cache_write_tokens=3,
                output_tokens=4,
            ),
            counted_input_tokens=10,
            worst_case_cost_usd=0.02,
            response_id="msg_saved",
            request_snapshot=snapshot,
            request_sha256=canonical_sha256(snapshot),
            input_sha256=analysis_input_sha256(data),
            plan_sha256="approved-plan",
        ),
    )

    class AnthropicStub:
        name = "anthropic"

    canary_run.execute_canary(
        replay,
        output,
        model=ANALYSIS_MODEL,
        approved_plan_sha256="approved-plan",
        provider=AnthropicStub(),
    )

    saved = json.loads(output.read_text(encoding="utf-8"))["candidate"]
    assert saved["provider"] == "anthropic"


def test_canary_cli_writes_request_snapshot_on_provider_error(monkeypatch, tmp_path):
    from src.analysis import canary_run

    replay = tmp_path / "replay.json"
    output = tmp_path / "result.json"
    data = _write_canary_replay(replay)
    snapshot = {"version": 1, "request": {"model": ANALYSIS_MODEL}}
    request_hash = canonical_sha256(snapshot)
    error = CanaryProviderError(
        code=data.code,
        model=ANALYSIS_MODEL,
        counted_input_tokens=10,
        worst_case_cost_usd=0.02,
        request_snapshot=snapshot,
        request_sha256=request_hash,
        input_sha256=analysis_input_sha256(data),
        plan_sha256="approved-plan",
        error=RuntimeError("provider failed"),
    )

    def raise_error(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(canary_run, "run_canary", raise_error)
    with pytest.raises(CanaryProviderError):
        canary_run.execute_canary(
            replay,
            output,
            model=ANALYSIS_MODEL,
            approved_plan_sha256="approved-plan",
        )

    saved = json.loads(output.read_text(encoding="utf-8"))["candidate"]
    assert saved["request_snapshot"] == snapshot
    assert saved["request_sha256"] == request_hash
    assert saved["input_sha256"] == analysis_input_sha256(data)
    assert saved["plan_sha256"] == "approved-plan"


def test_canary_cli_plan_writes_exact_offline_approval_contract(tmp_path):
    from src.analysis import canary_run

    replay = tmp_path / "replay.json"
    output = tmp_path / "plan.json"
    data = _write_canary_replay(replay)

    plan = canary_run.write_canary_plan(replay, output, model=ANALYSIS_MODEL)
    saved = json.loads(output.read_text(encoding="utf-8"))

    assert saved["status"] == "planned"
    assert saved["external_calls_executed"] == 0
    assert saved["plan_sha256"] == plan.plan_sha256
    assert canonical_sha256(saved["plan"]) == plan.plan_sha256
    assert saved["plan"]["input_sha256"] == analysis_input_sha256(data)


def test_canary_plan_can_override_effort_without_changing_operating_default():
    data = AnalysisInput(code="004000", name="롯데정밀화학", board="KOSPI")

    baseline = build_canary_plan(data, model=ANALYSIS_MODEL)
    medium = build_canary_plan(data, model=ANALYSIS_MODEL, effort="medium")

    assert baseline.request.effort == "low"
    assert medium.request.effort == "medium"
    assert medium.payload["request_snapshot"]["request"]["effort"] == "medium"
    assert medium.plan_sha256 != baseline.plan_sha256
