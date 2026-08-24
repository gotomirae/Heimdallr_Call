# PRD Ref: §5, §7.1 · traps.md T93, T99
"""발췌가 **어느 분기 것인지** 끝까지 지켜지는지. 외부 I/O 없이 돈다.

T99의 뿌리는 한 줄이었다 — `earnings_disclosures`에 기간을 안 채웠더니
발췌도 기간 없이 저장됐고, 읽는 쪽은 "가장 최근 것"으로 조용히 물러섰다.
공시 1,576행 전부가 NULL이었는데 **에러도 경고도 없었다.**

여기서 막는 것은 세 가지다.
  1. 공시 이름에서 기간을 뽑아내는가 (`period_of`)
  2. 뽑은 기간이 저장 payload에 실리는가 (`_save`)
  3. 다른 분기 발췌를 쓸 때 **모델에게 그 사실을 알리는가** (`load_excerpt`)
"""

from __future__ import annotations

import src.analysis.run as run
from src.collectors.dart_disclosure import Disclosure, period_of

# ── 1. 저장 payload에 기간이 실리는가 ────────────────────────────────────


def _disclosure(report_nm: str) -> Disclosure:
    return Disclosure(
        rcept_no="20260813000123",
        code="005930",
        corp_code="00126380",
        corp_name="삼성전자",
        report_nm=report_nm,
        doc_type="periodic",
        disclosed_at="20260813",
    )


def test_save_payload_carries_the_period(monkeypatch):
    """★★ 여기가 T99의 발화점이다 — 이 두 칸이 비면 아래 전부가 조용히 틀린다."""
    from src.collectors import replay

    captured: list[list[dict]] = []

    class _Table:
        def upsert(self, payload, **_kw):
            captured.append(payload)
            return self

        def execute(self):
            return None

    class _DB:
        def table(self, _name):
            return _Table()

    monkeypatch.setattr(replay, "get_client", lambda: _DB())
    replay._save([_disclosure("반기보고서 (2026.06)")])

    row = captured[0][0]
    assert row["fiscal_year"] == 2026
    assert row["fiscal_quarter"] == 2


def test_save_payload_leaves_provisional_period_empty(monkeypatch):
    """잠정실적 공정공시에는 기간이 이름에 없다 — None이 **정상**이다."""
    from src.collectors import replay

    captured: list[list[dict]] = []

    class _Table:
        def upsert(self, payload, **_kw):
            captured.append(payload)
            return self

        def execute(self):
            return None

    monkeypatch.setattr(
        replay, "get_client", lambda: type("D", (), {"table": lambda s, n: _Table()})()
    )
    replay._save([_disclosure("연결재무제표기준영업(잠정)실적(공정공시)")])

    row = captured[0][0]
    assert row["fiscal_year"] is None
    assert row["fiscal_quarter"] is None


# ── 2. 읽는 쪽이 출처 분기를 밝히는가 ────────────────────────────────────

_SECTIONS = {"매출 및 수주상황": "수주잔고 18.5억원"}


def _stub_rows(monkeypatch, rows: list[dict]) -> None:
    monkeypatch.setattr(run, "select_all", lambda *a, **k: rows)


def test_same_quarter_excerpt_is_labelled_with_its_quarter(monkeypatch):
    _stub_rows(monkeypatch, [{
        "rcept_no": "20260813000001", "code": "005930",
        "fiscal_year": 2026, "fiscal_quarter": 2, "sections": _SECTIONS,
    }])
    out = run.load_excerpt("005930", 2026, 2)
    assert "2026년 2분기 정기보고서" in out
    assert "이 아니다" not in out          # 같은 분기다 — 경고를 붙이면 안 된다
    assert "수주잔고 18.5억원" in out


def test_other_quarter_excerpt_warns_the_model(monkeypatch):
    """★★ 라벨이 없으면 모델은 **지난 분기 사실을 이번 분기 사건으로 쓴다**(T93 모양).

    분기가 넘어간 직후에는 이번 분기 발췌가 아직 없어 **항상** 이 경로를 탄다.
    """
    _stub_rows(monkeypatch, [{
        "rcept_no": "20260813000001", "code": "005930",
        "fiscal_year": 2026, "fiscal_quarter": 2, "sections": _SECTIONS,
    }])
    out = run.load_excerpt("005930", 2026, 3)
    assert "2026년 2분기 정기보고서" in out
    assert "2026년 3분기 것이 아니다" in out
    assert "이번 분기 사건으로 쓰지 마라" in out


def test_unknown_quarter_excerpt_says_so(monkeypatch):
    """기간을 모르는 옛 행(T99 이전에 저장된 453행)도 침묵하지 않는다."""
    _stub_rows(monkeypatch, [{
        "rcept_no": "20260813000001", "code": "005930",
        "fiscal_year": None, "fiscal_quarter": None, "sections": _SECTIONS,
    }])
    out = run.load_excerpt("005930", 2026, 2)
    assert "기준 분기 미상" in out


def test_fallback_is_deterministic_when_quarters_are_missing(monkeypatch):
    """★ `(0, 0)`으로 뭉개진 행들 사이에서도 **항상 같은 답**이 나와야 한다.

    무작위로 골라 두면 같은 종목을 재분석할 때마다 다른 원문이 실려
    "왜 결과가 바뀌지"를 영영 못 쫓는다.
    """
    rows = [
        {"rcept_no": "20260401000001", "code": "005930",
         "fiscal_year": None, "fiscal_quarter": None,
         "sections": {"주요제품": "옛 보고서"}},
        {"rcept_no": "20260813000002", "code": "005930",
         "fiscal_year": None, "fiscal_quarter": None,
         "sections": {"주요제품": "새 보고서"}},
    ]
    _stub_rows(monkeypatch, rows)
    first = run.load_excerpt("005930", 2026, 2)
    _stub_rows(monkeypatch, list(reversed(rows)))
    second = run.load_excerpt("005930", 2026, 2)

    assert first == second
    assert "새 보고서" in first          # 접수번호가 큰 쪽 = 나중 공시


def test_no_rows_gives_none_not_a_fake_label(monkeypatch):
    """발췌가 없으면 **없다고 해야 한다** — 빈 라벨만 붙여 보내면 안 된다."""
    _stub_rows(monkeypatch, [])
    assert run.load_excerpt("005930", 2026, 2) is None


def test_empty_sections_give_none(monkeypatch):
    _stub_rows(monkeypatch, [{
        "rcept_no": "20260813000001", "code": "005930",
        "fiscal_year": 2026, "fiscal_quarter": 2, "sections": {},
    }])
    assert run.load_excerpt("005930", 2026, 2) is None


# ── 3. 파서와 저장·읽기가 같은 규칙을 쓰는가 ─────────────────────────────


def test_writer_and_reader_agree_on_the_same_report_name():
    """저장이 뽑은 기간과 읽기가 기대하는 기간이 **같은 함수**에서 나와야 한다.

    T99 이전에는 저장 쪽이 아예 안 채웠고, 읽는 쪽만 그 칸을 비교했다 —
    양쪽이 서로 다른 전제를 갖고도 아무도 몰랐다.
    """
    assert period_of("반기보고서 (2026.06)") == (2026, 2)
    assert period_of("[기재정정]반기보고서 (2026.06)") == (2026, 2)
