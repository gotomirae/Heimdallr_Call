"use client";
// PRD Ref: §9.1-3 — 네이버 일간 종가 + 실적 발표일 + 일간 MACD·RSI
import {
  Bar,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { macdMeaning, priceMeaning, rsiMeaning, type MetricMeaning } from "@/lib/metricMeaning";
import { normalizeDailyRows, technicalIndicators } from "@/lib/technicalIndicators";
import type { DisclosureRow } from "@/lib/types";
import type { NaverDailyPrice } from "@/lib/naver";

const tooltipStyle = { backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: 6 };

function Explanation({ item, evidence }: { item: MetricMeaning; evidence?: string | null }) {
  return <div className="mt-2 rounded border border-slate-800 bg-slate-900/60 p-3">
    <div className="text-[11px] font-bold text-sky-200">현재 위치 · {item.label}</div>
    <div className="mt-0.5 text-sm font-semibold text-slate-100">{item.value}</div>
    <p className="mt-1 text-xs leading-relaxed text-slate-300">{item.meaning}</p>
    {evidence && <p className="mt-2 border-l-2 border-violet-500/70 pl-2 text-xs leading-relaxed text-slate-200">
      <strong className="text-violet-200">하락·상승 원인 분석 · </strong>{evidence}
    </p>}
    {item.action && <p className="mt-2 text-xs leading-relaxed text-emerald-200"><strong>투자전략 · </strong>{item.action}</p>}
    <p className="mt-1 text-[11px] leading-relaxed text-amber-200">다음 확인: {item.watch}</p>
  </div>;
}

function announcementDates(points: NaverDailyPrice[], disclosures: DisclosureRow[]): Array<{ date: string; title: string }> {
  const dates = points.map((point) => point.trade_date);
  const picked = new Map<string, { date: string; title: string }>();
  for (const row of disclosures) {
    if (!row.disclosed_at || !/잠정|영업.*실적|분기보고서|반기보고서|사업보고서/.test(row.report_nm ?? "")) continue;
    const disclosed = row.disclosed_at.slice(0, 10);
    const marketDate = dates.find((date) => date >= disclosed);
    if (!marketDate) continue;
    const quarter = row.fiscal_year && row.fiscal_quarter ? `${String(row.fiscal_year).slice(-2)}.${row.fiscal_quarter}Q` : "실적";
    if (!picked.has(quarter)) picked.set(quarter, { date: marketDate, title: `${quarter} 실적 발표 · ${disclosed}` });
  }
  return [...picked.values()].sort((left, right) => left.date.localeCompare(right.date)).slice(-10);
}

export default function DailyPriceChart({
  points,
  disclosures,
  fromDate,
  high52w,
  priceAnalysis,
}: {
  points: NaverDailyPrice[];
  disclosures: DisclosureRow[];
  fromDate?: string;
  high52w?: number | null;
  priceAnalysis?: string | null;
}) {
  // MACD 워밍업을 먼저 계산하고 화면 기간을 자른다. 먼저 자르면 첫 34거래일 지표가 비게 된다.
  const all = technicalIndicators(normalizeDailyRows(points));
  const visible = all.filter((point) => !fromDate || point.trade_date >= fromDate);
  const marks = announcementDates(visible, disclosures);
  const macdPoints = visible.filter((point) => point.macd != null);
  const latestMacd = [...macdPoints].reverse().find((point) => point.signal != null && point.histogram != null);
  if (!visible.length) return <p className="py-5 text-center text-sm text-slate-300">같은 기간의 네이버 일간 종가를 불러오지 못했다.</p>;
  const price = priceMeaning(visible, high52w);
  const macd = macdMeaning(visible);
  const rsi = rsiMeaning(visible);
  return <div id="daily-technical" className="mt-5 space-y-5">
    <div>
      <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-xs font-semibold text-slate-200">
        <span>네이버 증권 실제 일간 종가</span>
        <span className="font-normal text-slate-400">세로선 = 분기실적 발표일 · {visible.length}거래일</span>
      </div>
      <div className="h-64"><ResponsiveContainer width="100%" height="100%"><LineChart data={visible} margin={{ top: 16, right: 8, left: 4, bottom: 0 }}>
        <CartesianGrid stroke="#1e293b" vertical={false} />
        <XAxis dataKey="trade_date" stroke="#94a3b8" fontSize={9} minTickGap={44} />
        <YAxis domain={["auto", "auto"]} stroke="#94a3b8" fontSize={9} tickFormatter={(v) => Number(v).toLocaleString("ko-KR")} />
        <Tooltip formatter={(v) => [`${Number(v).toLocaleString("ko-KR")}원`, "일간 종가"]} contentStyle={tooltipStyle} />
        {marks.map((mark) => <ReferenceLine key={`${mark.date}-${mark.title}`} x={mark.date} stroke="#f59e0b" strokeDasharray="3 3" label={{ value: mark.title.split(" · ")[0], position: "insideTopLeft", fill: "#fbbf24", fontSize: 9 }} />)}
        <Line dataKey="close" stroke="#ef4444" strokeWidth={2} dot={false} isAnimationActive={false} />
      </LineChart></ResponsiveContainer></div>
      <Explanation item={price} evidence={priceAnalysis} />
    </div>
    <div>
      <div className="mb-1 flex items-center justify-between text-xs font-semibold text-slate-200">
        <span>MACD (일간 12·26·9)</span><span className="font-normal text-slate-400">네이버 일봉 · {macdPoints.length}거래일</span>
      </div>
      {macdPoints.length === 0 ? <div className="flex h-44 items-center justify-center text-xs text-slate-400">MACD 계산에는 최소 26거래일 종가가 필요하다.</div> : <>
        {latestMacd && <div className="mb-1 flex flex-wrap gap-3 text-[10px] text-slate-300"><span>{latestMacd.trade_date}</span><span>MACD {latestMacd.macd?.toFixed(1)}</span><span>Signal {latestMacd.signal?.toFixed(1)}</span><span>Histogram {latestMacd.histogram != null && latestMacd.histogram >= 0 ? "+" : ""}{latestMacd.histogram?.toFixed(1)}</span></div>}
        <div className="h-52"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={macdPoints} margin={{ top: 8, right: 8, left: 4, bottom: 0 }}>
          <CartesianGrid stroke="#1e293b" vertical={false} /><XAxis dataKey="trade_date" stroke="#94a3b8" fontSize={9} minTickGap={44} /><YAxis domain={["auto", "auto"]} stroke="#94a3b8" fontSize={9} tickFormatter={(v) => Number(v).toLocaleString("ko-KR", { maximumFractionDigits: 0 })} /><ReferenceLine y={0} stroke="#94a3b8" strokeWidth={1.2} /><Tooltip formatter={(v, name) => [Number(v).toLocaleString("ko-KR", { maximumFractionDigits: 1 }), name]} contentStyle={tooltipStyle} /><Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar dataKey="histogram" name="Histogram" isAnimationActive={false}>{macdPoints.map((point) => <Cell key={point.trade_date} fill={point.histogram == null ? "#475569" : point.histogram >= 0 ? "#22c55e" : "#ef4444"} fillOpacity={0.72} />)}</Bar><Line type="linear" dataKey="macd" name="MACD" stroke="#38bdf8" strokeWidth={2.4} dot={false} connectNulls={false} isAnimationActive={false} /><Line type="linear" dataKey="signal" name="Signal" stroke="#f59e0b" strokeWidth={2.2} dot={false} connectNulls={false} isAnimationActive={false} />
        </ComposedChart></ResponsiveContainer></div>
      </>}
      <Explanation item={macd} />
    </div>
    <div>
      <div className="mb-1 text-xs font-semibold text-slate-200">RSI (일간 14)</div>
      <div className="h-40"><ResponsiveContainer width="100%" height="100%"><LineChart data={visible}><CartesianGrid stroke="#1e293b" vertical={false} /><XAxis dataKey="trade_date" stroke="#94a3b8" fontSize={9} minTickGap={44} /><YAxis domain={[0, 100]} ticks={[30, 45, 70]} stroke="#94a3b8" fontSize={9} /><ReferenceLine y={70} stroke="#ef4444" strokeDasharray="3 3" /><ReferenceLine y={45} stroke="#facc15" strokeDasharray="3 3" /><ReferenceLine y={30} stroke="#38bdf8" strokeDasharray="3 3" /><Tooltip formatter={(v) => [Number(v).toFixed(1), "RSI"]} contentStyle={tooltipStyle} /><Line dataKey="rsi" stroke="#c084fc" strokeWidth={2} dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>
      <Explanation item={rsi} />
    </div>
  </div>;
}
