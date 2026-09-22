"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

type State = { status: string; message?: string; error?: string };

const LABEL: Record<string, string> = {
  idle: "LLM 분석 실행",
  pending: "분석 요청 접수 · 실행 대기",
  working: "LLM 분석 진행 중",
  deferred: "사용량 갱신 후 자동 재개",
  completed: "분석 완료 · 결과 새로고침",
  failed: "분석 실패 · 다시 요청",
};

export default function AnalysisRequestButton({ code, year, quarter, hasAnalysis }: {
  code: string; year: number; quarter: number; hasAnalysis: boolean;
}) {
  const router = useRouter();
  const [state, setState] = useState<State>({ status: hasAnalysis ? "completed" : "idle" });
  const polling = useRef<ReturnType<typeof setInterval> | null>(null);
  const endpoint = `/api/analysis-request?code=${code}&year=${year}&quarter=${quarter}`;

  const read = async () => {
    const response = await fetch(endpoint, { cache: "no-store" });
    const next = await response.json();
    setState(next);
    if (next.status === "completed") {
      if (polling.current) clearInterval(polling.current);
      router.refresh();
    }
  };
  useEffect(() => { read().catch(() => undefined); return () => { if (polling.current) clearInterval(polling.current); }; }, []);

  const request = async () => {
    setState({ status: "pending", message: "요청을 접수하고 있다." });
    const response = await fetch("/api/analysis-request", {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ code, year, quarter }),
    });
    const next = await response.json();
    setState(next);
    if (["pending", "working", "deferred"].includes(next.status) && !polling.current) {
      polling.current = setInterval(() => { read().catch(() => undefined); }, 10_000);
    }
  };

  const active = ["pending", "working", "deferred"].includes(state.status);
  return <div className="mb-4 rounded-lg border border-violet-700/70 bg-violet-950/25 p-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <div className="text-sm font-bold text-violet-100">기업 투자판단 LLM 분석</div>
        <p className="mt-1 text-xs leading-relaxed text-slate-300">클릭한 현재 날짜를 분석 기준일로 다시 저장한다.<br />기업 개요·제품별 매출 비중·핵심 투자 아이디어·실적 원인·향후 전망·주가 구간별 상승/하락 원인·리스크를 공시와 공개 원문으로 분석한다.</p>
      </div>
      <button type="button" onClick={request} disabled={active}
        className="rounded-lg bg-violet-500 px-4 py-2 text-sm font-bold text-white shadow-lg shadow-violet-950/40 hover:bg-violet-400 disabled:cursor-wait disabled:bg-slate-600">
        {active && <span className="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-white" />}
        {state.status === "completed" && hasAnalysis ? "현재 기준 LLM 다시 분석" : LABEL[state.status] ?? "LLM 분석 실행"}
      </button>
    </div>
    {(state.message || state.error) && <p className="mt-2 text-xs text-amber-200">{state.message ?? state.error}</p>}
    {active && <p className="mt-2 text-[11px] text-slate-400">보통 5~15분 안에 시작한다. 일·월 사용량이 소진되면 상태를 보존하고 갱신 후 자동 재개한다.</p>}
  </div>;
}
