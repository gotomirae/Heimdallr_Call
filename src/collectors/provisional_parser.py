# PRD Ref: §5.1(L2'), §5.3 · traps.md T11, T27
"""잠정실적 공정공시 원문 표 파싱 (규칙 기반).

★ `document.xml`은 공정공시(거래소공시)에 쓸 수 없다 — status 014 "파일이 존재하지 않습니다"
  가 돌아온다(실측 2026-08-13). 원문은 DART 웹 뷰어에서 받아야 한다:
      1) dsaf001/main.do?rcpNo=... → 본문에서 `viewDoc("<rcpNo>", "<dcmNo>", ...)` 추출
      2) report/viewer.do?rcpNo=..&dcmNo=..&dtd=HTML  → 실제 HTML (charset=MS949)

표 구조(실측):
    구분(단위 : 백만원, %) | 당기실적 | 전기실적 | 전기대비 | 전년동기실적 | 전년동기대비
    매출액   당해실적  86,805  78,348  10.8  -  82,130  5.7  -
             누계실적 165,153       -     -  -  164,466  0.4  -
    영업이익 당해실적  11,617   5,795 100.5  -   3,521 230.0  -

★ 단위를 못 읽으면 **추측해서 곱하지 말고 그 항목을 건너뛴다** (T11).
  회사·분기마다 원/백만원/억원이 섞이므로 종목별 고정 가정도 금물이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from bs4 import BeautifulSoup

from src.utils.http import http_get

VIEWER_MAIN_URL = "https://dart.fss.or.kr/dsaf001/main.do"
VIEWER_DOC_URL = "https://dart.fss.or.kr/report/viewer.do"

#: 단위 문자열 → 원 단위 배수. 여기 없는 표기는 **추측하지 않는다**.
UNIT_MULTIPLIERS: dict[str, int] = {
    "원": 1,
    "천원": 1_000,
    "백만원": 1_000_000,
    "억원": 100_000_000,
    "십억원": 1_000_000_000,
    # 실측 2026-08-13: 삼성전자 7/7 잠정공시가 '조원' 단위였다. 없으면 T11대로
    # 항목을 통째로 건너뛰므로(에러는 안 나지만 데이터가 빈다) 실제 본 단위는 추가한다.
    "조원": 1_000_000_000_000,
}

#: 표의 계정명 → 내부 필드
ACCOUNT_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("매출액", "영업수익", "매출"),
    "op": ("영업이익", "영업이익(손실)"),
    "np": ("당기순이익", "당기순이익(손실)", "당기순손익"),
}

_DCM_RE = re.compile(r'viewDoc\(\s*"(\d+)"\s*,\s*"(\d+)"')
_UNIT_RE = re.compile(r"단위\s*[:：]\s*([가-힣]+)")
_NUM_RE = re.compile(r"^-?[\d,]+(?:\.\d+)?$")
_PERIOD_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


@dataclass
class ProvisionalResult:
    rcept_no: str
    fs_div: str | None = None  # 'CFS'(연결) | 'OFS'(별도)
    unit: str | None = None
    unit_multiplier: int | None = None
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None
    revenue: int | None = None
    op: int | None = None
    np: int | None = None
    #: 단위를 못 읽어 **의도적으로 건너뛴** 항목 (T11). 화면에 밝힌다.
    skipped: list[str] = field(default_factory=list)
    #: 당기실적 기간의 일수. 분기 실적이면 80~100일이다.
    period_days: int | None = None
    #: 공시일 대비 실적기간이 이상하면 사유가 들어간다(분기를 잘못 읽은 신호).
    period_warning: str | None = None
    ok: bool = False
    failure: str | None = None


def fetch_document_html(rcept_no: str) -> str | None:
    """공시 원문 HTML. 실패하면 None(예외를 올려 파이프라인을 죽이지 않는다)."""
    main = http_get(VIEWER_MAIN_URL, params={"rcpNo": rcept_no}, timeout=60.0)
    match = _DCM_RE.search(main.text)
    if match is None or match.group(1) != rcept_no:
        return None
    resp = http_get(
        VIEWER_DOC_URL,
        params={
            "rcpNo": rcept_no, "dcmNo": match.group(2),
            "eleId": "0", "offset": "0", "length": "0", "dtd": "HTML",
        },
        timeout=60.0,
    )
    # 뷰어는 charset=MS949로 온다. utf-8로 읽으면 계정명이 깨져 매칭이 통째로 실패한다.
    charset = (resp.headers.get("content-type") or "").lower()
    encoding = "cp949" if ("949" in charset or "euc-kr" in charset) else "utf-8"
    return resp.content.decode(encoding, errors="replace")


def parse_unit(text: str) -> tuple[str | None, int | None]:
    """'구분(단위 : 백만원, %)' → ('백만원', 1_000_000). 모르는 표기는 (표기, None)."""
    match = _UNIT_RE.search(text)
    if match is None:
        return None, None
    unit = match.group(1)
    return unit, UNIT_MULTIPLIERS.get(unit)


def _to_number(text: str) -> float | None:
    cleaned = text.replace(",", "").strip()
    if not cleaned or cleaned in ("-", "—", "N/A"):
        return None
    if not _NUM_RE.match(cleaned):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _quarter_from_rows(table) -> tuple[int | None, int | None, int | None]:
    """실적기간 표의 **'당기실적' 행**에서 (연도, 분기, 기간일수)를 뽑는다.

    ★ 표 전체 텍스트에서 날짜를 긁어 마지막 것을 쓰면 안 된다.
      실적기간 표는 아래 순서로 5개 기간을 싣는다:
          당기실적 / 전기실적 / 전년동기실적 / 당기누계실적 / **전년동기누적실적**
      마지막 날짜는 *전년* 동기 누적의 종료일이라 **연도가 1년 어긋난다.**
      실측(2026-08): 2026.2Q 공시가 전부 2025.2Q로 찍혔고 파싱은 '성공'으로 보고됐다.

    ★ 기간 일수를 함께 돌려준다. 같은 공시명으로 **월별 실적**을 내는 회사가 있다(T28).
    """
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if not cells:
            continue
        label = cells[0].replace(" ", "")
        if not label.startswith("당기실적"):
            continue  # '당기누계실적'도 시작이 '당기'지만 '당기실적'으로는 시작하지 않는다
        dates = _PERIOD_RE.findall(" ".join(cells))
        if not dates:
            continue
        end_year, end_month, end_day = (int(x) for x in dates[-1])
        span = None
        if len(dates) >= 2:
            start = date(*(int(x) for x in dates[0]))
            span = (date(end_year, end_month, end_day) - start).days + 1
        return end_year, (end_month - 1) // 3 + 1, span
    return None, None, None


def check_period_plausible(
    fiscal_year: int | None, fiscal_quarter: int | None, disclosed_at: str | None
) -> str | None:
    """공시일 대비 실적 분기가 그럴듯한가. 이상하면 사유 문자열, 정상이면 None.

    ★ 잠정실적은 분기 종료 후 보통 2개월 안에 공시된다. 6개월을 넘어가면
      실적기간을 잘못 읽은 것이다(전년 동기 행을 집는 실수가 실제로 있었다).
      숫자는 멀쩡해 보이므로 이 검사가 없으면 못 잡는다.
    """
    if not disclosed_at or fiscal_year is None or fiscal_quarter is None:
        return None
    try:
        disclosed_year, disclosed_month = int(disclosed_at[:4]), int(disclosed_at[4:6])
    except (ValueError, IndexError):
        return None
    quarter_end_month = fiscal_quarter * 3
    months_after = (disclosed_year - fiscal_year) * 12 + (disclosed_month - quarter_end_month)
    if months_after < 0:
        return f"future_period(+{-months_after}m)"
    if months_after > 6:
        return f"stale_period({months_after}m)"
    return None


def parse_provisional(
    html: str, rcept_no: str, *, disclosed_at: str | None = None
) -> ProvisionalResult:
    result = ProvisionalResult(rcept_no=rcept_no)
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        result.failure = "no_table"
        return result

    full_text = soup.get_text(" ", strip=True)

    # ── 연결/별도 ──
    if "연결실적내용" in full_text or "연결재무제표" in full_text:
        result.fs_div = "CFS"
    elif "실적내용" in full_text:
        result.fs_div = "OFS"

    # ── 실적기간 → 회계연도·분기 ──
    for table in tables:
        text = table.get_text(" ", strip=True)
        if "당기실적" in text and "~" in text:
            year, quarter, span = _quarter_from_rows(table)
            if year:
                result.fiscal_year, result.fiscal_quarter = year, quarter
                result.period_days = span
                break

    # ── 단위 ──
    result.unit, result.unit_multiplier = parse_unit(full_text)

    # ── 계정값 ──
    # ★ "행이 가장 많은 표"로 고르지 마라. 실적기간 표가 더 길 수 있고, 그러면
    #   계정을 하나도 못 찾고 'no_account_matched'로 조용히 실패한다.
    #   계정명이 실제로 들어 있는 표를 고른다.
    all_aliases = {a for aliases in ACCOUNT_ALIASES.values() for a in aliases}

    def _account_hits(table) -> int:
        return sum(
            1
            for tr in table.find_all("tr")
            for cell in tr.find_all(["td", "th"])[:1]
            if cell.get_text(" ", strip=True) in all_aliases
        )

    data_table = max(tables, key=lambda t: (_account_hits(t), len(t.find_all("tr"))))
    found: dict[str, float] = {}
    for tr in data_table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) < 3:
            continue
        label = cells[0]
        field_name = next(
            (f for f, aliases in ACCOUNT_ALIASES.items() if label in aliases), None
        )
        if field_name is None or field_name in found:
            continue
        # 계정명 다음 칸이 '당해실적'/'누계실적' 구분일 수 있다. 첫 숫자를 당기실적으로 본다.
        for cell in cells[1:]:
            if cell in ("당해실적", "누계실적"):
                continue
            value = _to_number(cell)
            if value is not None:
                found[field_name] = value
                break

    if not found:
        result.failure = "no_account_matched"
        return result

    if result.unit_multiplier is None:
        # ★ 단위를 못 읽었다. 추측해서 곱하지 않는다 — 전부 건너뛴다 (T11).
        result.skipped = sorted(found)
        result.failure = "unknown_unit"
        return result

    for field_name, value in found.items():
        setattr(result, field_name, int(round(value * result.unit_multiplier)))

    # ★ 분기 실적이 맞는가. 같은 공시명으로 **월별 실적**을 내는 회사가 있다(T28).
    #   월간 매출을 분기 칸에 넣으면 매출이 1/3로 들어가 '가짜 급감'이 된다.
    if result.period_days is not None and not (80 <= result.period_days <= 100):
        result.period_warning = f"not_quarterly({result.period_days}d)"
    else:
        result.period_warning = check_period_plausible(
            result.fiscal_year, result.fiscal_quarter, disclosed_at
        )

    result.ok = (
        (result.revenue is not None or result.op is not None)
        and result.fiscal_year is not None
        and result.period_warning is None
    )
    if not result.ok:
        result.failure = (
            result.period_warning
            or ("no_period" if result.fiscal_year is None else "no_value")
        )
    return result


def to_db_row(result: ProvisionalResult, code: str, disclosed_at: str | None = None) -> dict | None:
    """`quarterly_fundamentals` upsert 행. 파싱 실패면 None.

    ★ `is_estimate=True`로 저장한다. 45일 뒤 정기보고서 확정치가 들어오면
      `delta_from_preliminary`에 변동을 기록해야 한다(T4) — 차이 자체가 신호다.
    """
    if not result.ok or result.fiscal_year is None or result.fs_div is None:
        return None
    row = {
        "code": code,
        "fiscal_year": result.fiscal_year,
        "fiscal_quarter": result.fiscal_quarter,
        "fs_div": result.fs_div,
        "revenue": result.revenue,
        "op": result.op,
        "np": result.np,
        "source": "dart_provisional",
        "is_estimate": True,
    }
    if disclosed_at and len(disclosed_at) == 8:
        row["disclosed_at"] = (
            f"{disclosed_at[:4]}-{disclosed_at[4:6]}-{disclosed_at[6:]}T00:00:00+09:00"
        )
    return row


def delta_from_confirmed(preliminary: dict, confirmed: dict) -> dict:
    """잠정 대비 확정치 변동 (T4). **확정치가 잠정보다 나빠졌으면 그 자체가 경고다.**"""
    out: dict = {}
    for field in ("revenue", "op", "np"):
        pre, con = preliminary.get(field), confirmed.get(field)
        if pre in (None, 0) or con is None:
            continue
        out[field] = {
            "preliminary": pre,
            "confirmed": con,
            "delta_pct": (float(con) - float(pre)) / abs(float(pre)) * 100,
        }
    return out
