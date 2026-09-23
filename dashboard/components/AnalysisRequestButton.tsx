"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

type State = {
  status: string;
  message?: string;
  error?: string;
  requested_at?: string;
  claimed_at?: string;
  completed_at?: string;
};

const LABEL: Record<string, string> = {
  idle: "LLM 분석 실행",
  pending: "분석 요청 접수 · 실행 대기",
  working: "LLM 분석 진행 중",
  deferred: "사용량 갱신 후 자동 재개",
  completed: "분석 완료 · 결과 새로고침",
  failed: "분석 실패 · 다시 요청",
};

const PROGRESS: Record<string, { pct: number; step: string }> = {
  idle: { pct: 0, step: "요청 전" },
  pending: { pct: 25, step: "1/4 접수 완료 · 처리 순서 대기" },
  deferred: { pct: 25, step: "1/4 접수 보존 · 사용량 갱신 대기" },
  working: { pct: 65, step: "2~3/4 입력 조립 · 공개 원문 확인 · LLM 분석/검증" },
  completed: { pct: 100, step: "4/4 결과 검증·저장 완료" },
  failed: { pct: 65, step: "처리 중단 · 오류 확인 후 재요청 가능" },
};

function timeLabel(value?: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
  }).format(date);
}

function errorLabel(value?: string): string | null {
  if (!value) return null;
  if (/domains are not accessible to our user agent/i.test(value)) {
    return "공개 웹검색 출처가 검색 도구에 의해 차단되었습니다. 수정된 worker는 같은 모델로 검색 없이 다시 분석합니다. 다시 요청해 주세요.";
  }
  if (/budget|limit|usage|ceiling/i.test(value)) return "사용량 한도 때문에 대기 중입니다. 한도 갱신 뒤 자동 재개합니다.";
  return value.length > 240 ? `${value.slice(0, 240)}…` : value;
}

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
    const nextActive = ["pending", "working", "deferred"].includes(next.status);
    if (nextActive && !polling.current) {
      polling.current = setInterval(() => { read().catch(() => undefined); }, 10_000);
    }
    if (!nextActive && polling.current) {
      clearInterval(polling.current);
      polling.current = null;
    }
    if (next.status === "completed") {
      router.refresh();
    }
  };
  useEffect(() => { read().catch(() => undefined); return () => {
    if (polling.current) clearInterval(polling.current);
    polling.current = null;
  }; }, []);

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
  const progress = PROGRESS[state.status] ?? PROGRESS.idle;
  const requestedAt = timeLabel(state.requested_at);
  const claimedAt = timeLabel(state.claimed_at);
  const visibleMessage = state.message ?? errorLabel(state.error);
  return <div className="mb-4 rounded-lg border border-violet-700/70 bg-violet-950/25 p-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div>
        <div className="text-sm font-bold text-violet-100">기업 투자판단 LLM 분석</div>
        <p className="mt-1 text-xs leading-relaxed text-slate-300">클릭한 현재 날짜를 분석 기준일로 다시 저장한다.<br />기업 개요·제품별 매출 비중·핵심 투자 아이디어·실적 원인·향후 전망·주가 구간별 상승/하락 원인·리스크를 공시와 공개 원문으로 분석한다.</p>
      </div>
      <button type="button" onClick={request} disabled={active}
        className="rounded-lg bg-violet-500 px-4 py-2 text-sm font-bold text-white shadow-lg shadow-violet-950/40 hover:bg-violet-400 disabled:cursor-wait disabled:bg-slate-600">
        {active && <span className="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-white" />}
        {(state.status === "completed" || state.status === "idle") && hasAnalysis ? "현재 기준 LLM 다시 분석" : LABEL[state.status] ?? "LLM 분석 실행"}
      </button>
    </div>
    {state.status !== "idle" && <div className="mt-4" aria-label="LLM 분석 처리 단계 진행률">
      <div className="mb-1.5 flex items-center justify-between gap-3 text-xs">
        <span className={state.status === "failed" ? "font-bold text-rose-300" : "font-bold text-violet-100"}>{progress.step}</span>
        <span className="font-black text-violet-200">{progress.pct}%</span>
      </div>
      <div className="h-2.5 overflow-hidden rounded-full bg-slate-800" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress.pct}>
        <div className={`h-full rounded-full transition-[width] duration-500 ${state.status === "failed" ? "bg-rose-500" : state.status === "completed" ? "bg-emerald-400" : "bg-violet-400"}`} style={{ width: `${progress.pct}%` }} />
      </div>
      <p className="mt-1.5 text-[11px] text-slate-400">
        단계 기준 진행률이며 모델 내부 토큰 생성률은 아닙니다.
        {requestedAt && <> · 접수 {requestedAt}</>}{claimedAt && <> · 처리 시작 {claimedAt}</>}
      </p>
    </div>}
    {visibleMessage && <p className="mt-2 text-xs leading-5 text-amber-200">{visibleMessage}</p>}
    {active && <p className="mt-2 text-[11px] text-slate-400">보통 5~15분 안에 시작한다. 일·월 사용량이 소진되면 상태를 보존하고 갱신 후 자동 재개한다.</p>}
  </div>;
}
