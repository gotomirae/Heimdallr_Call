// PRD Ref: §9 /season · traps.md T74
//
// ★★ **공시에서 회계 분기를 뽑는다.**
//   `earnings_disclosures.fiscal_quarter`는 **전 행이 null**이다(실측 1,558/1,558) —
//   수집기가 채우지 않는다. 그래서 분기 판정을 여기서 한다.
//
// ★ 왜 필요한가: 시즌 화면이 "재무가 수집됐는가"만 보고 발표 여부를 판정했다.
//   그래서 **공시를 이미 낸 610종목이 '미발표'로 표시**됐다(대한항공·리노공업·
//   삼양식품 등). 최근 공시 목록에는 그 공시 링크가 멀쩡히 걸려 있는데도.
//   공시는 났고 재무 수집만 늦은 것 — 그 둘은 **다른 상태**다.

/** 공시가 가리키는 회계 분기. 못 읽으면 null — 추측하지 않는다. */
export interface DisclosedQuarter {
  year: number;
  quarter: number;
}

/**
 * 보고서명에서 기준 월을 읽어 분기를 만든다.
 *
 * 실측 형식(2026-08-17):
 *   `반기보고서 (2026.06)`              → 2026.2Q
 *   `[기재정정]반기보고서 (2026.06)`      → 2026.2Q
 *   `분기보고서 (2026.03)`              → 2026.1Q
 *   `사업보고서 (2025.12)`              → 2025.4Q
 *   `연결재무제표기준영업(잠정)실적(공정공시)` → 월이 없다 → null
 *
 * ★ **기준 월이 곧 분기말**이다. 03→1Q · 06→2Q · 09→3Q · 12→4Q.
 *   비12월 결산이면 어긋날 수 있지만, 보고서 자체가 그 월을 기준으로 하므로
 *   공시가 말하는 분기는 이게 맞다.
 */
export function quarterFromReportName(name: string | null | undefined): DisclosedQuarter | null {
  if (!name) return null;
  const m = name.match(/\((\d{4})[.\-/](\d{1,2})\)/);
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  if (month < 1 || month > 12) return null;
  return { year, quarter: Math.floor((month - 1) / 3) + 1 };
}

/**
 * 공시일로 분기를 추정한다. **보고서명을 못 읽었을 때만** 쓴다.
 *
 * ★ 발표는 분기가 끝난 **뒤에** 나온다 → 공시일이 속한 분기의 **직전** 분기다.
 *   `src/analysis/outcome_run.py::announce_dates()`와 같은 규칙이어야 한다.
 * ★ 잠정실적(공정공시)은 보고서명에 월이 없어 이 경로로 온다.
 */
export function quarterFromDisclosedAt(iso: string | null | undefined): DisclosedQuarter | null {
  if (!iso || iso.length < 7) return null;
  const year = Number(iso.slice(0, 4));
  const month = Number(iso.slice(5, 7));
  if (!year || month < 1 || month > 12) return null;
  let quarter = Math.floor((month - 1) / 3) + 1 - 1;
  if (quarter === 0) return { year: year - 1, quarter: 4 };
  return { year, quarter };
}

/**
 * 공시 한 건이 가리키는 분기. 보고서명 → 공시일 순으로 시도한다.
 *
 * ★ 보고서명을 먼저 본다. 공시일 추정은 **분기 경계에서 틀린다** —
 *   7월 초에 나온 1Q 정정 공시를 2Q로 읽어버린다.
 */
export function disclosedQuarter(row: {
  report_nm?: string | null;
  disclosed_at?: string | null;
}): DisclosedQuarter | null {
  return quarterFromReportName(row.report_nm) ?? quarterFromDisclosedAt(row.disclosed_at);
}

/** `qIndex` 호환 정수. 연도 경계를 넘는 비교는 반드시 이걸 쓴다. */
export function quarterIndex(q: DisclosedQuarter): number {
  return q.year * 4 + (q.quarter - 1);
}
