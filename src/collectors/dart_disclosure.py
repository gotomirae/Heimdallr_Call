# PRD Ref: §5.1(L1), §5.3 · traps.md T27
"""DART 공시 폴링 → 실적 공시 감지.

`list.json`을 corp_code 없이 호출한다(corp_cls=Y/K 각각).
`rcept_no`가 자연 멱등키다 — 같은 공시를 두 번 처리하지 않는다.

★ 분류에서 조용히 틀리는 지점 두 곳 (실측 2026-08-13):
  1. `"실적"`으로 매칭하면 **증권발행실적보고서(436건)** · 소액공모실적보고서가 딸려 온다.
     반드시 `"영업(잠정)실적"` 전체 문자열로 판정한다.
  2. `"...(자회사의 주요경영사항)"`은 **자회사 실적**이지 공시 주체의 실적이 아니다(24건).
     그대로 받으면 모회사 실적으로 둔갑한다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from src.config.constants import DART_BASE_URL
from src.utils.env import require_env
from src.utils.http import http_get

LIST_URL = f"{DART_BASE_URL}/list.json"

DOC_PROVISIONAL = "provisional"
DOC_PL_CHANGE = "pl_change"
DOC_PERIODIC = "periodic"

#: 공시명 분류 규칙. 부분일치이므로 **더 긴 문자열을 먼저** 검사한다.
_PROVISIONAL_TOKEN = "영업(잠정)실적"
_PL_CHANGE_TOKEN = "매출액또는손익구조"
_PERIODIC_TOKENS = ("분기보고서", "반기보고서", "사업보고서")

#: 공시 주체의 실적이 아니다 — 버린다.
_SUBSIDIARY_TOKEN = "자회사의 주요경영사항"
#: 실적 확정치가 아니라 전망이다 — "영업(잠정)실적"과 헷갈리지 않도록 명시적으로 배제.
_FORECAST_TOKEN = "전망"
_CORRECTION_TOKENS = ("[기재정정]", "[첨부정정]")

REQUEST_INTERVAL_SEC = 0.15


@dataclass
class Disclosure:
    rcept_no: str
    code: str
    corp_code: str
    corp_name: str
    report_nm: str
    doc_type: str
    disclosed_at: str  # 'YYYYMMDD'
    is_correction: bool = False


@dataclass
class PollStats:
    calls: int = 0
    scanned: int = 0
    matched: int = 0
    by_type: dict[str, int] = field(default_factory=dict)
    dropped_subsidiary: int = 0
    dropped_forecast: int = 0
    dropped_not_in_universe: int = 0
    dropped_excluded: int = 0
    corrections: int = 0


def classify(report_nm: str) -> tuple[str | None, str | None]:
    """(doc_type, 버린 사유). 실적 공시가 아니면 (None, None)."""
    name = report_nm.strip()

    if _PROVISIONAL_TOKEN in name:
        if _SUBSIDIARY_TOKEN in name:
            return None, "subsidiary"
        return DOC_PROVISIONAL, None

    if _PL_CHANGE_TOKEN in name:
        if _SUBSIDIARY_TOKEN in name:
            return None, "subsidiary"
        return DOC_PL_CHANGE, None

    if any(token in name for token in _PERIODIC_TOKENS):
        return DOC_PERIODIC, None

    # "연결재무제표기준영업실적등에대한전망" — 실적이 아니라 전망이다.
    if _FORECAST_TOKEN in name and "영업실적" in name:
        return None, "forecast"

    return None, None


def is_correction(report_nm: str) -> bool:
    return any(token in report_nm for token in _CORRECTION_TOKENS)


def poll(
    begin: str,
    end: str,
    *,
    universe: dict[str, dict],
    stats: PollStats | None = None,
    max_pages: int = 200,
) -> list[Disclosure]:
    """기간 내 실적 공시를 모은다. `universe`는 {code: krx_universe row}."""
    stats = stats or PollStats()
    out: list[Disclosure] = []
    seen: set[str] = set()

    for corp_cls in ("Y", "K"):
        page = 1
        while page <= max_pages:
            resp = http_get(
                LIST_URL,
                params={
                    "crtfc_key": require_env("OPENDART_API_KEY"),
                    "corp_cls": corp_cls,
                    "bgn_de": begin,
                    "end_de": end,
                    "page_no": page,
                    "page_count": 100,
                },
                timeout=90.0,
            )
            body = resp.json()
            stats.calls += 1
            if body.get("status") != "000":
                break  # '013' 조회 결과 없음 — 정상 케이스

            for row in body.get("list") or []:
                stats.scanned += 1
                doc_type, dropped = classify(row["report_nm"])
                if dropped == "subsidiary":
                    stats.dropped_subsidiary += 1
                    continue
                if dropped == "forecast":
                    stats.dropped_forecast += 1
                    continue
                if doc_type is None:
                    continue

                code = (row.get("stock_code") or "").strip()
                universe_row = universe.get(code)
                if not code or universe_row is None:
                    stats.dropped_not_in_universe += 1
                    continue
                if universe_row.get("is_excluded"):
                    stats.dropped_excluded += 1
                    continue

                rcept_no = row["rcept_no"]
                if rcept_no in seen:  # 멱등 — 같은 공시를 두 번 담지 않는다
                    continue
                seen.add(rcept_no)

                correction = is_correction(row["report_nm"])
                if correction:
                    stats.corrections += 1
                stats.matched += 1
                stats.by_type[doc_type] = stats.by_type.get(doc_type, 0) + 1
                out.append(
                    Disclosure(
                        rcept_no=rcept_no,
                        code=code,
                        corp_code=row["corp_code"],
                        corp_name=row["corp_name"].strip(),
                        report_nm=row["report_nm"].strip(),
                        doc_type=doc_type,
                        disclosed_at=row["rcept_dt"],
                        is_correction=correction,
                    )
                )

            if page >= int(body.get("total_page", 1)):
                break
            page += 1
            time.sleep(REQUEST_INTERVAL_SEC)

    return out
