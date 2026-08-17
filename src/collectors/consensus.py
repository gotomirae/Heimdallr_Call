# PRD Ref: §5.1(L3), §6(consensus_snapshots), §4.2(C축) · traps.md T17, T30
"""분기 컨센서스 **사전** 스냅샷.

★ 존재 이유(T17): 분기 컨센서스는 `(E)` 표기로 나오는데 실적이 발표되면
  실적치로 덮여 사라진다. **발표 후에 조회하면 이미 늦다.**
  시즌 직전부터 주 1회 스냅샷해 쌓아야 C축(서프라이즈)이 성립한다.

★ 소스 (2026-08-13 실측으로 확정)
  PRD §5.1이 1·2순위로 지정한 `comp.fnguide.com/SVO2/ASP/SVD_Main.asp` ·
  `SVD_Consensus.asp`는 **더 이상 존재하지 않는다** — "페이지가 없습니다.
  신버전 바로가기"만 돌아온다(1,829바이트). 아래로 대체했다.

  1) 추정치  : finance.naver.com `item/main.naver` 기업실적분석 표의 `(E)` 분기 컬럼
               — 서버 렌더링 HTML이라 안정적이다. 단위 **억원**.
  2) 추정기관수: navercomp.wisereport.co.kr `c1010001.aspx`의 '추정기관수'

★ 실패는 예외가 아니라 **정상 케이스**다. 코스닥의 약 60%는 커버리지가 없다.
  None을 돌려주고 파이프라인을 죽이지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from src.config.constants import MIN_ESTIMATES
from src.utils.http import decode_html, http_get

NAVER_MAIN_URL = "https://finance.naver.com/item/main.naver"
WISEREPORT_URL = "https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx"

REQUEST_INTERVAL_SEC = 1.0  # 스크래핑 예의 — 반드시 지킨다

#: 기업실적분석 표의 행 라벨 → 내부 필드
_ROW_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue_est": ("매출액",),
    "op_est": ("영업이익",),
    "np_est": ("당기순이익",),
    "eps_est": ("EPS(원)", "EPS"),
}

_PERIOD_RE = re.compile(r"(\d{4})[./](\d{2})")
_ESTIMATE_MARK = "(E)"
#: 억원 → 원. 네이버 기업실적분석 표는 억원 고정이다(EPS만 원).
_EOK = 100_000_000


@dataclass
class ConsensusSnapshot:
    code: str
    fiscal_year: int
    fiscal_quarter: int
    revenue_est: int | None = None
    op_est: int | None = None
    np_est: int | None = None
    eps_est: float | None = None
    n_estimates: int | None = None
    source: str = "naver"

    @property
    def is_usable(self) -> bool:
        """추정기관 2곳 미만은 컨센서스로 인정하지 않는다 (PRD §4.2).

        `n_estimates`를 못 읽었으면 **인정하지 않는다** — 모르는 것을
        '있다'로 처리하면 커버리지 없는 종목에 가짜 C축이 붙는다.
        """
        return (
            self.n_estimates is not None
            and self.n_estimates >= MIN_ESTIMATES
            and (self.revenue_est is not None or self.op_est is not None)
        )

    def to_db(self) -> dict:
        return {
            "code": self.code,
            "fiscal_year": self.fiscal_year,
            "fiscal_quarter": self.fiscal_quarter,
            "revenue_est": self.revenue_est,
            "op_est": self.op_est,
            "np_est": self.np_est,
            "eps_est": self.eps_est,
            "n_estimates": self.n_estimates,
            "source": self.source,
        }


def _to_number(text: str) -> float | None:
    cleaned = text.replace(",", "").strip()
    if not cleaned or cleaned in ("-", "N/A"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def fetch_n_estimates(code: str) -> int | None:
    """추정기관수. 못 읽으면 None (0이 아니다)."""
    try:
        resp = http_get(WISEREPORT_URL, params={"cmp_cd": code, "cn": ""}, timeout=40.0)
        text = BeautifulSoup(decode_html(resp), "html.parser").get_text(" ", strip=True)
    except Exception:
        return None
    # '투자의견 목표주가 (원) EPS (원) PER (배) 추정기관수  4.04 491,875 47,821 5.34 24'
    index = text.find("추정기관수")
    if index < 0:
        return None
    numbers = re.findall(r"[\d,]+(?:\.\d+)?", text[index : index + 200])
    if len(numbers) < 5:
        return None
    try:
        return int(float(numbers[4].replace(",", "")))
    except ValueError:
        return None


def fetch_quarterly_estimates(code: str) -> list[ConsensusSnapshot]:
    """기업실적분석 표에서 `(E)`가 붙은 **분기** 컬럼만 뽑는다.

    연간 컬럼(2026.12 (E))도 (E)가 붙지만 분기가 아니므로 버린다 —
    표는 왼쪽이 연간, 오른쪽이 분기다. 헤더의 기간 개수로 구분한다.
    """
    resp = http_get(NAVER_MAIN_URL, params={"code": code}, timeout=40.0)
    soup = BeautifulSoup(decode_html(resp), "html.parser")

    section = soup.find("div", class_="section cop_analysis")
    table = section.find("table") if section else None
    if table is None:
        return []

    rows = table.find_all("tr")
    if len(rows) < 3:
        return []

    # 헤더: ['2023.12','2024.12','2025.12','2026.12 (E)','2025.03', ... '2026.06 (E)']
    # ★ 기간 패턴이 있는 칸만 모은다. 행마다 앞에 라벨 칸이 있을 수도, 없을 수도 있어
    #   위치로 세면 한 칸씩 밀린다(밀리면 **다른 분기 값을 컨센서스로 저장**한다).
    periods: list[tuple[int, int, bool]] = []
    for cell in rows[1].find_all(["th", "td"]):
        text = cell.get_text(" ", strip=True)
        match = _PERIOD_RE.search(text)
        if match is None:
            continue
        year, month = int(match.group(1)), int(match.group(2))
        periods.append((year, (month - 1) // 3 + 1, _ESTIMATE_MARK in text))
    if not periods:
        return []

    # 연간 블록은 앞쪽에 몰려 있고 12월 결산이 **연도 오름차순**으로 이어진다.
    # 그 흐름이 끊기는 지점부터가 분기 컬럼이다(2025.12는 양쪽에 다 나온다).
    annual_count = 0
    previous_year = None
    for year, quarter, _ in periods:
        if quarter == 4 and (previous_year is None or year == previous_year + 1):
            annual_count += 1
            previous_year = year
        else:
            break

    values: dict[str, list[float | None]] = {}
    for tr in rows[2:]:
        cells = tr.find_all(["th", "td"])
        if len(cells) <= len(periods):
            continue
        label = cells[0].get_text(" ", strip=True).replace(" ", "")
        field = next(
            (f for f, aliases in _ROW_ALIASES.items()
             if any(label.startswith(a.replace(" ", "")) for a in aliases)),
            None,
        )
        if field is None or field in values:
            continue
        # 뒤에서부터 기간 수만큼 잘라 헤더와 정렬한다.
        values[field] = [
            _to_number(c.get_text(" ", strip=True)) for c in cells[-len(periods):]
        ]

    out: list[ConsensusSnapshot] = []
    for index, (year, quarter, is_estimate) in enumerate(periods):
        if not year or not is_estimate or index < annual_count:
            continue  # 연간 (E) 컬럼과 확정 분기는 건너뛴다
        snap = ConsensusSnapshot(code=code, fiscal_year=year, fiscal_quarter=quarter)
        for field, row in values.items():
            if index >= len(row) or row[index] is None:
                continue
            value = row[index]
            if field == "eps_est":
                snap.eps_est = value  # EPS는 원 단위
            else:
                setattr(snap, field, int(round(value * _EOK)))  # 억원 → 원
        if snap.revenue_est is not None or snap.op_est is not None:
            out.append(snap)
    return out


def fetch_annual_estimate(code: str) -> dict | None:
    """**연간** 추정치(`2026.12 (E)`)를 뽑는다 — Forward PER의 재료다.

    ★ 기존 `fetch_quarterly_estimates`는 이 컬럼을 **일부러 버린다**(분기가 아니므로).
      여기서는 그 반대로 연간 (E) 컬럼만 골라낸다. 같은 표를 두 번 읽는 셈이지만
      한쪽 로직을 건드려 다른 쪽을 깨뜨리는 것보다 낫다(T30에서 이미 크게 데였다).
    ★ 연간 추정이 **여러 해** 있으면 가장 이른 해를 쓴다 — 가장 가까운 미래가
      가장 신뢰도가 높고, 먼 해까지 쓰면 추정 오차가 누적된다.

    반환: {'fiscal_year', 'revenue_est', 'op_est', 'np_est'} (원 단위) 또는 None
    """
    try:
        resp = http_get(NAVER_MAIN_URL, params={"code": code}, timeout=40.0)
        soup = BeautifulSoup(decode_html(resp), "html.parser")
        section = soup.find("div", class_="section cop_analysis")
        table = section.find("table") if section else None
        if table is None:
            return None
        rows = table.find_all("tr")
        if len(rows) < 3:
            return None

        periods: list[tuple[int, int, bool]] = []
        for cell in rows[1].find_all(["th", "td"]):
            text = cell.get_text(" ", strip=True)
            match = _PERIOD_RE.search(text)
            if match is None:
                continue
            year, month = int(match.group(1)), int(match.group(2))
            periods.append((year, (month - 1) // 3 + 1, _ESTIMATE_MARK in text))
        if not periods:
            return None

        # 연간 블록 길이 — 분기 파서와 **같은 규칙**이어야 한다.
        annual_count = 0
        previous_year = None
        for year, quarter, _ in periods:
            if quarter == 4 and (previous_year is None or year == previous_year + 1):
                annual_count += 1
                previous_year = year
            else:
                break

        values: dict[str, list[float | None]] = {}
        for tr in rows[2:]:
            cells = tr.find_all(["th", "td"])
            if len(cells) <= len(periods):
                continue
            label = cells[0].get_text(" ", strip=True).replace(" ", "")
            field = next(
                (f for f, aliases in _ROW_ALIASES.items()
                 if any(label.startswith(a.replace(" ", "")) for a in aliases)),
                None,
            )
            if field is None or field in values:
                continue
            values[field] = [
                _to_number(c.get_text(" ", strip=True)) for c in cells[-len(periods):]
            ]

        for index in range(annual_count):
            year, _, is_estimate = periods[index]
            if not is_estimate:
                continue
            out = {"fiscal_year": year}
            for field in ("revenue_est", "op_est", "np_est"):
                row = values.get(field)
                value = row[index] if row and index < len(row) else None
                out[field] = int(round(value * _EOK)) if value is not None else None
            return out if out.get("np_est") else None
        return None
    except Exception:
        return None  # 컨센서스 없음은 정상 케이스다


def snapshot(code: str) -> list[ConsensusSnapshot]:
    """한 종목의 분기 컨센서스. 실패는 정상 케이스 — 빈 리스트를 돌려준다."""
    try:
        snaps = fetch_quarterly_estimates(code)
    except Exception:
        return []
    if not snaps:
        return []
    n_estimates = fetch_n_estimates(code)
    for snap in snaps:
        snap.n_estimates = n_estimates
    return snaps
