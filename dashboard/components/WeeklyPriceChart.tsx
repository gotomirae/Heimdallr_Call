"use client";
// PRD Ref: §9.1-3 — 실제 거래일 기준 주간 종가
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { WeeklyPriceRow } from "@/lib/types";

export default function WeeklyPriceChart({ points, fromDate }: { points: WeeklyPriceRow[]; fromDate?: string }) {
  const visible = fromDate ? points.filter((point) => point.trade_date >= fromDate) : points;
  if (!visible.length) return <p className="py-5 text-center text-sm text-slate-300">같은 기간의 주간 종가를 아직 수집하지 않았다.</p>;
  return (
    <div className="mt-5 h-56 w-full">
      <div className="mb-1 text-xs font-semibold text-slate-200">실제 주간 종가</div>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={visible} margin={{ top: 8, right: 12, bottom: 8, left: 4 }}>
          <CartesianGrid stroke="#1e293b" vertical={false} />
          <XAxis dataKey="trade_date" stroke="#94a3b8" fontSize={10} minTickGap={36} />
          <YAxis domain={["auto", "auto"]} stroke="#94a3b8" fontSize={10} tickFormatter={(v) => Number(v).toLocaleString("ko-KR")} />
          <Tooltip labelFormatter={(date) => `거래일 ${date}`} formatter={(value) => [`${Number(value).toLocaleString("ko-KR")}원`, "주간 종가"]} contentStyle={{ backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: 6 }} />
          <Line dataKey="close" stroke="#ef4444" strokeWidth={2} dot={false} activeDot={{ r: 5 }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
