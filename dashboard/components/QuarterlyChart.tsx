"use client";
// PRD Ref: §9.1-3 — 10분기 실적 추이. 값 라벨과 요청 순서를 화면 계약으로 둔다.
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  LabelList,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { SERIES_COLOR, type ChartPoint } from "@/lib/chart";
import { fundamentalMetricMeanings, type MetricMeaning } from "@/lib/metricMeaning";

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

function Explanation({ items }: { items: MetricMeaning[] }) {
  return <div className="mt-2 grid gap-2 sm:grid-cols-2">
    {items.map((item) => <div key={item.label} className="rounded border border-slate-800 bg-slate-900/60 p-2.5">
      <div className="text-[11px] font-bold text-sky-200">현재 위치 · {item.label}</div>
      <div className="mt-0.5 text-xs font-semibold text-slate-100">{item.value}</div>
      <p className="mt-1 text-[11px] leading-relaxed text-slate-300">{item.meaning}</p>
      <p className="mt-1 text-[10px] leading-relaxed text-amber-200">다음 확인: {item.watch}</p>
    </div>)}
  </div>;
}

/** 마지막 확정점부터 다음 분기 예상점까지의 구간만 점선으로 그린다. */
function chartSeries(points: ChartPoint[]) {
  const forecastIndex = points.findIndex((point) => point.isCurrentQuarter && point.isEstimate);
  const priorIndex = forecastIndex > 0 ? forecastIndex - 1 : -1;
  return points.map((point, index) => {
    const forecast = index === forecastIndex;
    const connector = forecast || index === priorIndex;
    return {
      ...point,
      revenueActual: forecast ? null : point.revenue,
      revenueForecast: forecast ? point.revenue : null,
      opActual: forecast ? null : point.op,
      opForecast: forecast ? point.op : null,
      opmActual: forecast ? null : point.opm,
      opmForecast: connector ? point.opm : null,
      gpmActual: forecast ? null : point.gpm,
      revenueYoyActual: forecast ? null : point.revenueYoy,
      revenueYoyForecast: connector ? point.revenueYoy : null,
      opYoyActual: forecast ? null : point.opYoy,
      opYoyForecast: connector ? point.opYoy : null,
    };
  });
}

function RevenuePanel({ points, meaning }: { points: ChartPoint[]; meaning: MetricMeaning }) {
  const data = chartSeries(points);
  return <div className="rounded border border-slate-800 bg-slate-950/30 p-2 md:col-span-2">
    <div className="mb-1 flex items-center justify-between text-xs"><strong className="text-slate-100">매출액 · GPM</strong><span className="text-slate-400">억원 · %</span></div>
    <div className="h-52"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={data} margin={{ top: 30, right: 10, bottom: 0, left: 0 }}>
      <CartesianGrid stroke="#1e293b" vertical={false} /><QuarterAxis />
      <YAxis yAxisId="amount" width={45} domain={["auto", "auto"]} stroke="#94a3b8" fontSize={9} tickFormatter={(v) => Number(v).toLocaleString("ko-KR")} />
      <YAxis yAxisId="percent" orientation="right" width={40} domain={["auto", "auto"]} stroke="#fff" fontSize={9} tickFormatter={(v) => `${Number(v).toFixed(0)}%`} />
      <Tooltip formatter={(v, name) => [fmt(v, name === "GPM" ? "%" : "억"), name]} contentStyle={tooltipStyle} /><Legend wrapperStyle={{ fontSize: 11 }} />
      <Bar yAxisId="amount" dataKey="revenueActual" name="매출액 확정·잠정" fill="#16a34a" isAnimationActive={false}><LabelList dataKey="revenueActual" position="top" fill="#bbf7d0" fontSize={9} formatter={valueLabel("억")} /></Bar>
      <Bar yAxisId="amount" dataKey="revenueForecast" name="다음 분기 매출 전망" fill="transparent" stroke="#4ade80" strokeWidth={2} strokeDasharray="5 4" isAnimationActive={false}><LabelList dataKey="revenueForecast" position="top" fill="#86efac" fontSize={9} formatter={valueLabel("억")} /></Bar>
      <Line yAxisId="percent" dataKey="gpmActual" name="GPM" stroke={SERIES_COLOR.GPM_COLOR} strokeWidth={2.5} dot={{ r: 3 }} connectNulls={false} isAnimationActive={false}><LabelList dataKey="gpmActual" content={(p) => lineLabel(SERIES_COLOR.GPM_COLOR, "%", -15)({ ...p })} /></Line>
    </ComposedChart></ResponsiveContainer></div>
    <Explanation items={[meaning]} />
  </div>;
}

function EarningsPanel({ points, meanings }: { points: ChartPoint[]; meanings: MetricMeaning[] }) {
  const data = chartSeries(points);
  return <div className="rounded border border-slate-800 bg-slate-950/30 p-2 md:col-span-2">
    <div className="mb-1 flex items-center justify-between text-xs"><strong className="text-slate-100">영업이익 · OPM</strong><span className="text-slate-400">억원 · %</span></div>
    <div className="h-52"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={data} margin={{ top: 32, right: 10, bottom: 0, left: 0 }}>
      <CartesianGrid stroke="#1e293b" vertical={false} /><QuarterAxis />
      <YAxis yAxisId="amount" width={45} domain={["auto", "auto"]} stroke="#94a3b8" fontSize={9} tickFormatter={(v) => Number(v).toLocaleString("ko-KR")} />
      <YAxis yAxisId="percent" orientation="right" width={40} domain={["auto", "auto"]} stroke={SERIES_COLOR.OPM_COLOR} fontSize={9} tickFormatter={(v) => `${Number(v).toFixed(0)}%`} />
      <Tooltip formatter={(v, name) => [fmt(v, name === "OPM" ? "%" : "억"), name]} contentStyle={tooltipStyle} /><Legend wrapperStyle={{ fontSize: 11 }} />
      <Bar yAxisId="amount" dataKey="opActual" name="영업이익 확정·잠정" fill="#d4a017" isAnimationActive={false}><LabelList dataKey="opActual" position="top" fill="#fde68a" fontSize={9} formatter={valueLabel("억")} /></Bar>
      <Bar yAxisId="amount" dataKey="opForecast" name="다음 분기 영업이익 전망" fill="transparent" stroke="#facc15" strokeWidth={2} strokeDasharray="5 4" isAnimationActive={false}><LabelList dataKey="opForecast" position="top" fill="#fde047" fontSize={9} formatter={valueLabel("억")} /></Bar>
      <Line yAxisId="percent" dataKey="opmActual" name="영업이익률" stroke={SERIES_COLOR.OPM_COLOR} strokeWidth={2.5} dot={{ r: 3 }} connectNulls={false} isAnimationActive={false}><LabelList dataKey="opmActual" content={(p) => lineLabel(SERIES_COLOR.OPM_COLOR, "%", -17)({ ...p })} /></Line>
      <Line yAxisId="percent" dataKey="opmForecast" name="영업이익률 전망" stroke={SERIES_COLOR.OPM_COLOR} strokeDasharray="5 4" strokeWidth={2.5} dot={{ r: 4 }} connectNulls={false} isAnimationActive={false}><LabelList dataKey="opmForecast" content={(p) => lineLabel(SERIES_COLOR.OPM_COLOR, "%", -17)({ ...p })} /></Line>
    </ComposedChart></ResponsiveContainer></div>
    <Explanation items={meanings} />
  </div>;
}

function GrowthLinePanel({ points, meanings }: { points: ChartPoint[]; meanings: MetricMeaning[] }) {
  const data = chartSeries(points);
  const revenueMeasured = points.filter((point) => !point.isCurrentQuarter && point.revenueYoy != null).length;
  const opMeasured = points.filter((point) => !point.isCurrentQuarter && point.opYoy != null).length;
  const measured = revenueMeasured + opMeasured;
  return <div className="rounded border border-slate-800 bg-slate-950/30 p-2 md:col-span-2">
    <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-xs">
      <strong className="text-slate-100">매출액 YoY · 영업이익 YoY</strong>
      <span className="text-slate-400">같은 좌표(%) · 발표 분기 매출 {revenueMeasured}/{points.filter((point) => !point.isCurrentQuarter).length} · 영업이익 {opMeasured}/{points.filter((point) => !point.isCurrentQuarter).length}</span>
    </div>
    {measured === 0 ? <div className="flex h-64 items-center justify-center text-xs text-slate-400">전년 동기 비교값이 아직 없다.</div> : <div className="h-72"><ResponsiveContainer width="100%" height="100%"><LineChart data={data} margin={{ top: 38, right: 12, bottom: 0, left: 0 }}>
      <CartesianGrid stroke="#1e293b" vertical={false} /><QuarterAxis />
      <YAxis width={50} domain={[
        (min: number) => Math.min(0, min - Math.max(Math.abs(min) * 0.12, 5)),
        (max: number) => Math.max(0, max + Math.max(Math.abs(max) * 0.12, 5)),
      ]} stroke="#94a3b8" fontSize={9} tickFormatter={(v) => `${Number(v).toFixed(0)}%`} />
      <ReferenceLine y={0} stroke="#94a3b8" strokeWidth={1.2} />
      <Tooltip formatter={(v, name) => [fmt(v, "%"), name]} contentStyle={tooltipStyle} />
      <Legend wrapperStyle={{ fontSize: 11 }} />
      <Line type="linear" dataKey="revenueYoyActual" name="매출액 YoY 확정·잠정" stroke={SERIES_COLOR.REVENUE_COLOR} strokeWidth={3} dot={{ r: 4 }} connectNulls={false} isAnimationActive={false}><LabelList dataKey="revenueYoyActual" content={(p) => lineLabel(SERIES_COLOR.REVENUE_LABEL, "%", -11)({ ...p })} /></Line>
      <Line type="linear" dataKey="revenueYoyForecast" name="매출액 YoY 전망" stroke={SERIES_COLOR.REVENUE_COLOR} strokeDasharray="5 4" strokeWidth={3} dot={{ r: 4 }} connectNulls={false} isAnimationActive={false}><LabelList dataKey="revenueYoyForecast" content={(p) => lineLabel(SERIES_COLOR.REVENUE_LABEL, "%", -11)({ ...p })} /></Line>
      <Line type="linear" dataKey="opYoyActual" name="영업이익 YoY 확정·잠정" stroke={SERIES_COLOR.OP_COLOR} strokeWidth={3} dot={{ r: 4 }} connectNulls={false} isAnimationActive={false}><LabelList dataKey="opYoyActual" content={(p) => lineLabel(SERIES_COLOR.OP_LABEL, "%", 17)({ ...p })} /></Line>
      <Line type="linear" dataKey="opYoyForecast" name="영업이익 YoY 전망" stroke={SERIES_COLOR.OP_COLOR} strokeDasharray="5 4" strokeWidth={3} dot={{ r: 4 }} connectNulls={false} isAnimationActive={false}><LabelList dataKey="opYoyForecast" content={(p) => lineLabel(SERIES_COLOR.OP_LABEL, "%", 17)({ ...p })} /></Line>
    </LineChart></ResponsiveContainer></div>}
    <div className="mt-2 overflow-x-auto">
      <table className="w-full min-w-[760px] text-center text-[10px] text-slate-300">
        <thead><tr><th className="py-1 text-left">원값</th>{points.map((point) => <th key={point.label}>{point.label}</th>)}</tr></thead>
        <tbody>
          <tr className="border-t border-slate-800"><th className="py-1 text-left text-emerald-300">매출 YoY</th>{points.map((point) => <td key={point.label}>{fmt(point.revenueYoy, "%")}</td>)}</tr>
          <tr className="border-t border-slate-800"><th className="py-1 text-left text-amber-300">영업익 YoY</th>{points.map((point) => <td key={point.label}>{point.opYoy == null && point.opStatusLabel ? point.opStatusLabel : fmt(point.opYoy, "%")}</td>)}</tr>
        </tbody>
      </table>
    </div>
    <p className="mt-1 text-[10px] leading-relaxed text-slate-400">실선은 발표된 분기, 점선은 다음 분기 컨센서스다. 빈 칸은 선으로 이어 숨기지 않고, 흑전·적전처럼 % 계산이 성립하지 않는 분기는 원값 표에 상태로 표시한다.</p>
    <Explanation items={meanings} />
  </div>;
}

function OrdersPanel({ points, meaning }: { points: ChartPoint[]; meaning: MetricMeaning }) {
  const measured = points.some((p) => p.orderBacklog != null || p.newOrders != null);
  return <div className="rounded border border-slate-800 bg-slate-950/30 p-2 md:col-span-2">
    <div className="mb-1 flex items-center justify-between text-xs"><strong className="text-slate-100">수주잔고 · 신규수주</strong><span className="text-slate-400">억원</span></div>
    {!measured ? <div className="flex h-40 items-center justify-center text-xs text-slate-400">공개 자료의 구조화 수치 미수집</div> : <div className="h-40"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={points} margin={{ top: 24, right: 5, bottom: 0, left: 0 }}>
      <CartesianGrid stroke="#1e293b" vertical={false} /><QuarterAxis /><YAxis width={52} domain={[0, "auto"]} stroke="#94a3b8" fontSize={9} tickFormatter={(v) => Number(v).toLocaleString("ko-KR")} /><Tooltip formatter={(v, name) => [fmt(v, "억"), name]} contentStyle={tooltipStyle} /><Legend wrapperStyle={{ fontSize: 11 }} />
      <Bar dataKey="orderBacklog" name="수주잔고" fill="#a78bfa" isAnimationActive={false}><LabelList dataKey="orderBacklog" position="top" fill="#ddd6fe" fontSize={9} formatter={valueLabel("억")} /></Bar>
      <Bar dataKey="newOrders" name="신규수주" fill="#fb7185" isAnimationActive={false}><LabelList dataKey="newOrders" position="top" fill="#fecdd3" fontSize={9} formatter={valueLabel("억")} /></Bar>
    </ComposedChart></ResponsiveContainer></div>}
    <Explanation items={[meaning]} />
  </div>;
}

export default function QuarterlyChart({ points }: { points: ChartPoint[] }) {
  if (!points.length) return <p className="py-8 text-center text-sm text-slate-300">분기 재무가 아직 없다.</p>;
  // 현재 위치 해설은 발표된 분기만 본다. 점선 컨센서스를 현재 실적으로 오인하지 않는다.
  const meanings = fundamentalMetricMeanings(points.filter((point) => !point.isCurrentQuarter));
  return <div className="grid gap-3 md:grid-cols-2">
    <RevenuePanel points={points} meaning={meanings[0]} />
    <EarningsPanel points={points} meanings={meanings.slice(1, 3)} />
    <GrowthLinePanel points={points} meanings={meanings.slice(3, 5)} />
    <OrdersPanel points={points} meaning={meanings[5]} />
  </div>;
}
