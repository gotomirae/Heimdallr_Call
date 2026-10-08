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
import { createContext, useContext } from "react";
import { SERIES_COLOR, withOrderBacklogQoq, type ChartPoint } from "@/lib/chart";
import { orderAmount } from "@/lib/format";
import { fundamentalMetricMeanings, type MetricMeaning, type QuarterInterpretation } from "@/lib/metricMeaning";

const ReviewContext = createContext<QuarterInterpretation[]>([]);

const tooltipStyle = { backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: 6 };

function fmt(value: unknown, unit: string): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const shown = value.toLocaleString("ko-KR", { maximumFractionDigits: 1 });
  return `${value > 0 && unit === "%" ? "+" : ""}${shown}${unit}`;
}

function valueLabel(unit: string) {
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
  return <YAxis width={45} domain={["auto", "auto"]} stroke="#ffffff" fontSize={9} tickFormatter={(v) => percent ? `${Number(v).toFixed(0)}%` : Number(v).toLocaleString("ko-KR")} />;
}

function QuarterAxis() {
  return <XAxis dataKey="label" stroke="#ffffff" fontSize={9} tickLine={false} />;
}

function Explanation({ items, kind }: { items: MetricMeaning[]; kind?: "revenue" | "earnings" | "yoy" }) {
  const reviews = useContext(ReviewContext);
  if (kind) return <div className="mt-3 grid gap-2 sm:grid-cols-2">
    {reviews.map((row) => <div key={row.label} className="rounded border border-sky-900/60 bg-slate-900/60 p-3 text-xs leading-6">
      <strong className="text-sky-200">📅 {row.label} · {kind === "revenue" ? "📦 매출/GPM" : kind === "earnings" ? "🏭 영업이익/OPM" : "📈 성장률의 원인"}</strong>
      <p className="mt-2 whitespace-pre-line text-white">{row[kind] ?? "⚠️ 이 분기의 인과 해석은 아직 확인되지 않았습니다. 물량·판가·제품믹스·원가·일회성 항목을 해당 분기 원문과 대조해야 합니다. 숫자만으로 원인을 만들지 않습니다."}</p>
      {row.source && <a className="mt-1 inline-block text-sky-300 underline" href={row.source} target="_blank" rel="noreferrer">분기 공시 원문 ↗</a>}
    </div>)}
    <p className="col-span-full text-[11px] text-white">🔎 인과 해석은 공시·저장 분석 범위이며, 미확인 분기는 현재 기준 LLM 분석 후 근거와 함께 보완합니다. 높은 YoY만으로 반복 가능한 성장이라고 단정하지 않습니다.</p>
  </div>;
  return <div className="mt-2 grid gap-2 sm:grid-cols-2">
    {items.map((item) => <div key={item.label} className="rounded border border-slate-800 bg-slate-900/60 p-2.5">
      <div className="text-[11px] font-bold text-sky-200">현재 위치 · {item.label}</div>
      <div className="mt-0.5 text-xs font-semibold text-white">{item.value}</div>
      <p className="mt-1 text-[11px] leading-relaxed text-white">{item.meaning}</p>
      <p className="mt-1 text-[10px] leading-relaxed text-amber-200">다음 확인: {item.watch}</p>
    </div>)}
  </div>;
}

/** 마지막 확정점부터 다음 분기 예상점까지의 구간만 점선으로 그린다. */
function chartSeries(points: ChartPoint[]) {
  const chartable = points.filter((point) => !point.isContractEvent);
  const forecastIndex = chartable.findIndex((point) => point.isCurrentQuarter && point.isEstimate);
  const priorIndex = forecastIndex > 0 ? forecastIndex - 1 : -1;
  return chartable.map((point, index) => {
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
  const gpmMeasured = data.filter((point) => point.gpmActual != null).length;
  const actualCount = data.filter((point) => !point.isCurrentQuarter).length;
  return <div className="rounded border border-slate-800 bg-slate-950/30 p-2 md:col-span-2">
    <div className="mb-1 flex items-center justify-between"><strong className="text-lg font-black text-white">매출액 / GPM</strong><span className="text-xs text-white">억원 · % · 실적 GPM {gpmMeasured}/{actualCount}</span></div>
    <div className="h-52"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={data} margin={{ top: 30, right: 10, bottom: 0, left: 0 }}>
      <CartesianGrid stroke="#1e293b" vertical={false} /><QuarterAxis />
      <YAxis yAxisId="amount" width={45} domain={["auto", "auto"]} stroke="#ffffff" fontSize={9} tickFormatter={(v) => Number(v).toLocaleString("ko-KR")} />
      <YAxis yAxisId="percent" orientation="right" width={40} domain={["auto", "auto"]} stroke="#fff" fontSize={9} tickFormatter={(v) => `${Number(v).toFixed(0)}%`} />
      <Tooltip formatter={(v, name) => [fmt(v, String(name).startsWith("GPM") ? "%" : "억"), name]} contentStyle={tooltipStyle} /><Legend wrapperStyle={{ fontSize: 11 }} />
      <Bar yAxisId="amount" dataKey="revenueActual" name="매출액 확정·잠정" fill="#16a34a" isAnimationActive={false}><LabelList dataKey="revenueActual" position="top" fill="#bbf7d0" fontSize={9} formatter={valueLabel("억")} /></Bar>
      <Bar yAxisId="amount" dataKey="revenueForecast" name="다음 분기 매출 전망" fill="transparent" stroke="#4ade80" strokeWidth={2} strokeDasharray="5 4" isAnimationActive={false}><LabelList dataKey="revenueForecast" position="top" fill="#86efac" fontSize={9} formatter={valueLabel("억")} /></Bar>
      <Line yAxisId="percent" dataKey="gpmActual" name="GPM(흰색)" stroke="#ffffff" strokeWidth={3.5} dot={{ r: 4, fill: "#0f172a", stroke: "#ffffff", strokeWidth: 2 }} activeDot={{ r: 6, fill: "#ffffff", stroke: "#0f172a", strokeWidth: 2 }} connectNulls={false} isAnimationActive={false}><LabelList dataKey="gpmActual" content={(p) => lineLabel("#ffffff", "%", -15)({ ...p })} /></Line>
    </ComposedChart></ResponsiveContainer></div>
    {gpmMeasured === 0 && <p className="mt-1 rounded border border-amber-800/60 bg-amber-950/20 px-2 py-1 text-xs text-amber-200">GPM 원자료가 수집되지 않아 선을 그리지 않았다. 0%가 아니다.</p>}
    <Explanation items={[meaning]} kind="revenue" />
  </div>;
}

function EarningsPanel({ points, meanings }: { points: ChartPoint[]; meanings: MetricMeaning[] }) {
  const data = chartSeries(points);
  return <div className="rounded border border-slate-800 bg-slate-950/30 p-2 md:col-span-2">
    <div className="mb-1 flex items-center justify-between"><strong className="text-lg font-black text-white">영업이익 / OPM</strong><span className="text-xs text-white">억원 · %</span></div>
    <div className="h-52"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={data} margin={{ top: 32, right: 10, bottom: 0, left: 0 }}>
      <CartesianGrid stroke="#1e293b" vertical={false} /><QuarterAxis />
      <YAxis yAxisId="amount" width={45} domain={["auto", "auto"]} stroke="#ffffff" fontSize={9} tickFormatter={(v) => Number(v).toLocaleString("ko-KR")} />
      <YAxis yAxisId="percent" orientation="right" width={40} domain={["auto", "auto"]} stroke={SERIES_COLOR.OPM_COLOR} fontSize={9} tickFormatter={(v) => `${Number(v).toFixed(0)}%`} />
      <Tooltip formatter={(v, name) => [fmt(v, name === "OPM" ? "%" : "억"), name]} contentStyle={tooltipStyle} /><Legend wrapperStyle={{ fontSize: 11 }} />
      <Bar yAxisId="amount" dataKey="opActual" name="영업이익 확정·잠정" fill="#d4a017" isAnimationActive={false}><LabelList dataKey="opActual" position="top" fill="#fde68a" fontSize={9} formatter={valueLabel("억")} /></Bar>
      <Bar yAxisId="amount" dataKey="opForecast" name="다음 분기 영업이익 전망" fill="transparent" stroke="#facc15" strokeWidth={2} strokeDasharray="5 4" isAnimationActive={false}><LabelList dataKey="opForecast" position="top" fill="#fde047" fontSize={9} formatter={valueLabel("억")} /></Bar>
      <Line yAxisId="percent" dataKey="opmActual" name="영업이익률" stroke={SERIES_COLOR.OPM_COLOR} strokeWidth={2.5} dot={{ r: 3 }} connectNulls={false} isAnimationActive={false}><LabelList dataKey="opmActual" content={(p) => lineLabel(SERIES_COLOR.OPM_COLOR, "%", -17)({ ...p })} /></Line>
      <Line yAxisId="percent" dataKey="opmForecast" name="영업이익률 전망" stroke={SERIES_COLOR.OPM_COLOR} strokeDasharray="5 4" strokeWidth={2.5} dot={{ r: 4 }} connectNulls={false} isAnimationActive={false}><LabelList dataKey="opmForecast" content={(p) => lineLabel(SERIES_COLOR.OPM_COLOR, "%", -17)({ ...p })} /></Line>
    </ComposedChart></ResponsiveContainer></div>
    <Explanation items={meanings} kind="earnings" />
  </div>;
}

function GrowthLinePanel({ points, meanings }: { points: ChartPoint[]; meanings: MetricMeaning[] }) {
  const growthPoints = points.filter((point) => !point.isContractEvent);
  const data = chartSeries(growthPoints);
  const revenueMeasured = growthPoints.filter((point) => !point.isCurrentQuarter && point.revenueYoy != null).length;
  const opMeasured = growthPoints.filter((point) => !point.isCurrentQuarter && point.opYoy != null).length;
  const reportedCount = growthPoints.filter((point) => !point.isCurrentQuarter).length;
  const measured = revenueMeasured + opMeasured;
  return <div className="rounded border border-slate-800 bg-slate-950/30 p-2 md:col-span-2">
    <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-xs">
      <strong className="text-lg font-black text-white">매출액 YoY / 영업이익 YoY</strong>
      <span className="text-white">같은 좌표(%) · 발표 분기 매출 {revenueMeasured}/{reportedCount} · 영업이익 {opMeasured}/{reportedCount}</span>
    </div>
    {measured === 0 ? <div className="flex h-64 items-center justify-center text-xs text-white">전년 동기 비교값이 아직 없다.</div> : <div className="h-72"><ResponsiveContainer width="100%" height="100%"><LineChart data={data} margin={{ top: 38, right: 12, bottom: 0, left: 0 }}>
      <CartesianGrid stroke="#1e293b" vertical={false} /><QuarterAxis />
      <YAxis width={50} domain={[
        (min: number) => Math.min(0, min - Math.max(Math.abs(min) * 0.12, 5)),
        (max: number) => Math.max(0, max + Math.max(Math.abs(max) * 0.12, 5)),
      ]} stroke="#ffffff" fontSize={9} tickFormatter={(v) => `${Number(v).toFixed(0)}%`} />
      <ReferenceLine y={0} stroke="#ffffff" strokeWidth={1.2} />
      <Tooltip formatter={(v, name) => [fmt(v, "%"), name]} contentStyle={tooltipStyle} />
      <Legend wrapperStyle={{ fontSize: 11 }} />
      <Line type="linear" dataKey="revenueYoyActual" name="매출액 YoY 확정·잠정" stroke={SERIES_COLOR.REVENUE_COLOR} strokeWidth={3} dot={{ r: 4 }} connectNulls={false} isAnimationActive={false}><LabelList dataKey="revenueYoyActual" content={(p) => lineLabel(SERIES_COLOR.REVENUE_LABEL, "%", -11)({ ...p })} /></Line>
      <Line type="linear" dataKey="revenueYoyForecast" name="매출액 YoY 전망" stroke={SERIES_COLOR.REVENUE_COLOR} strokeDasharray="5 4" strokeWidth={3} dot={{ r: 4 }} connectNulls={false} isAnimationActive={false}><LabelList dataKey="revenueYoyForecast" content={(p) => lineLabel(SERIES_COLOR.REVENUE_LABEL, "%", -11)({ ...p })} /></Line>
      <Line type="linear" dataKey="opYoyActual" name="영업이익 YoY 확정·잠정" stroke={SERIES_COLOR.OP_COLOR} strokeWidth={3} dot={{ r: 4 }} connectNulls={false} isAnimationActive={false}><LabelList dataKey="opYoyActual" content={(p) => lineLabel(SERIES_COLOR.OP_LABEL, "%", 17)({ ...p })} /></Line>
      <Line type="linear" dataKey="opYoyForecast" name="영업이익 YoY 전망" stroke={SERIES_COLOR.OP_COLOR} strokeDasharray="5 4" strokeWidth={3} dot={{ r: 4 }} connectNulls={false} isAnimationActive={false}><LabelList dataKey="opYoyForecast" content={(p) => lineLabel(SERIES_COLOR.OP_LABEL, "%", 17)({ ...p })} /></Line>
    </LineChart></ResponsiveContainer></div>}
    <div className="mt-2 overflow-x-auto">
      <table className="w-full min-w-[760px] text-center text-[10px] text-white">
        <thead><tr><th className="py-1 text-left">원값</th>{growthPoints.map((point) => <th key={point.label}>{point.label}</th>)}</tr></thead>
        <tbody>
          <tr className="border-t border-slate-800"><th className="py-1 text-left text-emerald-300">매출 YoY</th>{growthPoints.map((point) => <td key={point.label}>{fmt(point.revenueYoy, "%")}</td>)}</tr>
          <tr className="border-t border-slate-800"><th className="py-1 text-left text-amber-300">영업익 YoY</th>{growthPoints.map((point) => <td key={point.label}>{point.opYoy == null && point.opStatusLabel ? point.opStatusLabel : fmt(point.opYoy, "%")}</td>)}</tr>
        </tbody>
      </table>
    </div>
    <p className="mt-1 text-[10px] leading-relaxed text-white">실선은 발표된 분기, 점선은 다음 분기 컨센서스다. 빈 칸은 선으로 이어 숨기지 않고, 흑전·적전처럼 % 계산이 성립하지 않는 분기는 원값 표에 상태로 표시한다.</p>
    <Explanation items={meanings} kind="yoy" />
  </div>;
}

function OrdersPanel({ points, meaning }: { points: ChartPoint[]; meaning: MetricMeaning }) {
  const data = withOrderBacklogQoq(points);
  const measured = data.some((p) => p.orderBacklog != null || p.newOrders != null || p.disclosedContractEok != null || p.postReportContractEok != null);
  const qoqMeasured = data.filter((p) => p.orderBacklogQoq != null).length;
  const unit = data.find((p) => p.orderAmountUnit)?.orderAmountUnit ?? "억원";
  const suffix = unit === "억원" ? "억" : unit;
  return <div className="rounded border border-slate-800 bg-slate-950/30 p-2 md:col-span-2">
    <div className="mb-1 flex items-center justify-between"><strong className="text-lg font-black text-white">수주잔고 / 신규 수주 / 수주잔고 QoQ</strong><span className="text-xs text-white">{unit} · % · QoQ {qoqMeasured}개</span></div>
    <div className="h-52"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={data} margin={{ top: 28, right: 8, bottom: 0, left: 0 }}>
      <CartesianGrid stroke="#1e293b" vertical={false} /><QuarterAxis />
      <YAxis yAxisId="amount" width={52} domain={[0, "auto"]} stroke="#ffffff" fontSize={9} tickFormatter={(v) => Number(v).toLocaleString("ko-KR")} />
      <YAxis yAxisId="percent" orientation="right" width={42} domain={["auto", "auto"]} stroke="#facc15" fontSize={9} tickFormatter={(v) => `${Number(v).toFixed(0)}%`} />
      <ReferenceLine yAxisId="percent" y={0} stroke="#64748b" strokeWidth={1} />
      <Tooltip formatter={(v, name) => [String(name).includes("QoQ") ? fmt(v, "%") : `${orderAmount(typeof v === "number" ? v : null)}${suffix}`, name]} contentStyle={tooltipStyle} /><Legend wrapperStyle={{ fontSize: 11 }} />
      <Bar yAxisId="amount" dataKey="orderBacklog" name="수주잔고" fill="#a78bfa" isAnimationActive={false}><LabelList dataKey="orderBacklog" position="top" fill="#ddd6fe" fontSize={9} formatter={(v) => `${orderAmount(typeof v === "number" ? v : null)}${suffix}`} /></Bar>
      <Bar yAxisId="amount" dataKey="newOrders" name="신규수주(분기 단독)" fill="#fb7185" isAnimationActive={false}><LabelList dataKey="newOrders" position="top" fill="#fecdd3" fontSize={9} formatter={(v) => `${orderAmount(typeof v === "number" ? v : null)}${suffix}`} /></Bar>
      <Bar yAxisId="amount" dataKey="disclosedContractEok" name="공시 신규계약(하한·보고서일까지)" fill="#22d3ee" isAnimationActive={false}><LabelList dataKey="disclosedContractEok" position="top" fill="#a5f3fc" fontSize={9} formatter={valueLabel("억")} /></Bar>
      <Bar yAxisId="amount" dataKey="postReportContractEok" name="공시 신규계약(하한·보고서 이후)" fill="#fb923c" isAnimationActive={false}><LabelList dataKey="postReportContractEok" position="top" fill="#fed7aa" fontSize={9} formatter={valueLabel("억")} /></Bar>
      <Line yAxisId="percent" type="linear" dataKey="orderBacklogQoq" name="수주잔고 QoQ" stroke="#facc15" strokeWidth={2.5} dot={{ r: 3 }} connectNulls={false} isAnimationActive={false}><LabelList dataKey="orderBacklogQoq" content={(p) => lineLabel("#fde047", "%", -12)({ ...p })} /></Line>
    </ComposedChart></ResponsiveContainer></div>
    {!measured && <p className="mt-1 rounded border border-amber-800/60 bg-amber-950/20 px-2 py-1 text-xs text-amber-200">막대 축은 유지하되 공개 자료의 구조화 수치가 없어 값을 그리지 않았다. 0원이 아니다.</p>}
    {unit !== "억원" && <p className="mt-1 text-xs text-sky-200">원문 외화({unit}) 기준입니다. 원화 환산이나 원화 계약액 합산은 하지 않습니다.</p>}
    <p className="mt-1 text-[11px] text-amber-200">분홍 막대는 분기 단독 신규수주입니다. 누적 공시는 같은 연도·범위·통화의 직전 분기 누적액을 차감하며, 비교할 원문이 없으면 빈 칸으로 남깁니다.</p>
    <p className="mt-1 text-[10px] leading-4 text-white">보라·분홍 막대는 정기보고서·공식 IR에서 확인한 수주잔고·신규수주다. 노란 선은 같은 공시 범위의 연속 분기 수주잔고만 비교한 QoQ이며, 범위가 바뀌거나 분기가 빠지면 선을 잇지 않는다. 신규수주 합계를 공개하지 않은 종목은 단일판매·공급계약 공시액을 청록·주황 막대의 공개 신규계약 하한으로 따로 표시하며, 이를 회사 전체 신규수주로 바꾸지 않는다.</p>
    {unit === "억원" && <Explanation items={[meaning]} />}
  </div>;
}

export function OrderQuarterlyChart({ points }: { points: ChartPoint[] }) {
  return <OrdersPanel points={points} meaning={fundamentalMetricMeanings(withOrderBacklogQoq(points.filter((point) => !point.isCurrentQuarter)))[5]} />;
}

export default function QuarterlyChart({ points, orderPoints = points, showOrders = true, interpretations = [] }: { points: ChartPoint[]; orderPoints?: ChartPoint[]; showOrders?: boolean; interpretations?: QuarterInterpretation[] }) {
  if (!points.length && !orderPoints.length) return <p className="py-8 text-center text-sm text-white">분기 재무가 아직 없다.</p>;
  // 현재 위치 해설은 발표된 분기만 본다. 점선 컨센서스를 현재 실적으로 오인하지 않는다.
  const meanings = fundamentalMetricMeanings(withOrderBacklogQoq(
    points.filter((point) => !point.isCurrentQuarter)
  ));
  return <ReviewContext.Provider value={interpretations}><div className="grid gap-3 md:grid-cols-2">
    <RevenuePanel points={points} meaning={meanings[0]} />
    <EarningsPanel points={points} meanings={meanings.slice(1, 3)} />
    <GrowthLinePanel points={points} meanings={meanings.slice(3, 5)} />
    {showOrders && <OrderQuarterlyChart points={orderPoints} />}
  </div></ReviewContext.Provider>;
}
