// PRD Ref: §9.1 — 종목 상세의 공시 기반 확인 포인트
//
// 수주 확인 포인트 한 건으로 QoQ를 만들지 않는다. 그래프는 별도 수집한
// 다분기 수치 중 같은 공시 범위·통화의 연속 분기만 비교한다.

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
  newOrdersPeriod: string | null;
  amountUnit?: string;
  backlogAmount?: number | null;
  newOrdersAmount?: number | null;
  periodEnd?: string;
  periodLabel?: string;
  closingMonth?: number;
  sourceUrl?: string;
  sourceLabel?: string;
  sourcePage?: string;
  newOrdersSourceUrl?: string;
}

export interface OrderDisclosureSummary {
  year: number;
  quarter: number;
  rceptNo: string;
  backlogEok: number | null;
  newOrdersEok: number | null;
  scope: string | null;
  newOrdersPeriod: string | null;
  amountUnit?: string;
  backlogAmount?: number | null;
  newOrdersAmount?: number | null;
  status: "measured" | "private" | "not_applicable" | "mentioned" | "truncated" | "unmentioned";
  statusLabel: string;
  evidence: string | null;
  periodEnd?: string;
  periodLabel?: string;
  sourceUrl?: string;
  sourceLabel?: string;
  sourcePage?: string;
  newOrdersSourceUrl?: string;
}

export interface OrderContractDisclosure {
  rceptNo: string;
  disclosedAt: string | null;
  contractName: string | null;
  amountEok: number | null;
  salesRatioPct: number | null;
  counterparty: string | null;
  contractDate: string | null;
  startDate: string | null;
  endDate: string | null;
  status: "measured" | "limited" | "terminated";
  /** 정정 총액은 증가분이 아니므로 신규 계약 막대에 다시 더하지 않는다. */
  isCorrection?: boolean;
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

/** 결산월은 실제 사업보고서에서 검증했다. 달력분기 데이터와 합치지 않는다. */
export function readOrderReportPeriod(row: Partial<DisclosureExcerptRow>) {
  const p = record(row.sections?.["공시 보고기간"]);
  if (!p || typeof p.end !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(p.end) ||
      !Number.isInteger(p.closingMonth) || !Number.isInteger(p.fiscalYear) || !Number.isInteger(p.fiscalQuarter)) return null;
  const closing = Number(p.closingMonth), year = Number(p.end.slice(0, 4)), month = Number(p.end.slice(5, 7));
  const distance = (month - closing + 12) % 12;
  const q = distance / 3 || 4;
  const kind = p.reportKind;
  const endDate = new Date(`${p.end}T00:00:00Z`);
  if (closing < 1 || closing > 12 || month < 1 || month > 12 || distance % 3 ||
      p.fiscalYear !== year + Number(month > closing) || p.fiscalQuarter !== q ||
      !(kind === "사업보고서" && q === 4 || kind === "반기보고서" && q === 2 || kind === "분기보고서" && (q === 1 || q === 3)) ||
      Number.isNaN(endDate.getTime()) || endDate.toISOString().slice(0, 10) !== p.end) return null;
  return { end: p.end, year: Number(p.fiscalYear), quarter: Number(p.fiscalQuarter), closingMonth: closing,
    label: `${p.end.slice(2, 7)}(${String(kind).replace("보고서", "")})` };
}

/** 첨부만 바꾼 정정을 새 실적 본문 발표일로 쓰면 계약 창이 잘못 잘린다. */
export function isAttachmentOnlyCorrection(reportName: string | null | undefined): boolean {
  return /\[\s*첨부\s*정정\s*\]/.test(reportName ?? "");
}

/** 단일판매·공급계약은 전체 신규수주가 아닌, 공시된 개별 계약이다. */
export function extractOrderContractDisclosure(
  row: Partial<DisclosureExcerptRow>
): OrderContractDisclosure | null {
  if (!row.rcept_no || !row.sections) return null;
  const value = record(row.sections["단일판매·공급계약"]);
  if (!value) return null;
  const number = (key: string): number | null =>
    typeof value[key] === "number" && Number.isFinite(value[key]) ? Number(value[key]) : null;
  const string = (key: string): string | null =>
    typeof value[key] === "string" && String(value[key]).trim() ? String(value[key]).trim() : null;
  const amountKrw = number("amount_krw");
  return {
    rceptNo: row.rcept_no,
    disclosedAt: string("disclosed_at"),
    contractName: string("contract_name"),
    amountEok: amountKrw == null ? null : amountKrw / 100_000_000,
    salesRatioPct: number("sales_ratio_pct"),
    counterparty: string("counterparty"),
    contractDate: string("contract_date"),
    startDate: string("start_date"),
    endDate: string("end_date"),
    status: string("disclosure_status") === "terminated"
      ? "terminated"
      : string("disclosure_status") === "limited" ? "limited" : "measured",
    ...(/정정/.test(string("report_name") ?? "") ? { isCorrection: true } : {}),
  };
}

/**
 * DART 정기보고서의 수주 표에서 단위와 명시적인 단일 값이 모두 확인될 때만 쓴다.
 * 수주총액(누적)을 임의로 신규수주로 바꾸거나 단위를 추측하지 않는다.
 */
export function extractOrderDisclosureMetric(row: Partial<DisclosureExcerptRow>): OrderDisclosureMetric | null {
  const period = readOrderReportPeriod(row);
  if (!row.rcept_no || !(period?.year ?? row.fiscal_year) || !(period?.quarter ?? row.fiscal_quarter) ||
      !row.sections || typeof row.sections !== "object" || Array.isArray(row.sections)) return null;
  const explicitMetric = row.sections["공시 수주지표"];
  const section = typeof explicitMetric === "string" ? explicitMetric : row.sections["매출 및 수주상황"];
  if (typeof section !== "string") return null;
  const unit = section.match(/(?:단위\s*[:：|]\s*|\(단위\s*[:：]\s*)(백만원|천원|원|억원|백만USD|백만달러|천USD|천달러|USD|달러|천RMB|백만IDR)/)?.[1];
  const krw = ["억원", "백만원", "천원", "원"].includes(unit ?? "");
  const amountUnit = krw ? "억원" : unit?.includes("RMB") ? "백만RMB" : unit?.includes("IDR") ? "백만IDR" : "백만USD";
  const factor = unit === "억원" ? 1 : unit === "백만원" ? 0.01 : unit === "천원" ? 0.00001 : unit === "원" ? 1e-8
    : ["백만USD", "백만달러", "백만IDR"].includes(unit ?? "") ? 1
    : ["천USD", "천달러", "천RMB"].includes(unit ?? "") ? 0.001
    : ["USD", "달러"].includes(unit ?? "") ? 0.000001 : null;
  if (factor == null) return null;
  const exactValue = (label: RegExp): number | null => {
    const values = section.split("\n").flatMap((line) => {
      const cells = line.split("|").map((cell) => cell.trim());
      if (cells.length !== 2 || !label.test(cells[0]) || !/^-?[\d,]+(?:\.\d+)?$/.test(cells[1])) return [];
      return [Number(cells[1].replaceAll(",", ""))];
    });
    // 둘 이상의 행·사업부가 있으면 어떤 합계인지 알 수 없다.
    return values.length === 1 && Number.isFinite(values[0]) && values[0] >= 0
      // 백만 외화 단위에서도 원문 1센트(1e-8)를 보존한다. 소액을 실제 0으로 바꾸지 않는다.
      ? Math.round(values[0] * factor * (krw ? 100 : 1e8)) / (krw ? 100 : 1e8) : null;
  };
  const backlogAmount = exactValue(/^수주\s*잔고$/);
  const newOrdersAmount = exactValue(/^신규\s*수주$/);
  if (backlogAmount == null && newOrdersAmount == null) return null;
  const backlogEok = krw ? backlogAmount : null, newOrdersEok = krw ? newOrdersAmount : null;
  const exactText = (label: RegExp): string | null => {
    const values = section.split("\n").flatMap((line) => {
      const cells = line.split("|").map((cell) => cell.trim());
      return cells.length === 2 && label.test(cells[0]) && cells[1] ? [cells[1]] : [];
    });
    return values.length === 1 ? values[0] : null;
  };
  const disclosedScope = exactText(/^범위$/);
  // 공식 원문으로 확인한 인수 전후 범위는 재수집해도 같은 시계열로 연결하지 않는다.
  const boundary = record(row.sections["수주 범위 변경 근거"]);
  const overrideScope = boundary && period?.end === boundary.effectivePeriodEnd &&
    disclosedScope === boundary.fromScope && typeof boundary.toScope === "string" &&
    boundary.toScope.trim() && typeof boundary.sourceUrl === "string" && boundary.sourceUrl.startsWith("https://") &&
    typeof boundary.sha256 === "string" && /^[a-f0-9]{64}$/.test(boundary.sha256)
    ? boundary.toScope : null;
  return { year: period?.year ?? row.fiscal_year!, quarter: period?.quarter ?? row.fiscal_quarter!, rceptNo: row.rcept_no,
    backlogEok, newOrdersEok,
    ...(!krw ? { amountUnit, backlogAmount, newOrdersAmount } : {}),
    scope: overrideScope ?? disclosedScope ?? "공시 명시 수치",
    newOrdersPeriod: exactText(/^신규\s*수주\s*기간$/),
    ...(exactText(/^출처$/)?.startsWith("https://") ? {
      sourceUrl: exactText(/^출처$/)!, sourceLabel: exactText(/^자료명$/) ?? "공식 IR",
      sourcePage: exactText(/^출처 페이지$/) ?? undefined,
      newOrdersSourceUrl: exactText(/^신규수주 출처$/) ?? undefined,
    } : {}),
    ...(period ? { periodEnd: period.end, periodLabel: period.label, closingMonth: period.closingMonth } : {}),
  };
}

/** 서로 다른 연결회사/사업부의 원문 표를 합산하거나 한 점으로 덮어쓰지 않는다. */
export function extractOrderDisclosureMetrics(row: DisclosureExcerptRow): OrderDisclosureMetric[] {
  const series = record(row.sections?.["공시 수주지표 목록"])?.series;
  const irSeries = record(row.sections?.["공식 IR 수주지표"])?.series;
  const irMetrics = (Array.isArray(irSeries) ? irSeries : []).flatMap((section) => {
    if (typeof section !== "string") return [];
    const metric = extractOrderDisclosureMetric({ ...row, sections: { ...row.sections, "공시 수주지표": section } });
    return metric ? [metric] : [];
  });
  if (!Array.isArray(series)) {
    const metric = extractOrderDisclosureMetric(row);
    return [...(metric ? [metric] : []), ...irMetrics];
  }
  return [...series.flatMap((section) => {
    if (typeof section !== "string") return [];
    const metric = extractOrderDisclosureMetric({ ...row, sections: { ...row.sections, "공시 수주지표": section } });
    return metric ? [metric] : [];
  }), ...irMetrics];
}

export function summarizeOrderDisclosures(row: DisclosureExcerptRow): OrderDisclosureSummary[] {
  if (record(row.sections?.["공식 IR 수주지표"])) {
    return extractOrderDisclosureMetrics(row).map((metric) => ({ ...metric,
      status: "measured", statusLabel: metric.sourceUrl ? "공식 IR 수치 확인" : "공시 수치 확인", evidence: null }));
  }
  const series = record(row.sections?.["공시 수주지표 목록"])?.series;
  if (!Array.isArray(series)) {
    const summary = summarizeOrderDisclosure(row);
    return summary ? [summary] : [];
  }
  return series.flatMap((section) => {
    if (typeof section !== "string") return [];
    const summary = summarizeOrderDisclosure({ ...row, sections: { ...row.sections, "공시 수주지표": section } });
    return summary ? [summary] : [];
  });
}

/** 최근 6개월 중 최근 정기보고서 이후이면서 현재 분기에 속한 계약만 남긴다. */
export function currentQuarterPostReportContracts(
  rows: OrderContractDisclosure[],
  basisDate: string,
  latestPeriodicReportDate: string | null,
): OrderContractDisclosure[] {
  if (!latestPeriodicReportDate || !/^\d{4}-\d{2}-\d{2}$/.test(basisDate)) return [];
  const basis = new Date(`${basisDate}T00:00:00Z`);
  if (Number.isNaN(basis.getTime())) return [];
  const sixMonthsAgo = new Date(basis);
  sixMonthsAgo.setUTCMonth(sixMonthsAgo.getUTCMonth() - 6);
  const quarterMonth = Math.floor(basis.getUTCMonth() / 3) * 3;
  const quarterStart = `${basis.getUTCFullYear()}-${String(quarterMonth + 1).padStart(2, "0")}-01`;
  const sixMonthsAgoIso = sixMonthsAgo.toISOString().slice(0, 10);
  return rows.filter((row) => row.disclosedAt != null &&
    row.disclosedAt >= sixMonthsAgoIso && row.disclosedAt >= quarterStart &&
    row.disclosedAt > latestPeriodicReportDate && row.disclosedAt <= basisDate);
}

/** 실제 정기보고서 제목의 종료월. 비12월 결산도 달력 Q로 환산하지 않는다. */
export function reportNamePeriodEnd(reportName: string | null): string | null {
  if (isAttachmentOnlyCorrection(reportName) || !/사업보고서|반기보고서|분기보고서/.test(reportName ?? "")) return null;
  const match = reportName?.match(/\((\d{4})[.\-/](\d{2})\)/);
  if (!match) return null;
  const year = Number(match[1]), month = Number(match[2]);
  if (month < 1 || month > 12) return null;
  return new Date(Date.UTC(year, month, 0)).toISOString().slice(0, 10);
}

/** 발표일이 아니라 실제 보고기간 종료일 이후의 공개 계약. 정정/해지도 표에는 보존한다. */
export function postPeriodContracts(rows: OrderContractDisclosure[], basisDate: string, periodEnd: string | null): OrderContractDisclosure[] {
  const validDate = (value: string | null): value is string => value != null && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(new Date(`${value}T00:00:00Z`).getTime()) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
  if (!validDate(basisDate) || !validDate(periodEnd) || periodEnd >= basisDate) return [];
  const cutoff = new Date(`${basisDate}T00:00:00Z`);
  const day = cutoff.getUTCDate();
  cutoff.setUTCDate(1);
  cutoff.setUTCMonth(cutoff.getUTCMonth() - 6);
  const lastDay = new Date(Date.UTC(cutoff.getUTCFullYear(), cutoff.getUTCMonth() + 1, 0)).getUTCDate();
  cutoff.setUTCDate(Math.min(day, lastDay));
  const from = cutoff.toISOString().slice(0, 10);
  return rows.filter((row) => validDate(row.disclosedAt) && row.disclosedAt > periodEnd && row.disclosedAt >= from && row.disclosedAt <= basisDate);
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
  const summary = summarizeOrderDisclosureBase(row);
  const period = readOrderReportPeriod(row);
  return summary && period ? { ...summary, periodEnd: period.end, periodLabel: period.label } : summary;
}

function summarizeOrderDisclosureBase(row: DisclosureExcerptRow): OrderDisclosureSummary | null {
  const period = readOrderReportPeriod(row);
  if (period) row = { ...row, fiscal_year: period.year, fiscal_quarter: period.quarter };
  if (row.fiscal_year == null || row.fiscal_quarter == null || !row.rcept_no) return null;
  const metric = extractOrderDisclosureMetric(row);
  const signal = deriveOrderDisclosureSignal(row, row.fiscal_year, row.fiscal_quarter);
  if (metric) return {
    year: row.fiscal_year, quarter: row.fiscal_quarter, rceptNo: row.rcept_no,
    backlogEok: metric.backlogEok, newOrdersEok: metric.newOrdersEok, scope: metric.scope,
    newOrdersPeriod: metric.newOrdersPeriod,
    ...(metric.amountUnit ? { amountUnit: metric.amountUnit, backlogAmount: metric.backlogAmount,
      newOrdersAmount: metric.newOrdersAmount } : {}),
    status: "measured", statusLabel: "공시 수치 확인", evidence: signal?.evidence ?? null,
  };
  const evidence = signal?.evidence ?? null;
  if (signal?.status === "limited" && evidence && /해당사항\s*없음|수주산업.{0,12}아니/.test(evidence)) {
    return { year: row.fiscal_year, quarter: row.fiscal_quarter, rceptNo: row.rcept_no,
      backlogEok: null, newOrdersEok: null, scope: null, newOrdersPeriod: null, status: "not_applicable",
      statusLabel: "해당 없음", evidence };
  }
  if (signal?.status === "limited") return {
    year: row.fiscal_year, quarter: row.fiscal_quarter, rceptNo: row.rcept_no,
    backlogEok: null, newOrdersEok: null, scope: null, newOrdersPeriod: null, status: "private",
    statusLabel: "비공개·기재 생략", evidence,
  };
  if (signal?.truncated) return {
    year: row.fiscal_year, quarter: row.fiscal_quarter, rceptNo: row.rcept_no,
    backlogEok: null, newOrdersEok: null, scope: null, newOrdersPeriod: null, status: "truncated",
    statusLabel: "발췌 범위 밖·원문 확인 필요", evidence,
  };
  if (signal) return {
    year: row.fiscal_year, quarter: row.fiscal_quarter, rceptNo: row.rcept_no,
    backlogEok: null, newOrdersEok: null, scope: null, newOrdersPeriod: null, status: "mentioned",
    statusLabel: "수주 언급·단일 수치 미확인", evidence,
  };
  return {
    year: row.fiscal_year, quarter: row.fiscal_quarter, rceptNo: row.rcept_no,
    backlogEok: null, newOrdersEok: null, scope: null, newOrdersPeriod: null, status: "unmentioned",
    statusLabel: "정기보고서에서 수주 수치 미확인", evidence: null,
  };
}
