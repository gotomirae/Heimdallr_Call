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
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { macdMeaning, priceMeaning, rsiMeaning, type MetricMeaning } from "@/lib/metricMeaning";
import { normalizeDailyRows, technicalIndicators } from "@/lib/technicalIndicators";
import type { DisclosureRow } from "@/lib/types";
import type { NaverDailyPrice, NaverInvestorFlow } from "@/lib/naver";

const tooltipStyle = { backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: 6 };

function Tooltip(props: React.ComponentProps<typeof ChartTooltip>) {
  return <ChartTooltip {...props} reverseDirection={{ x: true, y: false }} allowEscapeViewBox={{ x: true, y: false }} />;
}

function causalSegments(text: string): string[] {
  return text
    .split(/\n+|(?<=\.)\s+/)
    .map((part) => part.trim())
    .filter(Boolean)
    .slice(0, 10);
}

function Explanation({ item, evidence, outlook }: { item: MetricMeaning; evidence?: string | null; outlook?: string | null }) {
  return <div className="mt-2 rounded border border-slate-800 bg-slate-900/60 p-3">
    <div className="text-lg font-black tracking-tight text-sky-200">현재 위치 · {item.label}</div>
    <div className="mt-0.5 text-sm font-semibold text-slate-100">{item.value}</div>
    <p className="mt-1 text-xs leading-relaxed text-slate-300">{item.meaning}</p>
    {evidence && <div className="mt-3 rounded border border-violet-800/70 bg-violet-950/20 p-3">
      <strong className="text-xs text-violet-200">주요 시기별 주가 상승·하락 원인</strong>
      <ol className="mt-2 space-y-2 text-xs leading-relaxed text-slate-100">
        {causalSegments(evidence).map((segment, index) => <li key={`${index}-${segment.slice(0, 24)}`} className="flex gap-2">
          <span className="font-bold text-violet-300">{index + 1}</span><span>{segment}</span>
        </li>)}
      </ol>
    </div>}
    {outlook && <p className="mt-2 border-l-2 border-amber-400 pl-2 text-xs leading-relaxed text-amber-100"><strong>현재 반영 수준·향후 전망 · </strong>{outlook}</p>}
    {item.action && <p className="mt-2 text-xs leading-relaxed text-emerald-200"><strong>투자전략 · </strong>{item.action}</p>}
    <p className="mt-1 text-[11px] leading-relaxed text-amber-200">다음 확인: {item.watch}</p>
  </div>;
}

function announcementDates(points: NaverDailyPrice[], disclosures: DisclosureRow[]): Array<{ date: string; title: string }> {
  const dates = points.map((point) => point.trade_date);
  const picked = new Map<string, { date: string; title: string }>();
  for (const row of [...disclosures].sort((left, right) => String(left.disclosed_at).localeCompare(String(right.disclosed_at)))) {
    if (!row.disclosed_at || !/잠정|영업.*실적|분기보고서|반기보고서|사업보고서/.test(row.report_nm ?? "")) continue;
    const disclosed = row.disclosed_at.slice(0, 10);
    if (!dates.length || disclosed < dates[0] || disclosed > dates[dates.length - 1]) continue;
    const marketDate = dates.find((date) => date >= disclosed);
    if (!marketDate) continue;
    const quarter = row.fiscal_year && row.fiscal_quarter ? `${String(row.fiscal_year).slice(-2)}.${row.fiscal_quarter}Q` : "실적";
    const kind = /잠정|영업.*실적/.test(row.report_nm ?? "") && row.doc_type !== "periodic" ? "잠정" : "확정";
    const key = `${quarter}-${kind}`;
    if (!picked.has(key)) picked.set(key, { date: marketDate, title: `${quarter}(${kind}) · ${disclosed}` });
  }
  return [...picked.values()].sort((left, right) => left.date.localeCompare(right.date));
}

export default function DailyPriceChart({
  points,
  disclosures,
  fromDate,
  high52w,
  priceAnalysis,
  priceOutlook,
  investorFlows = [],
  code,
}: {
  points: NaverDailyPrice[];
  disclosures: DisclosureRow[];
  fromDate?: string;
  high52w?: number | null;
  priceAnalysis?: string | null;
  priceOutlook?: string | null;
  investorFlows?: NaverInvestorFlow[];
  code?: string;
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
  const flowsByDate = new Map(investorFlows.map((row) => [row.trade_date, row]));
  const flowPoints = visible.map((point) => ({ trade_date: point.trade_date,
    foreign: flowsByDate.get(point.trade_date)?.foreign ?? null,
    institution: flowsByDate.get(point.trade_date)?.institution ?? null }));
  const flowCount = flowPoints.filter((point) => point.foreign != null && point.institution != null).length;
  return <div id="daily-technical" className="mt-5 rounded-xl border border-sky-900/70 bg-slate-950/35 p-3">
    <p className="rounded-lg border border-sky-700/50 bg-sky-950/30 px-3 py-2 text-xs text-sky-100">
      같은 날짜 축으로 연결했다. 한 그래프의 특정 시기를 가리키면 일간 종가·MACD·RSI의 세로 커서가 함께 이동한다.
    </p>
    <div className="mt-2 overflow-hidden rounded-lg border border-slate-800 bg-slate-950/50">
    <div className="px-2 pt-2">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm font-black text-white">
        <span>일간 종가</span>
        <span className="font-normal text-slate-400">점선 = 잠정·확정 분기실적 발표일 · {visible.length}거래일</span>
      </div>
      <div className="h-48"><ResponsiveContainer width="100%" height="100%"><LineChart data={visible} syncId="daily-technical" syncMethod="value" margin={{ top: 12, right: 8, left: 4, bottom: 0 }}>
        <CartesianGrid stroke="#1e293b" vertical={false} />
        <XAxis dataKey="trade_date" hide />
        <YAxis domain={["auto", "auto"]} stroke="#94a3b8" fontSize={9} tickFormatter={(v) => Number(v).toLocaleString("ko-KR")} />
        <Tooltip reverseDirection={{ x: true, y: false }} allowEscapeViewBox={{ x: true, y: false }} formatter={(v) => [`${Number(v).toLocaleString("ko-KR")}원`, "일간 종가"]} contentStyle={tooltipStyle} />
        {marks.map((mark) => <ReferenceLine key={`${mark.date}-${mark.title}`} x={mark.date} stroke={mark.title.includes("(잠정)") ? "#f59e0b" : "#38bdf8"} strokeDasharray={mark.title.includes("(잠정)") ? "3 3" : "7 3"} />)}
        <Line dataKey="close" stroke="#ef4444" strokeWidth={2} dot={false} isAnimationActive={false} />
      </LineChart></ResponsiveContainer></div>
      <div className="mb-2 flex flex-wrap gap-1.5" aria-label="잠정·확정 실적 발표일 목록">
        {marks.map((mark) => <span key={mark.title} className={`rounded border px-2 py-1 text-[10px] ${mark.title.includes("(잠정)") ? "border-amber-800 text-amber-200" : "border-sky-800 text-sky-200"}`}>{mark.title}</span>)}
      </div>
    </div>
    <div className="border-t border-slate-800 px-2 pt-1">
      <div className="flex items-center justify-between text-sm font-black text-white">
        <span>MACD</span><span className="text-xs font-normal text-slate-400">일간 12·26·9 · MACD=단기·장기 추세 차이 · Signal=MACD 9일 평균 · {macdPoints.length}거래일</span>
      </div>
      {macdPoints.length === 0 ? <div className="flex h-44 items-center justify-center text-xs text-slate-400">MACD 계산에는 최소 26거래일 종가가 필요하다.</div> : <>
        {latestMacd && <div className="mb-1 flex flex-wrap gap-3 text-[10px] text-slate-300"><span>{latestMacd.trade_date}</span><span>MACD {latestMacd.macd?.toFixed(1)}</span><span>Signal {latestMacd.signal?.toFixed(1)}</span><span>Histogram {latestMacd.histogram != null && latestMacd.histogram >= 0 ? "+" : ""}{latestMacd.histogram?.toFixed(1)}</span></div>}
        <div className="h-36"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={macdPoints} syncId="daily-technical" syncMethod="value" margin={{ top: 4, right: 8, left: 4, bottom: 0 }}>
          <CartesianGrid stroke="#1e293b" vertical={false} /><XAxis dataKey="trade_date" hide /><YAxis domain={["auto", "auto"]} stroke="#94a3b8" fontSize={9} tickFormatter={(v) => Number(v).toLocaleString("ko-KR", { maximumFractionDigits: 0 })} /><ReferenceLine y={0} stroke="#94a3b8" strokeWidth={1.2} /><Tooltip formatter={(v, name) => [Number(v).toLocaleString("ko-KR", { maximumFractionDigits: 1 }), name]} contentStyle={tooltipStyle} /><Legend wrapperStyle={{ fontSize: 10 }} />
          <Bar dataKey="histogram" name="Histogram" isAnimationActive={false}>{macdPoints.map((point) => <Cell key={point.trade_date} fill={point.histogram == null ? "#475569" : point.histogram >= 0 ? "#22c55e" : "#ef4444"} fillOpacity={0.72} />)}</Bar><Line type="linear" dataKey="macd" name="MACD" stroke="#38bdf8" strokeWidth={2.4} dot={false} connectNulls={false} isAnimationActive={false} /><Line type="linear" dataKey="signal" name="Signal" stroke="#f59e0b" strokeWidth={2.2} dot={false} connectNulls={false} isAnimationActive={false} />
        </ComposedChart></ResponsiveContainer></div>
      </>}
    </div>
    <div className="border-t border-slate-800 px-2 pt-1">
      <div className="flex flex-wrap justify-between gap-2 text-sm font-black text-white"><span>RSI</span><span className="text-xs font-normal text-slate-400">일간 14 · 최근 14일 상승·하락 힘의 비율 · 45선은 추세 회복 기준</span></div>
      <div className="h-28"><ResponsiveContainer width="100%" height="100%"><LineChart data={visible} syncId="daily-technical" syncMethod="value" margin={{ top: 0, right: 8, left: 4, bottom: 0 }}><CartesianGrid stroke="#1e293b" vertical={false} /><XAxis dataKey="trade_date" stroke="#94a3b8" fontSize={9} minTickGap={44} /><YAxis domain={[0, 100]} ticks={[30, 45, 70]} stroke="#94a3b8" fontSize={9} /><ReferenceLine y={70} stroke="#ef4444" strokeDasharray="3 3" /><ReferenceLine y={45} stroke="#facc15" strokeDasharray="3 3" /><ReferenceLine y={30} stroke="#38bdf8" strokeDasharray="3 3" /><Tooltip formatter={(v) => [Number(v).toFixed(1), "RSI"]} contentStyle={tooltipStyle} /><Line dataKey="rsi" stroke="#c084fc" strokeWidth={2} dot={false} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>
    </div>
    <div className="border-t border-slate-800 px-2 pt-2" id="investor-flow">
      <div className="flex flex-wrap justify-between gap-2 text-sm font-black text-white"><span>🌍 외국인·기관 수급 동향</span><span className="text-[11px] font-normal text-slate-400">일별 순매수량(주) · RSI와 동일 날짜축 · {flowCount}/{visible.length}거래일</span></div>
      <div className="h-36"><ResponsiveContainer width="100%" height="100%"><ComposedChart data={flowPoints} syncId="daily-technical" syncMethod="value" margin={{ top: 6, right: 8, left: 4, bottom: 0 }}>
        <CartesianGrid stroke="#1e293b" vertical={false} /><XAxis dataKey="trade_date" stroke="#94a3b8" fontSize={9} minTickGap={44} /><YAxis stroke="#94a3b8" fontSize={9} tickFormatter={(v) => Number(v).toLocaleString("ko-KR")} /><ReferenceLine y={0} stroke="#94a3b8" />
        <Tooltip formatter={(v, name) => [`${Number(v).toLocaleString("ko-KR")}주`, name]} contentStyle={tooltipStyle} /><Legend wrapperStyle={{ fontSize: 10 }} />
        <Bar dataKey="foreign" name="외국인 순매수" fill="#38bdf8" isAnimationActive={false} /><Bar dataKey="institution" name="기관 순매수" fill="#f59e0b" isAnimationActive={false} />
      </ComposedChart></ResponsiveContainer></div>
      <p className="mb-2 text-[11px] leading-5 text-slate-300">🔎 양수는 순매수, 음수는 순매도입니다. 수급은 참여자의 매매 결과이지 실적 개선의 원인이나 향후 상승 보장이 아닙니다.<br />{flowCount < visible.length && "⚠️ 원천 미제공·미공개·수집 실패 날짜는 빈칸입니다. 0주로 채우거나 기간을 줄이지 않습니다. "}{code && <a className="text-sky-300 underline" href={`https://m.stock.naver.com/api/stock/${code}/trend?pageSize=60`} target="_blank" rel="noreferrer">네이버 수급 원자료</a>}</p>
    </div>
    </div>
    <div className="mt-2 grid gap-2 lg:grid-cols-3">
      <Explanation item={price} evidence={priceAnalysis} outlook={priceOutlook} />
      <Explanation item={macd} />
      <Explanation item={rsi} />
    </div>
  </div>;
}
