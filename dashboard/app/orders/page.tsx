// PRD Ref: §9.1-3 — 수주기업을 먼저 분류하고 그 명단의 확보 상태를 표시한다.
import { getOrderCompanyAudits, getUniverse } from "@/lib/queries";
import OrderCompanies from "@/components/OrderCompanies";
import constants from "@/lib/constants.json";
export const dynamic = "force-dynamic";

export default async function OrdersPage() {
  const universe = await getUniverse();
  const companies = [...universe.values()].filter(u => !u.is_excluded && (u.market_cap_krw ?? 0) >= constants.gate.market_cap_floor_krw);
  const audits = await getOrderCompanyAudits(companies.map(u => u.code));
  const indexed = new Map(audits.map(a => [a.code, a]));
  const rows = companies.map(u => indexed.get(u.code) ?? {
    code: u.code, name: u.name ?? u.code, sector: u.sector ?? null, status: "review" as const,
    basis: "수주기업 분류 장부 미수집: 원문 조사 필요", evidence: "", sourceUrl: null,
    generatedAt: "", anchorReceipt: null, latestPeriod: null, reportCount: 0, series: [],
  });
  return <main className="mx-auto max-w-[1600px] px-4 py-6 text-white">
    <h1 className="text-2xl font-black">수주기업 · 분기 수주 조사</h1>
    <p className="my-3 text-sm leading-6">정기보고서 수주표·공식 IR·공급계약을 근거로 먼저 분류합니다. 수치 결측은 비수주 판정의 근거가 아닙니다.
      각 기업의 최신 정기보고서 기간에서 같은 범위·통화의 수주잔고, 분기 신규수주, 잔고 QoQ를 대조합니다. 사업부·주요계약 범위를 회사 전체로 합치지 않습니다.</p>
    <OrderCompanies rows={rows} />
  </main>;
}
