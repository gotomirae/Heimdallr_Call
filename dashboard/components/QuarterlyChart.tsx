"use client";
// PRD Ref: §9.1-3 — 9분기 실적 추이. 서로 다른 단위는 항목별 축으로 그린다.
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { SERIES_COLOR, type ChartPoint } from "@/lib/chart";

type NumericKey = "revenue" | "revenueYoy" | "op" | "opYoy" | "opm";
const SERIES: Array<{ label: string; key: NumericKey | "orderBacklog" | "newOrders"; unit: "억" | "%"; color: string; kind: "bar" | "line" }> = [
  { label: "매출", key: "revenue", unit: "억", color: "#2563eb", kind: "bar" },
  { label: "매출 YoY", key: "revenueYoy", unit: "%", color: SERIES_COLOR.REVENUE_COLOR, kind: "line" },
  { label: "영업이익", key: "op", unit: "억", color: "#0891b2", kind: "bar" },
  { label: "영업이익 YoY", key: "opYoy", unit: "%", color: SERIES_COLOR.OP_COLOR, kind: "line" },
  { label: "OPM", key: "opm", unit: "%", color: SERIES_COLOR.OPM_COLOR, kind: "line" },
  { label: "수주잔고", key: "orderBacklog", unit: "억", color: "#a78bfa", kind: "bar" },
  { label: "신규수주", key: "newOrders", unit: "억", color: "#fb7185", kind: "bar" },
];

function fmt(value: unknown, unit: string): string {
  return typeof value === "number" && Number.isFinite(value) ? `${value.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}${unit}` : "—";
}

function SeriesPanel({ points, series }: { points: ChartPoint[]; series: (typeof SERIES)[number] }) {
  const measured = points.some((point) => series.key in point && typeof point[series.key as NumericKey] === "number");
  return <div className="rounded border border-slate-800 bg-slate-950/30 p-2">
    <div className="mb-1 flex items-center justify-between text-xs"><strong className="text-slate-100">{series.label}</strong><span className="text-slate-400">{series.unit}</span></div>
    {!measured ? <div className="flex h-32 items-center justify-center text-xs text-slate-400">공개 자료의 구조화 수치 미수집</div> : <div className="h-32"><ResponsiveContainer width="100%" height="100%">
      {series.kind === "bar" ? <BarChart data={points} margin={{ top: 5, right: 4, bottom: 0, left: 0 }}><CartesianGrid stroke="#1e293b" vertical={false} /><XAxis dataKey="label" stroke="#94a3b8" fontSize={9} tickLine={false} /><YAxis width={42} stroke="#94a3b8" fontSize={9} tickFormatter={(v) => Number(v).toLocaleString("ko-KR")} /><Tooltip formatter={(v) => [fmt(v, series.unit), series.label]} contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: 6 }} /><Bar dataKey={series.key} fill={series.color} isAnimationActive={false} /></BarChart>
      : <LineChart data={points} margin={{ top: 5, right: 4, bottom: 0, left: 0 }}><CartesianGrid stroke="#1e293b" vertical={false} /><XAxis dataKey="label" stroke="#94a3b8" fontSize={9} tickLine={false} /><YAxis width={42} domain={["auto", "auto"]} stroke="#94a3b8" fontSize={9} tickFormatter={(v) => `${Number(v).toFixed(0)}%`} /><Tooltip formatter={(v) => [fmt(v, series.unit), series.label]} contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: 6 }} /><Line dataKey={series.key} stroke={series.color} strokeWidth={2.5} dot={{ r: 3 }} connectNulls={false} isAnimationActive={false} /></LineChart>}
    </ResponsiveContainer></div>}
  </div>;
}

export default function QuarterlyChart({ points }: { points: ChartPoint[] }) {
  if (!points.length) return <p className="py-8 text-center text-sm text-slate-300">분기 재무가 아직 없다.</p>;
  return <div className="grid gap-3 md:grid-cols-2">{SERIES.map((series) => <SeriesPanel key={series.key} points={points} series={series} />)}</div>;
}
