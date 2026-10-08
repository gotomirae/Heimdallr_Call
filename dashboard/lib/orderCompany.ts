// PRD Ref: §9.1-3 — 기업 분류와 숫자 확보 여부를 독립적으로 판정한다.
import { attachOrderReportPoints, sortOrderChartSeries, withOrderBacklogQoq } from "./chart";
import { extractOrderContractDisclosure, extractOrderDisclosureMetrics, readOrderReportPeriod } from "./orderSignals";
import type { DisclosureExcerptRow, OrderDisclosureMetric } from "./orderSignals";

export interface OrderCompanyAudit {
  code: string; name: string; sector: string | null;
  status: "confirmed" | "not_applicable" | "review";
  basis: string; evidence: string; sourceUrl: string | null;
  generatedAt: string; anchorReceipt: string | null; latestPeriod: string | null;
  reportCount: number;
  irResearch?: { documents: number; candidates: number; failures: number; throughDate: string; verifiedFacts: number };
  series: { scope: string; unit: string; period: string; backlog: number | null;
    newOrders: number | null; qoq: number | null; complete: boolean;
    missing: string[]; sourceUrl: string; history: { backlog: number; newOrders: number; qoq: number; complete: number } }[];
}

function period(row: DisclosureExcerptRow): string {
  return readOrderReportPeriod(row)?.end ?? `${row.fiscal_year}-${String(Number(row.fiscal_quarter) * 3).padStart(2, "0")}`;
}
function metricPeriod(m: OrderDisclosureMetric): string {
  return (m.periodEnd ?? `${m.year}-${String(m.quarter * 3).padStart(2, "0")}`).slice(0, 7);
}
const dartUrl = (receipt: string) => `https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${receipt}`;

export function auditOrderCompany(company: { code: string; name: string; sector?: string | null; irResearch?: OrderCompanyAudit["irResearch"] }, rows: DisclosureExcerptRow[], generatedAt: string): OrderCompanyAudit {
  const periodic = rows.filter(r => (readOrderReportPeriod(r) || r.fiscal_year && r.fiscal_quarter) && r.sections?.["공시 수주지표 확인"])
    .sort((a, b) => period(b).localeCompare(period(a)) || b.rcept_no.localeCompare(a.rcept_no));
  const latest = periodic[0];
  const latestPeriod = latest ? period(latest).slice(0, 7) : null;
  const metrics = periodic.flatMap(extractOrderDisclosureMetrics);
  const fullEvidence = periodic.map(row => ({ row, value: row.sections?.order_business_evidence as { status?: string; basis?: string; evidence?: string } | undefined }));
  const positive = fullEvidence.find(e => e.value?.status === "confirmed");
  const latestEvidence = fullEvidence[0]?.value;
  const contract = [...rows].sort((a, b) => b.rcept_no.localeCompare(a.rcept_no)).find(r => extractOrderContractDisclosure(r));
  let status: OrderCompanyAudit["status"] = "review";
  let basis = "수주기업 여부 확인 필요: 정기보고서 수주 절과 공식 IR 조사 대상";
  let evidence = ""; let sourceUrl: string | null = null;
  if (metrics.length || positive || contract) {
    status = "confirmed";
    basis = metrics.length ? "정기보고서·공식 IR 수주 수치 확인" : positive?.value?.basis ?? "단일판매·공급계약 공시 확인 (전체 수주량은 별도 조사)";
    evidence = positive?.value?.evidence ?? (metrics[0]?.scope || "공개 공급계약 존재");
    sourceUrl = metrics[0]?.sourceUrl ?? dartUrl(metrics[0]?.rceptNo ?? positive?.row.rcept_no ?? contract!.rcept_no);
    if (latestEvidence?.status === "not_applicable" && !metrics.some(m => metricPeriod(m) === latestPeriod)) {
      status = "review"; basis = "과거 수주 근거와 최신 비수주 문구가 다름: 사업 변경·범위 재확인 필요";
    }
  } else if (latestEvidence?.status === "not_applicable") {
    status = "not_applicable"; basis = latestEvidence.basis ?? "최신 원문 수주사업 비해당 명시";
    evidence = latestEvidence.evidence ?? ""; sourceUrl = dartUrl(latest.rcept_no);
  } else if (latestEvidence) {
    basis = latestEvidence.basis ?? basis; evidence = latestEvidence.evidence ?? ""; sourceUrl = dartUrl(latest.rcept_no);
  }
  const groups = new Map<string, Map<string, OrderDisclosureMetric>>();
  for (const metric of metrics) {
    const key = `${metric.scope}\u0000${metric.amountUnit ?? "억원"}`;
    const values = groups.get(key) ?? new Map<string, OrderDisclosureMetric>();
    const p = metricPeriod(metric);
    if (!values.has(p) || values.get(p)!.rceptNo < metric.rceptNo) values.set(p, metric);
    groups.set(key, values);
  }
  const ranked = sortOrderChartSeries([...groups.values()].map(values => {
    const reports = [...values.values()].sort((a, b) => metricPeriod(a).localeCompare(metricPeriod(b))).slice(-10);
    return { reports, points: withOrderBacklogQoq(attachOrderReportPoints([], reports)) };
  }));
  const series = ranked.map(({ reports, points }) => {
    const newest = points[points.length - 1];
    const newestReport = reports[reports.length - 1];
    const current = metricPeriod(newestReport) === latestPeriod;
    const missing: string[] = [];
    if (!current) missing.push("최신 정기보고서 기간의 수치 미확보");
    if (newest.orderBacklog == null) missing.push("수주잔고 미확보: 공시표·단위·범위 추가 대조 필요");
    if (newest.newOrders == null) missing.push(newest.newOrdersStatus && newest.newOrdersStatus !== "원문 신규수주 미공개"
      ? newest.newOrdersStatus : "신규수주 직접값 미확보: 원문표·그림·기업 IR 추가 조사 필요");
    if (newest.orderBacklogQoq == null) missing.push("QoQ 미확보: 같은 범위·통화의 연속 분기 잔고 필요");
    return { scope: newestReport.scope, unit: newestReport.amountUnit ?? "억원", period: metricPeriod(newestReport),
      backlog: newest.orderBacklog, newOrders: newest.newOrders, qoq: newest.orderBacklogQoq,
      complete: current && newest.orderBacklog != null && newest.newOrders != null && newest.orderBacklogQoq != null,
      missing, sourceUrl: newestReport.sourceUrl ?? dartUrl(newestReport.rceptNo),
      history: { backlog: points.filter(p => p.orderBacklog != null).length, newOrders: points.filter(p => p.newOrders != null).length,
        qoq: points.filter(p => p.orderBacklogQoq != null).length,
        complete: points.filter(p => p.orderBacklog != null && p.newOrders != null && p.orderBacklogQoq != null).length } };
  });
  return { code: company.code, name: company.name, sector: company.sector ?? null, status, basis, evidence, sourceUrl,
    generatedAt, anchorReceipt: latest?.rcept_no ?? rows[0]?.rcept_no ?? null, latestPeriod, reportCount: periodic.length, series,
    ...(company.irResearch ? { irResearch: company.irResearch } : {}) };
}
