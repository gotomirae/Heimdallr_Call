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
  const fearGreed = context.fearGreed;
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
        <h4 className="text-base font-black text-white">Fear & Greed Index · 60거래일</h4>
        <p className="mt-1 text-xs leading-5 text-slate-300">7개 시장 심리 신호를 0~100으로 합친 지수다. 25 미만은 극도의 공포, 75 초과는 극도의 탐욕이며 방향 전환을 함께 본다.</p>
        <div className="mt-3 h-44"><ResponsiveContainer width="100%" height="100%"><LineChart data={fearGreed?.history ?? []} syncId="macro-sentiment">
          <CartesianGrid stroke="#1e293b" vertical={false} /><XAxis dataKey="date" stroke="#94a3b8" fontSize={9} minTickGap={38} /><YAxis domain={[0, 100]} ticks={[25, 50, 75]} stroke="#94a3b8" fontSize={9} /><ReferenceLine y={25} stroke="#fb7185" strokeDasharray="3 3" /><ReferenceLine y={50} stroke="#cbd5e1" strokeDasharray="3 3" /><ReferenceLine y={75} stroke="#34d399" strokeDasharray="3 3" /><Tooltip contentStyle={tooltipStyle} formatter={(value) => [Number(value).toFixed(1), "Fear & Greed"]} /><Line dataKey="value" stroke="#c084fc" strokeWidth={2.5} dot={false} isAnimationActive={false} />
        </LineChart></ResponsiveContainer></div>
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
