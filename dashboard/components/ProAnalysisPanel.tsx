"use client";
// PRD Ref: §9 · ADR50
import {useEffect, useRef, useState} from "react";
import {ANALYSIS_SESSION_KEY, analysisHeaders} from "@/lib/pro-analysis-client";

export default function ProAnalysisPanel() {
  const [kind, setKind] = useState("market"), [target, setTarget] = useState("시장·매크로");
  const [password, setPassword] = useState("");
  const [periods, setPeriods] = useState("");
  const [state, setState] = useState<any>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {setPassword(sessionStorage.getItem(ANALYSIS_SESSION_KEY) ?? ""); return () => {if (timer.current) clearInterval(timer.current);};}, []);
  const read = async (query: URLSearchParams) => {
    const response = await fetch(`/api/pro-analysis?${query}`, {cache: "no-store", headers: analysisHeaders()});
    const value = await response.json(); setState(value);
    if (!["pending", "working", "deferred"].includes(value.status) && timer.current) {clearInterval(timer.current); timer.current = null;}
  };
  const submit = async () => {
    const parsed = periods.split(",").filter(x => x.trim()).map(x => {const [year, quarter] = x.trim().split(".").map(Number); return {year, quarter};});
    const historical = kind === "history";
    const body = {kind: historical ? "company" : kind, target, historical, periods: parsed};
    setState({status: "pending", message: "접수 확인 중"});
    try {
      const response = await fetch("/api/pro-analysis", {method: "POST", headers: analysisHeaders(), body: JSON.stringify(body)});
      const value = await response.json(); setState(value);
      if (timer.current) clearInterval(timer.current);
      if (response.ok) {
        const q = new URLSearchParams({kind: body.kind, target});
        if (historical && parsed[0]) {q.set("year", String(parsed[0].year)); q.set("quarter", String(parsed[0].quarter));}
        timer.current = setInterval(() => {read(q).catch(() => undefined);}, 10000);
      }
    } catch {setState({status: "unavailable", message: "연결을 확인하지 못했습니다. 접수 상태 확인 후 재시도해 주세요."});}
  };
  const active = ["pending", "working", "deferred"].includes(state?.status);
  return <details className="mb-4 rounded-xl border border-violet-500/50 bg-slate-900 p-4 text-white">
    <summary className="cursor-pointer font-bold text-violet-200">분석 · 시장 / 산업 / 전략 / 과거 분기</summary>
    <p className="mt-3 text-sm">주가·매크로 등 변동 지표는 평일 16시 자동 갱신하며 한국 공휴일에는 쉽니다. 종목을 포함한 해설·보고서는 분석을 요청할 때 갱신합니다.</p>
    <label className="mt-3 block text-sm">분석 암호 <input type="password" autoComplete="off" value={password} onChange={e => {setPassword(e.target.value); sessionStorage.setItem(ANALYSIS_SESSION_KEY, e.target.value);}} className="ml-2 rounded bg-slate-800 p-2" /></label>
    <div className="mt-3 flex flex-wrap gap-2">
      <select aria-label="분석 유형" value={kind} onChange={e => {setKind(e.target.value); setTarget(e.target.value === "market" ? "시장·매크로" : e.target.value === "strategy" ? "실적 시즌 전략" : ""); setState(null);}} className="rounded bg-slate-800 p-2"><option value="market">시장·매크로</option><option value="industry">산업</option><option value="strategy">전략·전망</option><option value="history">과거 분기 일괄 분석</option></select>
      <input aria-label="분석 대상" placeholder={kind === "history" ? "6자리 종목코드" : "분석 대상"} value={target} onChange={e => setTarget(e.target.value)} className="rounded bg-slate-800 p-2" />
      {kind === "history" && <input aria-label="과거 분기 범위" placeholder="예: 2025.1,2025.2,2025.3" value={periods} onChange={e => setPeriods(e.target.value)} className="rounded bg-slate-800 p-2" />}
      <button disabled={active || !password || !target} onClick={submit} className="rounded bg-violet-600 px-4 py-2 font-bold disabled:bg-slate-700">분석</button>
    </div>
    {state && <p className="mt-3 text-sm">{({pending:"접수 완료 · 순서 대기",working:"작성·검수 중",deferred:"사용량 갱신 후 재개",completed:"검수·저장 완료",failed:"분석 중단",forbidden:"분석 암호를 확인해 주세요",unavailable:"접수 서버 연결 확인 필요"} as Record<string,string>)[state.status] ?? state.status}{state.queued ? ` · ${state.queued}건 접수` : ""}{state.message ? ` · ${state.message}` : ""}</p>}
    {state?.result?.report && <article className="mt-4 whitespace-pre-wrap border-t border-slate-600 pt-4 text-sm leading-7"><h3 className="font-bold">{state.result.title}</h3>{state.result.report}</article>}
    <p className="mt-2 text-xs">Pro 구독 사용량으로 순차 처리합니다. 과거 분석은 현재 요청보다 낮은 우선순위이며 PC가 꺼져 있거나 한도에 닿으면 저장 후 대기합니다.</p>
  </details>;
}
