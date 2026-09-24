"use client";
// PRD Ref: §9 · §10 — 미국 시장 온도 그래프·S&P 500 히트맵

import { useEffect, useRef } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { MacroContext, MacroMarketSeries } from "@/lib/macroContext";

const tooltipStyle = { backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: 8 };

type SentimentNasdaqPoint = { date: string; fearGreed: number; nasdaq: number };

export function alignFearGreedAndNasdaq(
  fearHistory: { date: string; value: number }[],
  nasdaqHistory: { date: string; value: number }[]
): SentimentNasdaqPoint[] {
  const nasdaqByDate = new Map(nasdaqHistory.map((point) => [point.date, point.value]));
  return fearHistory.flatMap((point) => {
    const nasdaq = nasdaqByDate.get(point.date);
    return nasdaq == null ? [] : [{ date: point.date, fearGreed: point.value, nasdaq }];
  });
}

export function dailyChangeCorrelation(points: SentimentNasdaqPoint[]): number | null {
  const pairs = points.slice(1).map((point, index) => {
    const previous = points[index];
    return [point.fearGreed - previous.fearGreed, (point.nasdaq / previous.nasdaq - 1) * 100];
  }).filter(([fearDelta, nasdaqPct]) => Number.isFinite(fearDelta) && Number.isFinite(nasdaqPct));
  if (pairs.length < 3) return null;
  const fearMean = pairs.reduce((sum, pair) => sum + pair[0], 0) / pairs.length;
  const nasdaqMean = pairs.reduce((sum, pair) => sum + pair[1], 0) / pairs.length;
  const covariance = pairs.reduce((sum, pair) => sum + (pair[0] - fearMean) * (pair[1] - nasdaqMean), 0);
  const fearVariance = pairs.reduce((sum, pair) => sum + (pair[0] - fearMean) ** 2, 0);
  const nasdaqVariance = pairs.reduce((sum, pair) => sum + (pair[1] - nasdaqMean) ** 2, 0);
  const denominator = Math.sqrt(fearVariance * nasdaqVariance);
  return denominator === 0 ? null : covariance / denominator;
}

function IndexCard({ label, row }: { label: string; row?: MacroMarketSeries }) {
  const positive = (row?.changePct ?? 0) >= 0;
  return <div className="rounded-lg border border-slate-700 bg-slate-950/60 p-3">
    <div className="text-xs font-bold text-slate-300">{label}</div>
    <div className="mt-1 flex items-baseline justify-between gap-2">
      <strong className="text-lg text-white">{row?.close != null ? row.close.toLocaleString("ko-KR", { maximumFractionDigits: 2 }) : "—"}</strong>
      <span className={`text-sm font-black ${positive ? "text-emerald-300" : "text-rose-300"}`}>{row?.changePct != null ? `${positive ? "+" : ""}${row.changePct.toFixed(2)}%` : "—"}</span>
    </div>
  </div>;
}

function SentimentBar({ value, label }: { value: number | null; label: string }) {
  const bounded = Math.max(0, Math.min(100, value ?? 0));
  return <div>
    <div className="mb-1 flex items-center justify-between text-xs"><strong className="text-white">{label}</strong><span className="font-black text-sky-200">{value == null ? "—" : value.toFixed(1)}</span></div>
    <div className="relative h-3 overflow-hidden rounded-full bg-gradient-to-r from-rose-600 via-amber-400 to-emerald-500">
      {value != null && <span className="absolute top-1/2 h-5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded bg-white shadow" style={{ left: `${bounded}%` }} />}
    </div>
    <div className="mt-1 flex justify-between text-[10px] text-slate-400"><span>공포</span><span>중립</span><span>탐욕</span></div>
  </div>;
}

function TradingViewHeatmap() {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!host.current) return;
    host.current.replaceChildren();
    const widget = document.createElement("div");
    widget.className = "tradingview-widget-container__widget h-full";
    const script = document.createElement("script");
    script.src = "https://s3.tradingview.com/external-embedding/embed-widget-stock-heatmap.js";
    script.async = true;
    script.text = JSON.stringify({
      dataSource: "SPX500", blockSize: "market_cap_basic", blockColor: "change",
      grouping: "sector", locale: "kr", colorTheme: "dark", hasTopBar: false,
      isDataSetEnabled: false, isZoomEnabled: true, hasSymbolTooltip: true,
      isMonoSize: false, width: "100%", height: "100%",
    });
    host.current.append(widget, script);
    return () => host.current?.replaceChildren();
  }, []);
  return <div ref={host} className="tradingview-widget-container h-[420px] overflow-hidden rounded-lg bg-slate-950" aria-label="S&P 500 미국 증시 맵" />;
}

export default function MacroMarketOverview({ context }: { context: MacroContext }) {
  const markets = context.markets ?? {};
  const vix = markets.vix;
  const nasdaq = markets.nasdaq;
  const fearGreed = context.fearGreed;
  const sentimentNasdaq = alignFearGreedAndNasdaq(fearGreed?.history ?? [], nasdaq?.history ?? []);
  const correlation = dailyChangeCorrelation(sentimentNasdaq);
  const correlationStrength = correlation == null ? "측정 불가" : Math.abs(correlation) >= 0.7 ? "강한" : Math.abs(correlation) >= 0.4 ? "보통" : "약한";
  const correlationDirection = correlation == null ? "" : correlation >= 0 ? "동행" : "역행";
  const vixMood = vix?.close == null ? null : Math.max(0, Math.min(100, 100 - (vix.close - 10) * 4));
  return <div className="space-y-4">
    <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
      <IndexCard label="S&P 500" row={markets.sp500} />
      <IndexCard label="나스닥 종합" row={markets.nasdaq} />
      <IndexCard label="다우 지수" row={markets.dow} />
      <IndexCard label="SOX 반도체" row={markets.semiconductor} />
    </div>

    <div className="grid gap-3 xl:grid-cols-2">
      <article className="rounded-xl border border-slate-700 bg-slate-950/55 p-4">
        <h4 className="text-base font-black text-white">CBOE VIX · 60거래일</h4>
        <p className="mt-1 text-xs leading-5 text-slate-300">S&P 500 옵션이 반영하는 향후 30일 변동성 기대다. 20 아래는 비교적 안정, 25 이상은 위험회피 경계로 본다.</p>
        <div className="mt-3 h-44"><ResponsiveContainer width="100%" height="100%"><LineChart data={vix?.history ?? []} syncId="macro-sentiment">
          <CartesianGrid stroke="#1e293b" vertical={false} /><XAxis dataKey="date" stroke="#94a3b8" fontSize={9} minTickGap={38} /><YAxis domain={[0, "auto"]} stroke="#94a3b8" fontSize={9} /><ReferenceLine y={20} stroke="#facc15" strokeDasharray="3 3" /><ReferenceLine y={25} stroke="#fb7185" strokeDasharray="3 3" /><Tooltip contentStyle={tooltipStyle} formatter={(value) => [Number(value).toFixed(2), "VIX"]} /><Line dataKey="value" stroke="#38bdf8" strokeWidth={2.5} dot={false} isAnimationActive={false} />
        </LineChart></ResponsiveContainer></div>
        <SentimentBar value={vixMood} label={`변동성 심리 환산 · VIX ${vix?.close?.toFixed(2) ?? "—"}`} />
      </article>

      <article className="rounded-xl border border-slate-700 bg-slate-950/55 p-4">
        <h4 className="text-base font-black text-white">Fear & Greed × 나스닥 · 60거래일</h4>
        <p className="mt-1 text-xs leading-5 text-slate-300">심리지수(왼쪽 축)와 나스닥 종가(오른쪽 축)를 같은 날짜에 겹쳤다. 상관계수는 두 지수의 수준이 아니라 일간 변화로 계산하므로 방향 동행성을 보는 보조지표이며 인과관계를 뜻하지 않는다.</p>
        <div className="mt-2 flex flex-wrap gap-2 text-[10px] font-bold"><span className="rounded-full bg-violet-400/15 px-2 py-1 text-violet-200">● Fear & Greed</span><span className="rounded-full bg-amber-400/15 px-2 py-1 text-amber-200">● 나스닥 종가</span></div>
        <div className="mt-2 h-44"><ResponsiveContainer width="100%" height="100%"><LineChart data={sentimentNasdaq} syncId="macro-sentiment">
          <CartesianGrid stroke="#1e293b" vertical={false} /><XAxis dataKey="date" stroke="#94a3b8" fontSize={9} minTickGap={38} /><YAxis yAxisId="sentiment" domain={[0, 100]} ticks={[25, 50, 75]} stroke="#c084fc" fontSize={9} /><YAxis yAxisId="nasdaq" orientation="right" domain={["auto", "auto"]} stroke="#fbbf24" fontSize={9} tickFormatter={(value) => Number(value).toLocaleString("ko-KR", { maximumFractionDigits: 0 })} width={48} /><ReferenceLine yAxisId="sentiment" y={25} stroke="#fb7185" strokeDasharray="3 3" /><ReferenceLine yAxisId="sentiment" y={50} stroke="#cbd5e1" strokeDasharray="3 3" /><ReferenceLine yAxisId="sentiment" y={75} stroke="#34d399" strokeDasharray="3 3" /><Tooltip contentStyle={tooltipStyle} formatter={(value, name) => [name === "나스닥" ? Number(value).toLocaleString("ko-KR", { maximumFractionDigits: 2 }) : Number(value).toFixed(1), name]} /><Line yAxisId="sentiment" dataKey="fearGreed" name="Fear & Greed" stroke="#c084fc" strokeWidth={2.5} dot={false} isAnimationActive={false} /><Line yAxisId="nasdaq" dataKey="nasdaq" name="나스닥" stroke="#fbbf24" strokeWidth={2.2} dot={false} isAnimationActive={false} />
        </LineChart></ResponsiveContainer></div>
        <p className="mb-3 rounded-lg border border-slate-700 bg-slate-900/70 px-3 py-2 text-[11px] text-slate-200">최근 {Math.max(0, sentimentNasdaq.length - 1)}회 일간 변화 상관계수 <strong className="text-white">r {correlation == null ? "—" : `${correlation >= 0 ? "+" : ""}${correlation.toFixed(2)}`}</strong> · {correlationStrength}{correlationDirection}</p>
        <SentimentBar value={fearGreed?.value ?? null} label={fearGreed ? `${fearGreed.label} · ${fearGreed.date}` : "Fear & Greed 미수집"} />
        {fearGreed && <a href={`/macro/translation?source=${encodeURIComponent(fearGreed.sourceUrl)}`} target="_blank" rel="noreferrer" className="mt-2 inline-block text-[11px] text-sky-300 underline">{fearGreed.sourceLabel} · 한국어 설명</a>}
      </article>
    </div>

    <article className="rounded-xl border border-slate-700 bg-slate-950/55 p-4">
      <div className="mb-3 flex items-center justify-between gap-2"><h4 className="text-base font-black text-white">미국 증시 맵 · S&P 500</h4><a href="https://www.tradingview.com/heatmap/stock/?color=change&dataset=SPX500&group=sector&size=market_cap_basic" target="_blank" rel="noreferrer" className="text-xs font-bold text-sky-300 underline">전체 화면</a></div>
      <TradingViewHeatmap />
      <p className="mt-2 text-[11px] text-slate-400">사각형 크기는 시가총액, 색은 당일 등락률이다. 개별 종목 색보다 같은 섹터가 함께 움직이는지 먼저 본다.</p>
    </article>
  </div>;
}
