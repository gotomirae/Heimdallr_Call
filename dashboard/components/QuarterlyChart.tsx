"use client";
// PRD Ref: §9.1-3 — 9분기 실적 추이. 값 라벨과 요청 순서를 화면 계약으로 둔다.
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  LabelList,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { SERIES_COLOR, type ChartPoint } from "@/lib/chart";

const tooltipStyle = { backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: 6 };

function fmt(value: unknown, unit: "억" | "%"): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const shown = value.toLocaleString("ko-KR", { maximumFractionDigits: 1 });
  return `${value > 0 && unit === "%" ? "+" : ""}${shown}${unit}`;
}

function valueLabel(unit: "억" | "%") {
  return (value: unknown) => fmt(value, unit);
}

function lineLabel(color: string, unit: "억" | "%", dy: number) {
  return (props: Record<string, unknown>) => {
    const { x, y, value } = props;
    if (typeof value !== "number" || !Number.isFinite(value)) return null;
    return <text x={Number(x)} y={Number(y) + dy} fill={color} fontSize={9} fontWeight={700} textAnchor="middle">{fmt(value, unit)}</text>;
  };
}

function Axis({ percent = false }: { percent?: boolean }) {
  return <YAxis width={45} domain={["auto", "auto"]} stroke="#94a3b8" fontSize={9} tickFormatter={(v) => percent ? `${Number(v).toFixed(0)}%` : Number(v).toLocaleString("ko-KR")} />;
}

function QuarterAxis() {
  return <XAxis dataKey="label" stroke="#94a3b8" fontSize={9} tickLine={false} />;
}

function RevenuePanel({ points }: { points: ChartPoint[] }) {
  return <div className="rounded border border-slate-800 bg-slate-950/30 p-2 md:col-span-2">
    <div className="mb-1 flex items-center justify-between text-xs"><strong className="text-slate-100">매출액</strong><span className="text-slate-400">억원</span></div>
    <div className="h-40"><ResponsiveContainer width="100%" height="100%"><BarChart data={points} margin={{ top: 24, right: 5, bottom: 0, left: 0 }}>
      <CartesianGrid stroke="#1e293b" vertical={false} /><QuarterAxis /><Axis />
      <Tooltip formatter={(v) => [fmt(v, "억"), "매출액"]} contentStyle={tooltipStyle} />
      <Bar dataKey="revenue" name="매출액" fill="#2563eb" isAnimationActive={false}><LabelList dataKey="revenue" position="top" fill="#e2e8f0" fontSize={9} formatter={valueLabel("억")} /></Bar>
    </BarChart></ResponsiveContainer></div>
  </div>;
}

function EarningsPanel({ points }: { points: ChartPoint[] }) {
  return <div className="rounded border border-slate-800 bg-slate-950/30 p-2 md:col-span-2">
    <div className="mb-1 flex items-center justify-between text-xs"><strong className="text-slate-100">영업이익 · OPM</strong><span className="text-slate-400">억원 · %</span></div>
    <div className="h-52"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={points} margin={{ top: 32, right: 10, bottom: 0, left: 0 }}>
      <CartesianGrid stroke="#1e293b" vertical={false} /><QuarterAxis />
      <YAxis yAxisId="amount" width={45} domain={["auto", "auto"]} stroke="#94a3b8" fontSize={9} tickFormatter={(v) => Number(v).toLocaleString("ko-KR")} />
      <YAxis yAxisId="percent" orientation="right" width={40} domain={["auto", "auto"]} stroke={SERIES_COLOR.OPM_COLOR} fontSize={9} tickFormatter={(v) => `${Number(v).toFixed(0)}%`} />
      <Tooltip formatter={(v, name) => [fmt(v, name === "OPM" ? "%" : "억"), name]} contentStyle={tooltipStyle} /><Legend wrapperStyle={{ fontSize: 11 }} />
      <Bar yAxisId="amount" dataKey="op" name="영업이익" fill="#0891b2" isAnimationActive={false}><LabelList dataKey="op" position="top" fill="#bae6fd" fontSize={9} formatter={valueLabel("억")} /></Bar>
      <Line yAxisId="percent" dataKey="opm" name="OPM" stroke={SERIES_COLOR.OPM_COLOR} strokeWidth={2.5} dot={{ r: 3 }} connectNulls={false} isAnimationActive={false}><LabelList dataKey="opm" content={(p) => lineLabel(SERIES_COLOR.OPM_COLOR, "%", -17)({ ...p })} /></Line>
    </ComposedChart></ResponsiveContainer></div>
  </div>;
}

/* 성장률은 단위가 같아 한 축에서 두 계열의 가속 방향을 직접 비교한다. */
function GrowthPanel({ points }: { points: ChartPoint[] }) {
  return <div className="rounded border border-slate-800 bg-slate-950/30 p-2 md:col-span-2">
    <div className="mb-1 flex items-center justify-between text-xs"><strong className="text-slate-100">매출 YoY · 영업이익 YoY</strong><span className="text-slate-400">%</span></div>
    <div className="h-52"><ResponsiveContainer width="100%" height="100%"><LineChart data={points} margin={{ top: 32, right: 10, bottom: 0, left: 0 }}>
      <CartesianGrid stroke="#1e293b" vertical={false} /><QuarterAxis /><Axis percent />
      <Tooltip formatter={(v, name) => [fmt(v, "%"), name]} contentStyle={tooltipStyle} /><Legend wrapperStyle={{ fontSize: 11 }} />
      <Line dataKey="revenueYoy" name="매출 YoY" stroke={SERIES_COLOR.REVENUE_COLOR} strokeWidth={2.5} dot={{ r: 3 }} connectNulls={false} isAnimationActive={false}><LabelList dataKey="revenueYoy" content={(p) => lineLabel(SERIES_COLOR.REVENUE_LABEL, "%", -9)({ ...p })} /></Line>
      <Line dataKey="opYoy" name="영업이익 YoY" stroke={SERIES_COLOR.OP_COLOR} strokeWidth={2.5} dot={{ r: 3 }} connectNulls={false} isAnimationActive={false}><LabelList dataKey="opYoy" content={(p) => lineLabel(SERIES_COLOR.OP_LABEL, "%", -21)({ ...p })} /></Line>
    </LineChart></ResponsiveContainer></div>
  </div>;
}

function OrdersPanel({ points }: { points: ChartPoint[] }) {
  const measured = points.some((p) => p.orderBacklog != null || p.newOrders != null);
  return <div className="rounded border border-slate-800 bg-slate-950/30 p-2 md:col-span-2">
    <div className="mb-1 flex items-center justify-between text-xs"><strong className="text-slate-100">수주잔고 · 신규수주</strong><span className="text-slate-400">억원</span></div>
    {!measured ? <div className="flex h-40 items-center justify-center text-xs text-slate-400">공개 자료의 구조화 수치 미수집</div> : <div className="h-40"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={points} margin={{ top: 24, right: 5, bottom: 0, left: 0 }}>
      <CartesianGrid stroke="#1e293b" vertical={false} /><QuarterAxis /><Axis /><Tooltip formatter={(v, name) => [fmt(v, "억"), name]} contentStyle={tooltipStyle} /><Legend wrapperStyle={{ fontSize: 11 }} />
      <Bar dataKey="orderBacklog" name="수주잔고" fill="#a78bfa" isAnimationActive={false}><LabelList dataKey="orderBacklog" position="top" fill="#ddd6fe" fontSize={9} formatter={valueLabel("억")} /></Bar>
      <Bar dataKey="newOrders" name="신규수주" fill="#fb7185" isAnimationActive={false}><LabelList dataKey="newOrders" position="top" fill="#fecdd3" fontSize={9} formatter={valueLabel("억")} /></Bar>
    </ComposedChart></ResponsiveContainer></div>}
  </div>;
}

export default function QuarterlyChart({ points }: { points: ChartPoint[] }) {
  if (!points.length) return <p className="py-8 text-center text-sm text-slate-300">분기 재무가 아직 없다.</p>;
  return <div className="grid gap-3 md:grid-cols-2">
    <RevenuePanel points={points} />
    <EarningsPanel points={points} />
    <GrowthPanel points={points} />
    <OrdersPanel points={points} />
  </div>;
}
