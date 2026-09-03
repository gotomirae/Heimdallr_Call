// PRD Ref: §9 · traps.md T56(URL을 추론하지 마라), T58(DART 검색 URL은 검색을 하지 않는다)
//
// ★ 외부 링크는 **여기서만** 만든다. 세 곳(텔레그램·목록·상세)에 흩어지면
//   틀렸을 때 아무것도 실패하지 않고 링크만 죽는다 — 알아채는 데 오래 걸린다.
//   같은 규칙의 파이썬 쪽 짝은 `src/notify/links.py`다.

/**
 * DART 공시 **원문**. `rcept_no`(접수번호)가 있어야 열린다.
 *
 * ★ `dsab007/main.do?textCrpNm=회사명`을 쓰면 안 된다.
 *   200을 주고 검색창에 회사명까지 채워 주지만 **검색을 실행하지 않아**
 *   빈 화면이 뜬다. 실측(2026-08-17): 파라미터 있는 응답과 없는 응답의 차이가
 *   input의 `value=` 24바이트뿐이고, 페이지 JS 어디에서도 search()를 부르지 않는다.
 *   "링크는 살아 있는데 아무것도 안 나오는" 형태라 오류로 보이지 않는다.
 */
export function dartReportUrl(rceptNo: string): string {
  return `https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${encodeURIComponent(rceptNo)}`;
}

/** 네이버 증권 종목 페이지(PC). 시세·차트·공시·재무를 한 화면에서 본다. */
export function naverStockUrl(code: string): string {
  return `https://finance.naver.com/item/main.naver?code=${encodeURIComponent(code)}`;
}

/** 네이버 증권 종목 페이지(모바일). 텔레그램에서 여는 링크는 이쪽이 낫다. */
export function naverStockMobileUrl(code: string): string {
  return `https://m.stock.naver.com/domestic/stock/${encodeURIComponent(code)}/total`;
}

/** 네이버 증권의 그 종목 공시 목록 — DART 접수번호가 없을 때의 대체 경로. */
export function naverDisclosureUrl(code: string): string {
  return `https://finance.naver.com/item/news_notice.naver?code=${encodeURIComponent(code)}`;
}

/** StockEasy 종목 분석 페이지. */
export function stockeasyStockUrl(code: string): string {
  return `https://stockeasy.intellio.kr/stock-analysis/stock-info/${encodeURIComponent(code)}`;
}
