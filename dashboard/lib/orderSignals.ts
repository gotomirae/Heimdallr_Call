// PRD Ref: §9.1 — 종목 상세의 공시 기반 확인 포인트
//
// ★ 수주 발췌는 한 분기뿐이므로 QoQ를 만들지 않는다. 같은 분기 원문에서
//   "다음 보고서에 다시 확인할 말"만 꺼내며, 금액·증가율을 재계산하지 않는다.

export interface DisclosureExcerptRow {
  rcept_no: string;
  code: string;
  fiscal_year: number | null;
  fiscal_quarter: number | null;
  sections: Record<string, unknown> | null;
  excerpt_chars: number | null;
  full_chars: number | null;
}

export interface OrderDisclosureSignal {
  status: "evidence" | "limited";
  evidence: string;
  sourceLabel: string;
  truncated: boolean;
}

const ORDER_TERMS = [
  "수주잔고",
  "수주 총액",
  "수주총액",
  "신규 수주",
  "신규수주",
];
const LIMITED = /비공개|영업\s*(?:상|비밀)|기재\s*(?:를\s*)?생략|해당사항\s*없음|수주산업.{0,12}아니/;
const TRUNCATED = /…?\s*\(이하\s*[\d,]+자\s*생략\)/;

function compactContext(text: string, at: number): string {
  const clean = text.replace(/\s+/g, " ").trim();
  const start = Math.max(0, at - 80);
  const end = Math.min(clean.length, at + 180);
  return `${start > 0 ? "…" : ""}${clean.slice(start, end).trim()}${end < clean.length ? "…" : ""}`;
}

/**
 * 같은 분기 정기보고서에 실제 수주 언어가 있을 때만 확인 신호를 만든다.
 * SC: 다른 분기·매출표뿐인 발췌·비정상 sections는 모두 null이다.
 */
export function deriveOrderDisclosureSignal(
  row: Partial<DisclosureExcerptRow> | null,
  expectedYear: number,
  expectedQuarter: number
): OrderDisclosureSignal | null {
  if (
    !row ||
    row.fiscal_year !== expectedYear ||
    row.fiscal_quarter !== expectedQuarter ||
    !row.sections ||
    typeof row.sections !== "object" ||
    Array.isArray(row.sections)
  ) {
    return null;
  }

  for (const body of Object.values(row.sections)) {
    if (typeof body !== "string" || body.trim() === "") continue;
    const normalized = body.replace(/\s+/g, " ").trim();
    const matches = ORDER_TERMS
      .map((term) => ({ term, at: normalized.indexOf(term) }))
      .filter((match) => match.at >= 0)
      .sort((a, b) => a.at - b.at);
    if (matches.length === 0) continue;

    const evidence = compactContext(normalized, matches[0].at);
    return {
      status: LIMITED.test(evidence) ? "limited" : "evidence",
      evidence,
      sourceLabel: `${expectedYear}년 ${expectedQuarter}분기 정기보고서`,
      truncated: TRUNCATED.test(normalized),
    };
  }
  return null;
}
