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

export interface OrderDisclosureMetric {
  year: number;
  quarter: number;
  rceptNo: string;
  backlogEok: number | null;
  newOrdersEok: number | null;
  scope: string;
}

export interface OrderDisclosureSummary {
  year: number;
  quarter: number;
  rceptNo: string;
  backlogEok: number | null;
  newOrdersEok: number | null;
  scope: string | null;
  status: "measured" | "private" | "not_applicable" | "mentioned" | "truncated" | "unmentioned";
  statusLabel: string;
  evidence: string | null;
}

/**
 * DART 정기보고서의 수주 표에서 단위와 명시적인 단일 값이 모두 확인될 때만 쓴다.
 * 수주총액(누적)을 임의로 신규수주로 바꾸거나 단위를 추측하지 않는다.
 */
export function extractOrderDisclosureMetric(row: Partial<DisclosureExcerptRow>): OrderDisclosureMetric | null {
  if (!row.rcept_no || !row.fiscal_year || !row.fiscal_quarter ||
      !row.sections || typeof row.sections !== "object" || Array.isArray(row.sections)) return null;
  const explicitMetric = row.sections["공시 수주지표"];
  const section = typeof explicitMetric === "string" ? explicitMetric : row.sections["매출 및 수주상황"];
  if (typeof section !== "string") return null;
  const unit = section.match(/(?:단위\s*[:：|]\s*|\(단위\s*[:：]\s*)(백만원|천원|원|억원)/)?.[1];
  const factor = unit === "억원" ? 1 : unit === "백만원" ? 0.01 : unit === "천원" ? 0.00001 : unit === "원" ? 1e-8 : null;
  if (factor == null) return null;
  const exactValue = (label: RegExp): number | null => {
    const values = section.split("\n").flatMap((line) => {
      const cells = line.split("|").map((cell) => cell.trim());
      if (cells.length !== 2 || !label.test(cells[0]) || !/^-?[\d,]+(?:\.\d+)?$/.test(cells[1])) return [];
      return [Number(cells[1].replaceAll(",", ""))];
    });
    // 둘 이상의 행·사업부가 있으면 어떤 합계인지 알 수 없다.
    return values.length === 1 && Number.isFinite(values[0]) && values[0] >= 0
      ? Math.round(values[0] * factor * 100) / 100 : null;
  };
  const backlogEok = exactValue(/^수주\s*잔고$/);
  const newOrdersEok = exactValue(/^신규\s*수주$/);
  if (backlogEok == null && newOrdersEok == null) return null;
  return { year: row.fiscal_year, quarter: row.fiscal_quarter, rceptNo: row.rcept_no,
    backlogEok, newOrdersEok,
    scope: typeof explicitMetric === "string" ? "공시 주요계약 수주잔고(전체 아님)" : "공시 명시 수치" };
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

/** 모든 종목·분기의 수주 표시 계약. 값이 없어도 왜 없는지 숨기지 않는다. */
export function summarizeOrderDisclosure(row: DisclosureExcerptRow): OrderDisclosureSummary | null {
  if (row.fiscal_year == null || row.fiscal_quarter == null || !row.rcept_no) return null;
  const metric = extractOrderDisclosureMetric(row);
  const signal = deriveOrderDisclosureSignal(row, row.fiscal_year, row.fiscal_quarter);
  if (metric) return {
    year: row.fiscal_year, quarter: row.fiscal_quarter, rceptNo: row.rcept_no,
    backlogEok: metric.backlogEok, newOrdersEok: metric.newOrdersEok, scope: metric.scope,
    status: "measured", statusLabel: "공시 수치 확인", evidence: signal?.evidence ?? null,
  };
  const evidence = signal?.evidence ?? null;
  if (signal?.status === "limited" && evidence && /해당사항\s*없음|수주산업.{0,12}아니/.test(evidence)) {
    return { year: row.fiscal_year, quarter: row.fiscal_quarter, rceptNo: row.rcept_no,
      backlogEok: null, newOrdersEok: null, scope: null, status: "not_applicable",
      statusLabel: "해당 없음", evidence };
  }
  if (signal?.status === "limited") return {
    year: row.fiscal_year, quarter: row.fiscal_quarter, rceptNo: row.rcept_no,
    backlogEok: null, newOrdersEok: null, scope: null, status: "private",
    statusLabel: "비공개·기재 생략", evidence,
  };
  if (signal?.truncated) return {
    year: row.fiscal_year, quarter: row.fiscal_quarter, rceptNo: row.rcept_no,
    backlogEok: null, newOrdersEok: null, scope: null, status: "truncated",
    statusLabel: "발췌 범위 밖·원문 확인 필요", evidence,
  };
  if (signal) return {
    year: row.fiscal_year, quarter: row.fiscal_quarter, rceptNo: row.rcept_no,
    backlogEok: null, newOrdersEok: null, scope: null, status: "mentioned",
    statusLabel: "수주 언급·단일 수치 미확인", evidence,
  };
  return {
    year: row.fiscal_year, quarter: row.fiscal_quarter, rceptNo: row.rcept_no,
    backlogEok: null, newOrdersEok: null, scope: null, status: "unmentioned",
    statusLabel: "정기보고서에서 수주 수치 미확인", evidence: null,
  };
}
