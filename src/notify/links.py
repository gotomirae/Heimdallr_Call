# PRD Ref: §8 · traps.md T56, T58
"""외부 링크 조립 — **순수 함수. 외부 I/O 금지.**

★ 대시보드 쪽 짝은 `dashboard/lib/links.ts`다. 규칙이 갈라지면 텔레그램과
  화면이 서로 다른 곳을 가리키는데 **둘 다 200이라 아무도 눈치채지 못한다.**
"""

from __future__ import annotations

from urllib.parse import quote

DART_REPORT = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
NAVER_STOCK = "https://finance.naver.com/item/main.naver?code={code}"
NAVER_STOCK_MOBILE = "https://m.stock.naver.com/domestic/stock/{code}/total"
NAVER_DISCLOSURE = "https://finance.naver.com/item/news_notice.naver?code={code}"
STOCKEASY_STOCK = "https://stockeasy.intellio.kr/stock-analysis/stock-info/{code}"


def dart_report_url(rcept_no: str | None) -> str | None:
    """DART 공시 **원문**. 접수번호가 없으면 링크를 만들지 않는다.

    ★ `dsab007/main.do?textCrpNm=회사명`은 쓰지 않는다 — 200을 주고 검색창에
      회사명까지 채워 주지만 **검색을 실행하지 않아 빈 화면**이 뜬다.
      죽은 링크가 아니라 '살아 있는데 아무것도 없는' 링크라 더 나쁘다.
    """
    if not rcept_no:
        return None
    return DART_REPORT.format(rcept_no=quote(str(rcept_no)))


def naver_stock_url(code: str, *, mobile: bool = False) -> str:
    """네이버 증권 종목 페이지. 텔레그램은 폰에서 열리므로 mobile=True를 쓴다."""
    template = NAVER_STOCK_MOBILE if mobile else NAVER_STOCK
    return template.format(code=quote(str(code)))


def naver_disclosure_url(code: str) -> str:
    """네이버 증권의 그 종목 공시 목록 — DART 접수번호가 없을 때의 대체 경로."""
    return NAVER_DISCLOSURE.format(code=quote(str(code)))


def stockeasy_stock_url(code: str) -> str:
    """StockEasy 종목 분석 페이지. 로그인 뒤에도 같은 종목 경로로 돌아온다."""
    return STOCKEASY_STOCK.format(code=quote(str(code)))
