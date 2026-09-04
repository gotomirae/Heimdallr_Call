"use client";
// PRD Ref: §9.1-3 — 실제 주간 종가 + MACD + RSI
import { Bar, CartesianGrid, ComposedChart, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { technicalIndicators } from "@/lib/technicalIndicators";
import type { WeeklyPriceRow } from "@/lib/types";

const tooltipStyle = { backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: 6 };
export default function WeeklyPriceChart({ points, fromDate }: { points: WeeklyPriceRow[]; fromDate?: string }) {
  const visible = technicalIndicators(points).filter((point) => !fromDate || point.trade_date >= fromDate);
  if (!visible.length) return <p className="py-5 text-center text-sm text-slate-300">같은 기간의 주간 종가를 아직 수집하지 않았다.</p>;
  return <div id="weekly-technical" className="mt-5 space-y-4">
    <div><div className="mb-1 text-xs font-semibold text-slate-200">실제 주간 종가</div><div className="h-52"><ResponsiveContainer width="100%" height="100%"><LineChart data={visible}><CartesianGrid stroke="#1e293b" vertical={false} /><XAxis dataKey="trade_date" stroke="#94a3b8" fontSize={9} minTickGap={42} /><YAxis domain={["auto", "auto"]} stroke="#94a3b8" fontSize={9} tickFormatter={(v) => Number(v).toLocaleString("ko-KR")} /><Tooltip formatter={(v) => [`${Number(v).toLocaleString("ko-KR")}원`, "주간 종가"]} contentStyle={tooltipStyle} /><Line dataKey="close" stroke="#ef4444" strokeWidth={2} dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div></div>
    <div><div className="mb-1 text-xs font-semibold text-slate-200">MACD (12·26·9)</div><div className="h-44"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={visible}><CartesianGrid stroke="#1e293b" vertical={false} /><XAxis dataKey="trade_date" stroke="#94a3b8" fontSize={9} minTickGap={42} /><YAxis domain={["auto", "auto"]} stroke="#94a3b8" fontSize={9} /><ReferenceLine y={0} stroke="#64748b" /><Tooltip contentStyle={tooltipStyle} /><Bar dataKey="histogram" name="히스토그램" fill="#475569" isAnimationActive={false} /><Line dataKey="macd" name="MACD" stroke="#38bdf8" dot={false} isAnimationActive={false} /><Line dataKey="signal" name="Signal" stroke="#f59e0b" dot={false} isAnimationActive={false} /></ComposedChart></ResponsiveContainer></div></div>
    <div><div className="mb-1 text-xs font-semibold text-slate-200">RSI (14)</div><div className="h-40"><ResponsiveContainer width="100%" height="100%"><LineChart data={visible}><CartesianGrid stroke="#1e293b" vertical={false} /><XAxis dataKey="trade_date" stroke="#94a3b8" fontSize={9} minTickGap={42} /><YAxis domain={[0, 100]} ticks={[30, 45, 70]} stroke="#94a3b8" fontSize={9} /><ReferenceLine y={70} stroke="#ef4444" strokeDasharray="3 3" /><ReferenceLine y={45} stroke="#facc15" strokeDasharray="3 3" /><ReferenceLine y={30} stroke="#38bdf8" strokeDasharray="3 3" /><Tooltip formatter={(v) => [Number(v).toFixed(1), "RSI"]} contentStyle={tooltipStyle} /><Line dataKey="rsi" stroke="#c084fc" strokeWidth={2} dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div></div>
  </div>;
}
