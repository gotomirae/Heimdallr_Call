# PRD Ref: §13 (P0) · 부록 A
"""P0 스캐폴딩 회귀 테스트 — 외부 I/O 없이 돈다.

여기서 막는 것: schema.sql과 init.py의 테이블 목록이 조용히 어긋나는 것.
어긋나면 "적용 안 된 테이블"을 검증에서 통째로 빼먹고도 초록불이 뜬다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.config import constants as C
from src.db.init import ANON_READABLE, EXPECTED_TABLES
from src.utils.env import DirtyEnvError, MissingEnvError, optional_env, require_env

SCHEMA = Path(__file__).resolve().parents[1] / "src" / "db" / "schema.sql"


def _tables_in_schema() -> set[str]:
    text = SCHEMA.read_text(encoding="utf-8")
    return set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", text))


def test_schema_and_init_table_lists_match():
    assert _tables_in_schema() == set(EXPECTED_TABLES)


def test_every_table_is_rls_enabled():
    text = SCHEMA.read_text(encoding="utf-8")
    enabled = set(re.findall(r"ALTER TABLE\s+(\w+)\s+ENABLE ROW LEVEL SECURITY", text))
    assert enabled == set(EXPECTED_TABLES)


def test_cost_log_has_no_anon_policy():
    """비용 로그는 anon에게 열지 않는다."""
    text = SCHEMA.read_text(encoding="utf-8")
    policies = set(re.findall(r"CREATE POLICY \w+ ON (\w+)\n\s*FOR SELECT TO anon", text))
    assert "cost_log" not in policies
    assert policies == set(ANON_READABLE)


def test_schema_is_idempotent():
    """CREATE TABLE / CREATE INDEX는 전부 IF NOT EXISTS여야 한다."""
    text = SCHEMA.read_text(encoding="utf-8")
    for stmt in re.findall(r"^CREATE (?:TABLE|INDEX) .*$", text, flags=re.MULTILINE):
        assert "IF NOT EXISTS" in stmt, stmt


def test_score_weights_sum_to_100():
    assert sum(C.SCORE_WEIGHTS.values()) == 100
    assert sum(C.A_WEIGHTS.values()) == C.SCORE_WEIGHTS["A"]
    assert sum(C.B_WEIGHTS.values()) == C.SCORE_WEIGHTS["B"]
    assert sum(C.C_WEIGHTS.values()) == C.SCORE_WEIGHTS["C"]
    assert sum(C.D_WEIGHTS.values()) == C.SCORE_WEIGHTS["D"]
    assert sum(C.PRI_WEIGHTS.values()) == 100


def test_normalization_denominators_match_weights():
    """★ 정규화 규칙 (PRD §4.2). 여기가 어긋나면 커버리지 편향이 되살아난다."""
    a, b, c, d = (C.SCORE_WEIGHTS[k] for k in "ABCD")
    assert C.SCORE_DENOM_FLASH_WITH_CONSENSUS == a + b + c == 82
    assert C.SCORE_DENOM_FLASH_NO_CONSENSUS == a + b == 67
    assert C.SCORE_DENOM_FINAL_WITH_CONSENSUS == a + b + c + d == 100
    assert C.SCORE_DENOM_FINAL_NO_CONSENSUS == a + b + d == 85


def test_kis_whitelist_has_no_order_endpoint():
    """주문 API 호출 금지. 화이트리스트에 quotations/oauth 외에는 없어야 한다."""
    for path in C.KIS_ALLOWED_PATHS:
        assert "order" not in path.lower()
        assert path.startswith("/oauth2/") or "/quotations/" in path


def test_sonnet_price_is_flat():
    """날짜 기준 가격 전환 로직 금지 (traps.md T19). $2/$10이 정가다."""
    assert C.SONNET_INPUT_PER_MTOK == 2.0
    assert C.SONNET_OUTPUT_PER_MTOK == 10.0


def test_env_strips_whitespace(monkeypatch):
    monkeypatch.setenv("HEIMDALLR_TEST_VAL", "  abc123  ")
    assert require_env("HEIMDALLR_TEST_VAL") == "abc123"


def test_env_rejects_embedded_newline(monkeypatch):
    """조용히 자르지 않고 실패시킨다 (traps.md T9)."""
    monkeypatch.setenv("HEIMDALLR_TEST_VAL", "abc\ndef")
    with pytest.raises(DirtyEnvError):
        require_env("HEIMDALLR_TEST_VAL")


def test_env_empty_is_missing(monkeypatch):
    """빈 문자열은 '있다'가 아니라 '없다'로 취급한다."""
    monkeypatch.setenv("HEIMDALLR_TEST_VAL", "   ")
    assert optional_env("HEIMDALLR_TEST_VAL") is None
    with pytest.raises(MissingEnvError):
        require_env("HEIMDALLR_TEST_VAL")


def test_no_direct_os_environ_outside_env_module():
    """os.environ 직접 읽기 금지 — 창구는 src/utils/env.py 하나뿐이다."""
    src = Path(__file__).resolve().parents[1] / "src"
    offenders = [
        str(p.relative_to(src))
        for p in src.rglob("*.py")
        if p.name != "env.py" and "os.environ" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []
