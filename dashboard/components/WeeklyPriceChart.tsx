"use client";
// PRD Ref: §9.1-3 — 실제 주간 종가 + MACD + RSI
import { Bar, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { normalizeWeeklyRows, technicalIndicators } from "@/lib/technicalIndicators";
import type { WeeklyPriceRow } from "@/lib/types";

const tooltipStyle = { backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: 6 };
export default function WeeklyPriceChart({ points, fromDate }: { points: WeeklyPriceRow[]; fromDate?: string }) {
  // 지표는 화면 시작일보다 앞선 데이터까지 먼저 계산해야 첫 표시일부터 MACD가 나온다.
  // 반복 수집으로 같은 ISO 주가 여러 행인 경우 마지막 거래일만 남긴다.
  const visible = technicalIndicators(normalizeWeeklyRows(points))
    .filter((point) => !fromDate || point.trade_date >= fromDate);
  const macdPoints = visible.filter((point) => point.macd != null);
  const latestMacd = [...macdPoints].reverse().find((point) => point.signal != null && point.histogram != null);
  if (!visible.length) return <p className="py-5 text-center text-sm text-slate-300">같은 기간의 주간 종가를 아직 수집하지 않았다.</p>;
  return <div id="weekly-technical" className="mt-5 space-y-4">
    <div><div className="mb-1 text-xs font-semibold text-slate-200">실제 주간 종가</div><div className="h-52"><ResponsiveContainer width="100%" height="100%"><LineChart data={visible}><CartesianGrid stroke="#1e293b" vertical={false} /><XAxis dataKey="trade_date" stroke="#94a3b8" fontSize={9} minTickGap={42} /><YAxis domain={["auto", "auto"]} stroke="#94a3b8" fontSize={9} tickFormatter={(v) => Number(v).toLocaleString("ko-KR")} /><Tooltip formatter={(v) => [`${Number(v).toLocaleString("ko-KR")}원`, "주간 종가"]} contentStyle={tooltipStyle} /><Line dataKey="close" stroke="#ef4444" strokeWidth={2} dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div></div>
    <div>
      <div className="mb-1 flex items-center justify-between text-xs font-semibold text-slate-200">
        <span>MACD (12·26·9)</span><span className="font-normal text-slate-400">네이버 일봉 → ISO 주 마지막 거래일 · {macdPoints.length}주</span>
      </div>
      {macdPoints.length === 0 ? (
        <div className="flex h-44 items-center justify-center text-xs text-slate-400">MACD 계산에는 최소 26주 종가가 필요하다.</div>
      ) : (
        <>
          {latestMacd && <div className="mb-1 flex flex-wrap gap-3 text-[10px] text-slate-300"><span>{latestMacd.trade_date}</span><span>MACD {latestMacd.macd?.toFixed(1)}</span><span>Signal {latestMacd.signal?.toFixed(1)}</span><span>Histogram {latestMacd.histogram != null && latestMacd.histogram >= 0 ? "+" : ""}{latestMacd.histogram?.toFixed(1)}</span></div>}
          <div className="h-52"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={macdPoints} margin={{ top: 8, right: 8, left: 4, bottom: 0 }}><CartesianGrid stroke="#1e293b" vertical={false} /><XAxis dataKey="trade_date" stroke="#94a3b8" fontSize={9} minTickGap={42} /><YAxis domain={["auto", "auto"]} stroke="#94a3b8" fontSize={9} tickFormatter={(v) => Number(v).toLocaleString("ko-KR", { maximumFractionDigits: 0 })} /><ReferenceLine y={0} stroke="#94a3b8" strokeWidth={1.2} /><Tooltip formatter={(v, name) => [Number(v).toLocaleString("ko-KR", { maximumFractionDigits: 1 }), name]} contentStyle={tooltipStyle} /><Legend wrapperStyle={{ fontSize: 11 }} /><Bar dataKey="histogram" name="Histogram" isAnimationActive={false}>{macdPoints.map((point) => <Cell key={point.trade_date} fill={point.histogram == null ? "#475569" : point.histogram >= 0 ? "#22c55e" : "#ef4444"} fillOpacity={0.72} />)}</Bar><Line type="linear" dataKey="macd" name="MACD" stroke="#38bdf8" strokeWidth={2.4} dot={false} connectNulls={false} isAnimationActive={false} /><Line type="linear" dataKey="signal" name="Signal" stroke="#f59e0b" strokeWidth={2.2} dot={false} connectNulls={false} isAnimationActive={false} /></ComposedChart></ResponsiveContainer></div>
        </>
      )}
      <p className="mt-1 text-[10px] leading-relaxed text-slate-400">주봉 MACD = EMA(12) − EMA(26), Signal = MACD의 EMA(9), Histogram = MACD − Signal. 화면 시작 전 주가까지 먼저 계산해 첫 표시 구간의 지표가 잘리지 않게 했다.</p>
    </div>
    <div><div className="mb-1 text-xs font-semibold text-slate-200">RSI (14)</div><div className="h-40"><ResponsiveContainer width="100%" height="100%"><LineChart data={visible}><CartesianGrid stroke="#1e293b" vertical={false} /><XAxis dataKey="trade_date" stroke="#94a3b8" fontSize={9} minTickGap={42} /><YAxis domain={[0, 100]} ticks={[30, 45, 70]} stroke="#94a3b8" fontSize={9} /><ReferenceLine y={70} stroke="#ef4444" strokeDasharray="3 3" /><ReferenceLine y={45} stroke="#facc15" strokeDasharray="3 3" /><ReferenceLine y={30} stroke="#38bdf8" strokeDasharray="3 3" /><Tooltip formatter={(v) => [Number(v).toFixed(1), "RSI"]} contentStyle={tooltipStyle} /><Line dataKey="rsi" stroke="#c084fc" strokeWidth={2} dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div></div>
  </div>;
}
