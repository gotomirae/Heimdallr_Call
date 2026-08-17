# PRD Ref: §5.1(L3), §4.2(C축) · ADR 2 · traps.md T17, T30
"""P5 컨센서스 테스트. 합성 HTML로 돌아 외부 I/O가 없다."""

from __future__ import annotations

import pytest

from src.collectors.consensus import ConsensusSnapshot, fetch_quarterly_estimates


class _FakeResponse:
    def __init__(self, html: str):
        self.content = html.encode("utf-8")
        self.headers = {"content-type": "text/html;charset=UTF-8"}


def _analysis_html(header_cells: list[str], rows: dict[str, list[str]]) -> str:
    header = "".join(f"<th>{c}</th>" for c in header_cells)
    body = ""
    for label, values in rows.items():
        cells = "".join(f"<td>{v}</td>" for v in values)
        body += f"<tr><th>{label}</th>{cells}</tr>"
    return f"""<html><body>
      <div class="section cop_analysis"><table>
        <tr><th>주요재무정보</th><th>최근 연간 실적</th><th>최근 분기 실적</th></tr>
        <tr>{header}</tr>
        {body}
      </table></div>
    </body></html>"""


HEADER = [
    "2023.12", "2024.12", "2025.12", "2026.12 (E)",       # 연간 (마지막이 (E))
    "2025.03", "2025.06", "2025.09", "2025.12", "2026.03", "2026.06 (E)",  # 분기
]
ROWS = {
    "매출액": ["2,589,355", "3,008,709", "3,336,059", "7,386,252",
             "791,405", "745,663", "860,617", "938,374", "1,338,734", "1,738,644"],
    "영업이익": ["65,670", "327,260", "436,010", "3,909,276",
              "66,853", "46,761", "121,661", "200,737", "572,328", "850,494"],
    "당기순이익": ["154,871", "344,514", "452,068", "3,260,750",
               "82,229", "51,164", "122,257", "196,417", "472,253", "734,933"],
    "EPS(원)": ["2,131", "4,950", "6,500", "48,000",
               "1,100", "800", "1,700", "2,900", "7,000", "10,625"],
}


@pytest.fixture()
def patched(monkeypatch):
    from src.collectors import consensus as mod

    monkeypatch.setattr(mod, "http_get", lambda *a, **k: _FakeResponse(_analysis_html(HEADER, ROWS)))
    return mod


def test_only_estimate_quarter_is_returned(patched):
    """확정 분기는 컨센서스가 아니다. `(E)`가 붙은 분기만 뽑는다."""
    snaps = fetch_quarterly_estimates("005930")
    assert len(snaps) == 1
    assert (snaps[0].fiscal_year, snaps[0].fiscal_quarter) == (2026, 2)


def test_annual_estimate_column_is_excluded(patched):
    """연간 (E) 컬럼(2026.12)을 4분기 컨센서스로 착각하면 안 된다."""
    snaps = fetch_quarterly_estimates("005930")
    assert all(not (s.fiscal_year == 2026 and s.fiscal_quarter == 4) for s in snaps)


def test_units_are_converted_from_eok_to_won(patched):
    """네이버 기업실적분석 표는 **억원** 단위다. EPS만 원이다."""
    snap = fetch_quarterly_estimates("005930")[0]
    assert snap.revenue_est == 1_738_644 * 100_000_000
    assert snap.op_est == 850_494 * 100_000_000
    assert snap.np_est == 734_933 * 100_000_000
    assert snap.eps_est == 10_625.0


# 실측 변형: 헤더 앞에 **빈 칸**이 있고 연간 컬럼이 **3개**인 종목이 있다
# (한화비전 489790 · SK이터닉스 475150). 이 변형에서 열이 한 칸 밀리면
# **연간 추정치가 4Q 분기 컨센서스로 저장된다** — 실측 4배 오차(20,334억 vs 5,012억).
HEADER_3ANNUAL = [
    "", "2024.12", "2025.12", "2026.12 (E)",
    "2025.03", "2025.06", "2025.09", "2025.12", "2026.03", "2026.06 (E)",
]
ROWS_3ANNUAL = {
    "매출액": ["", "18,000", "19,000", "20,334",
             "4,000", "4,500", "4,800", "5,000", "4,900", "5,012"],
    "영업이익": ["", "1,000", "1,100", "1,200",
              "250", "260", "270", "280", "290", "300"],
}


def test_leading_blank_header_does_not_shift_columns(monkeypatch):
    """★ 실제로 있었던 데이터 오염(2026-08-13).

    헤더 첫 칸이 비어 있고 연간이 3개인 변형에서 열이 밀려
    **연간 추정치(20,334억)가 2026.4Q 분기 컨센서스로 저장**됐다.
    실제 2026.2Q는 5,012억이라 4배 오차다. 서프라이즈 계산이 통째로 뒤집힌다.
    """
    from src.collectors import consensus as mod

    monkeypatch.setattr(
        mod, "http_get",
        lambda *a, **k: _FakeResponse(_analysis_html(HEADER_3ANNUAL, ROWS_3ANNUAL)),
    )
    snaps = fetch_quarterly_estimates("489790")
    assert len(snaps) == 1
    assert (snaps[0].fiscal_year, snaps[0].fiscal_quarter) == (2026, 2)
    assert snaps[0].revenue_est == 5_012 * 100_000_000  # 20,334억이 아니다


def test_missing_section_returns_empty(monkeypatch):
    """파싱 실패는 예외가 아니라 정상 케이스다 — 파이프라인을 죽이지 않는다."""
    from src.collectors import consensus as mod

    monkeypatch.setattr(mod, "http_get", lambda *a, **k: _FakeResponse("<html><body/></html>"))
    assert fetch_quarterly_estimates("000000") == []


# ═══════════════════════════════════════════════════════════════════
# ★ MIN_ESTIMATES — 1곳은 컨센서스가 아니다 (PRD §4.2)
# ═══════════════════════════════════════════════════════════════════
def test_single_estimator_is_not_consensus():
    snap = ConsensusSnapshot("A", 2026, 2, revenue_est=100, n_estimates=1)
    assert snap.is_usable is False


def test_two_estimators_is_consensus():
    snap = ConsensusSnapshot("A", 2026, 2, revenue_est=100, n_estimates=2)
    assert snap.is_usable is True


def test_unknown_estimator_count_is_not_consensus():
    """★ 모르는 것을 '있다'로 처리하면 커버리지 없는 종목에 가짜 C축이 붙는다."""
    snap = ConsensusSnapshot("A", 2026, 2, revenue_est=100, n_estimates=None)
    assert snap.is_usable is False


def test_no_values_is_not_consensus():
    snap = ConsensusSnapshot("A", 2026, 2, n_estimates=10)
    assert snap.is_usable is False


def test_to_db_shape():
    snap = ConsensusSnapshot("005930", 2026, 2, revenue_est=1, op_est=2, n_estimates=24)
    row = snap.to_db()
    assert row["code"] == "005930"
    assert row["fiscal_year"] == 2026 and row["fiscal_quarter"] == 2
    assert row["n_estimates"] == 24
    assert row["source"] == "naver"
