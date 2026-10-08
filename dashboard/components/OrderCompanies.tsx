"use client";
// PRD Ref: §9.1-3
import { useState } from "react";
import Link from "next/link";
import type { OrderCompanyAudit } from "@/lib/orderCompany";

const labels = { confirmed: "수주 확인", review: "확인 필요", not_applicable: "비수주 명시" };
const amount = (v: number | null | undefined) => v == null ? "미확보" : v.toLocaleString("ko-KR", { maximumFractionDigits: 8 });

export default function OrderCompanies({ rows }: { rows: OrderCompanyAudit[] }) {
  const [status, setStatus] = useState("confirmed");
  const [search, setSearch] = useState("");
  const [missingOnly, setMissingOnly] = useState(false);
  const [limit, setLimit] = useState(50);
  const visible = rows.filter(r => (status === "all" || r.status === status) &&
    (!missingOnly || !r.series.some(s => s.complete)) && `${r.name} ${r.code} ${r.sector ?? ""}`.includes(search))
    .sort((a, b) => Number(a.series.some(s => s.complete)) - Number(b.series.some(s => s.complete)) || a.code.localeCompare(b.code));
  const date = rows.map(r => r.generatedAt).sort().at(-1);
  return <>
    <div className="flex flex-wrap gap-3 rounded-xl border border-white/30 p-4 text-sm">
      <span>대상 {rows.length}기업</span>
      {Object.entries(labels).map(([key, label]) => <span key={key}>{label} {rows.filter(r => r.status === key).length}</span>)}
      <span className="text-emerald-200">최신 기간 세 항목 확보 {rows.filter(r => r.status === "confirmed" && r.series.some(s => s.complete)).length}기업 (부분 범위 포함)</span>
      <span>장부 갱신 {date ? new Date(date).toLocaleString("ko-KR") : "미실행"}</span>
    </div>
    <div className="my-4 flex flex-wrap items-center gap-3">
      <select aria-label="수주기업 분류" className="rounded bg-slate-800 p-2" value={status} onChange={e => setStatus(e.target.value)}>
        <option value="all">전체</option>{Object.entries(labels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select>
      <input aria-label="기업 검색" placeholder="기업명·코드·섹터 검색" className="rounded bg-slate-800 p-2" value={search} onChange={e => setSearch(e.target.value)} />
      <label><input type="checkbox" checked={missingOnly} onChange={e => setMissingOnly(e.target.checked)} className="mr-2" />세 항목 미확보 기업만</label>
      <span>{visible.length}기업 표시</span>
    </div>
    <div className="overflow-x-auto"><table className="w-full min-w-[1000px] text-left text-sm">
      <thead className="bg-slate-800"><tr>{["기업·분류", "분류 근거", "보고 기간·범위", "수주잔고", "분기 신규수주", "잔고 QoQ", "추가 조사"].map(t => <th className="p-3" key={t}>{t}</th>)}</tr></thead>
      <tbody>{visible.slice(0, limit).map(r => { const s = r.series[0]; return <tr key={r.code} className="border-b border-white/20 align-top">
        <td className="p-3"><Link className="font-bold text-sky-200 underline" href={`/stock/${r.code}`}>{r.name}</Link><p>{r.code} · {labels[r.status]}</p><p>{r.sector}</p></td>
        <td className="max-w-[260px] p-3">{r.basis}<p className="mt-1 text-xs">{r.evidence}</p>{r.sourceUrl && <a className="text-sky-200 underline" href={r.sourceUrl} target="_blank" rel="noreferrer">분류 원문</a>}</td>
        <td className="max-w-[220px] p-3">최신 보고기간 {r.latestPeriod ?? "미확인"}<p>{s?.period} · {s?.scope ?? "금액 범위 조사 필요"}</p>{s && <><p>단위 {s.unit} · {r.series.length}개 범위 (상세에서 각각 표시)</p><a className="text-sky-200 underline" href={s.sourceUrl} target="_blank" rel="noreferrer">수치 원문</a></>}</td>
        <td className="p-3">{amount(s?.backlog)}</td><td className="p-3">{amount(s?.newOrders)}</td>
        <td className="p-3">{s?.qoq == null ? "미확보" : `${s.qoq.toFixed(2)}%`}</td>
        <td className="max-w-[280px] p-3">{s?.complete ? "동일 범위의 최신 세 항목 확보" : s?.missing.join(" · ") || (r.status === "not_applicable" ? "비수주 근거 확인; 사업 변경 시 재분류" : "수주 절 전체·기업 IR에서 잔고 및 신규수주 직접값 조사 필요")}
          {s && <p className="mt-1 text-xs">최근 10분기 확보점: 잔고 {s.history.backlog} / 신규 {s.history.newOrders} / QoQ {s.history.qoq}</p>}
          {r.irResearch && <p className="mt-1 text-xs">KIND IR 조사 {r.irResearch.documents}파일 · 수주 후보 {r.irResearch.candidates} · 조회 실패 {r.irResearch.failures} ({r.irResearch.throughDate}까지). 검증 IR 수치 {r.irResearch.verifiedFacts}점. {r.irResearch.documents === 0 && r.irResearch.verifiedFacts === 0 && "회사별 자료실 추가 조사 필요."}</p>}
          <Link className="mt-2 block text-sky-200 underline" href={`/stock/${r.code}#orders`}>분기 그래프·원문 보기</Link>
        </td>
      </tr>; })}</tbody>
    </table></div>
    {visible.length > limit && <button onClick={() => setLimit(n => n + 50)} className="my-4 rounded border border-white/40 px-5 py-2">50기업 더 보기 ({Math.min(limit, visible.length)}/{visible.length})</button>}
  </>;
}
