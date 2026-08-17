# PRD Ref: §3 (유니버스), §5.1(L0) · traps.md T8
"""네이버 시가총액 + 관리종목/거래정지 수집."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from src.config.constants import MARKET_CAP_FLOOR_KRW
from src.utils.http import http_get

NAVER_MARKET_VALUE_URL = "https://m.stock.naver.com/api/stocks/marketValue/{board}"
NAVER_ADMIN_ISSUE_URL = "https://finance.naver.com/sise/management.naver"

_BOARDS = ("KOSPI", "KOSDAQ")
_PAGE_SIZE = 100
_MAX_PAGES = 40  # 하한 도달 시 조기 종료하므로 정상적으로는 닿지 않는다


@dataclass
class MarketCapResult:
    caps: dict[str, int] = field(default_factory=dict)  # code → 시총(원)
    trade_stopped: set[str] = field(default_factory=set)  # 거래정지
    pages_read: dict[str, int] = field(default_factory=dict)
    scanned: dict[str, int] = field(default_factory=dict)  # 훑은 종목 수(하한 무관)


def fetch_market_caps(floor_krw: int = MARKET_CAP_FLOOR_KRW) -> MarketCapResult:
    """시총 하한 이상 종목의 시총(원)을 가져온다.

    ★ 정렬이 엄격한 내림차순이 아니다 (T8). 시총이 비슷한 구간에서 순서가 흔들린다.
      "하한 미만을 처음 본 순간"이 아니라 **그 페이지의 마지막 항목까지 하한 미만일 때**만
      멈춰 최소 한 페이지 분량의 여유를 남긴다.

    ★ 단위: marketValueRaw는 **원 단위 정수**다(2026-08-13 실측: 삼성전자
      1578495224160000 = 1,578조). marketValue 필드는 억원 단위 문자열이라 혼용 금지.
      추측해서 곱하지 않는다.
    """
    result = MarketCapResult()

    for board in _BOARDS:
        scanned = 0
        for page in range(1, _MAX_PAGES + 1):
            resp = http_get(
                NAVER_MARKET_VALUE_URL.format(board=board),
                params={"page": page, "pageSize": _PAGE_SIZE},
                timeout=30.0,
            )
            stocks = resp.json().get("stocks") or []
            if not stocks:
                break

            last_value: int | None = None
            for stock in stocks:
                code = stock.get("itemCode")
                raw = stock.get("marketValueRaw")
                if not code or raw in (None, ""):
                    continue
                try:
                    value = int(raw)
                except (TypeError, ValueError):
                    continue  # 단위를 못 읽으면 추측하지 않고 건너뛴다 (T11)
                scanned += 1
                last_value = value
                if value >= floor_krw:
                    result.caps[code] = value
                    # tradeStopType.code == '1'이 정상 거래(실측: '운영.Trading')
                    stop = (stock.get("tradeStopType") or {}).get("code")
                    if stop is not None and stop != "1":
                        result.trade_stopped.add(code)

            result.pages_read[board] = page
            if len(stocks) < _PAGE_SIZE or (last_value is not None and last_value < floor_krw):
                break
        result.scanned[board] = scanned

    return result


def fetch_admin_issues() -> set[str]:
    """관리종목 코드 집합.

    ★ 투자주의환기종목(코스닥)은 **여기에 포함되지 않는다.**
      KIND의 investwarn 엔드포인트가 404를 돌려주어(2026-08-13 실측) 무료로 안정적인
      소스를 확보하지 못했다. 있는 척하지 말고 미수집으로 두고 리포트에 밝힌다.
    """
    resp = http_get(NAVER_ADMIN_ISSUE_URL, timeout=30.0)
    soup = BeautifulSoup(resp.content.decode("euc-kr", errors="replace"), "html.parser")
    table = soup.find("table", class_="type_2")
    if table is None:
        raise RuntimeError("네이버 관리종목 페이지 구조 변경: table.type_2 없음")

    codes: set[str] = set()
    for tr in table.find_all("tr"):
        anchor = tr.find("a", href=re.compile(r"code=\d{6}"))
        if anchor:
            codes.add(re.search(r"code=(\d{6})", anchor["href"]).group(1))

    if not codes:
        # 0건은 "관리종목이 없다"가 아니라 파싱이 깨진 것이다. 조용히 통과시키지 않는다.
        raise RuntimeError("네이버 관리종목 파싱 결과 0건 — 페이지 구조를 확인하라")
    return codes
