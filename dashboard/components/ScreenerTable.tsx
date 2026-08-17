"use client";
// PRD Ref: §9 /screener — 전 종목 스크리너
//
// ★ 이 화면만 **탈락 종목까지** 보여준다. 다른 화면은 가속 중인 종목만 담지만,
//   여기는 "왜 안 걸렸나"를 확인하는 곳이라 전수가 필요하다.
import { useMemo, useState } from "react";
import Link from "next/link";
import { GRADE_COLOR, type Grade } from "@/lib/types";

export interface ScreenerRow {
  code: string;
  name: string;
  board: string | null;
  industry: string | null;
  marketCap: number | null;
  quarter: string;
  gatePassed: boolean | null;
  grade: Grade | null;
  score: number | null;
  pri: number | null;
  hasConsensus: boolean | null;
  baseEffect: boolean | null;
  failReasons: string[];
}

type GateFilter = "all" | "passed" | "failed" | "undecided";
type CapFilter = "all" | "large" | "mid" | "small";

const CAP_BOUNDS: Record<Exclude<CapFilter, "all">, [number, number]> = {
  large: [1e12, Infinity],
  mid: [3e11, 1e12],
  small: [0, 3e11],
};

const CAP_LABEL: Record<CapFilter, string> = {
  all: "전체",
  large: "1조 이상",
  mid: "3천억~1조",
  small: "3천억 미만",
};

function fmtCap(value: number | null): string {
  if (value == null) return "—";
  return value >= 1e12
    ? `${(value / 1e12).toFixed(1)}조`
    : `${Math.round(value / 1e8).toLocaleString("ko-KR")}억`;
}

function fmtNum(value: number | null, digits = 1): string {
  return value == null ? "—" : value.toFixed(digits);
}

export default function ScreenerTable({ rows }: { rows: ScreenerRow[] }) {
  const [query, setQuery] = useState("");
  const [gate, setGate] = useState<GateFilter>("passed");
  const [grade, setGrade] = useState<Grade | "all">("all");
  const [industry, setIndustry] = useState("all");
  const [cap, setCap] = useState<CapFilter>("all");
  const [consensus, setConsensus] = useState<"all" | "yes" | "no">("all");
  const [quarter, setQuarter] = useState("all");

  const industries = useMemo(
    () =>
      [...new Set(rows.map((r) => r.industry).filter((v): v is string => !!v))].sort(
        (a, b) => a.localeCompare(b, "ko")
      ),
    [rows]
  );
  const quarters = useMemo(
    () => [...new Set(rows.map((r) => r.quarter))].sort().reverse(),
    [rows]
  );

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return rows
      .filter((r) => {
        if (needle && !r.name.toLowerCase().includes(needle) && !r.code.includes(needle))
          return false;
        if (gate === "passed" && r.gatePassed !== true) return false;
        if (gate === "failed" && r.gatePassed !== false) return false;
        if (gate === "undecided" && r.gatePassed != null) return false;
        if (grade !== "all" && r.grade !== grade) return false;
        if (industry !== "all" && r.industry !== industry) return false;
        if (quarter !== "all" && r.quarter !== quarter) return false;
        if (consensus === "yes" && !r.hasConsensus) return false;
        if (consensus === "no" && r.hasConsensus) return false;
        if (cap !== "all") {
          const [lo, hi] = CAP_BOUNDS[cap];
          const v = r.marketCap ?? -1;
          if (v < lo || v >= hi) return false;
        }
        return true;
      })
      .sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  }, [rows, query, gate, grade, industry, cap, consensus, quarter]);

  const select =
    "rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-slate-200";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="종목명 또는 코드"
          className={`${select} w-44 placeholder:text-slate-400`}
          aria-label="종목 검색"
        />
        <select
          value={gate}
          onChange={(e) => setGate(e.target.value as GateFilter)}
          className={select}
          aria-label="게이트"
        >
          <option value="passed">가속 중 (통과)</option>
          <option value="failed">탈락</option>
          <option value="undecided">판정 불가</option>
          <option value="all">게이트 전체</option>
        </select>
        <select
          value={grade}
          onChange={(e) => setGrade(e.target.value as Grade | "all")}
          className={select}
          aria-label="등급"
        >
          <option value="all">등급 전체</option>
          {(["★", "○", "△", "·", "✕"] as Grade[]).map((g) => (
            <option key={g} value={g}>{g}</option>
          ))}
        </select>
        <select
          value={quarter}
          onChange={(e) => setQuarter(e.target.value)}
          className={select}
          aria-label="분기"
        >
          <option value="all">분기 전체</option>
          {quarters.map((q) => <option key={q} value={q}>{q}</option>)}
        </select>
        <select
          value={cap}
          onChange={(e) => setCap(e.target.value as CapFilter)}
          className={select}
          aria-label="시가총액"
        >
          {(Object.keys(CAP_LABEL) as CapFilter[]).map((k) => (
            <option key={k} value={k}>{CAP_LABEL[k]}</option>
          ))}
        </select>
        <select
          value={consensus}
          onChange={(e) => setConsensus(e.target.value as "all" | "yes" | "no")}
          className={select}
          aria-label="컨센서스"
        >
          <option value="all">컨센 전체</option>
          <option value="yes">컨센 있음</option>
          <option value="no">컨센 없음</option>
        </select>
        <select
          value={industry}
          onChange={(e) => setIndustry(e.target.value)}
          className={`${select} max-w-[14rem]`}
          aria-label="업종"
        >
          <option value="all">업종 전체 ({industries.length})</option>
          {industries.map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
      </div>

      <p className="text-sm text-slate-300">
        {filtered.length.toLocaleString("ko-KR")}종목
        <span className="text-slate-400"> / 전체 {rows.length.toLocaleString("ko-KR")}</span>
      </p>

      {/* ★ 높이를 제한해야 머리글 sticky가 먹는다(T64). 300행을 훑어 내려가는
          화면이라 여기가 가장 필요하다. */}
      <div className="max-h-[70vh] overflow-auto rounded-lg border border-slate-800">
        <table className="w-full min-w-[940px] text-sm">
          <thead className="sticky top-0 z-20 bg-slate-900 text-xs uppercase text-slate-300 shadow-[0_1px_0_0_rgba(148,163,184,0.35)]">
            <tr>
              <th className="px-3 py-2 text-left">등급</th>
              <th className="px-3 py-2 text-left">종목</th>
              <th className="px-3 py-2 text-left">업종</th>
              <th className="px-3 py-2 text-left">분기</th>
              <th className="px-3 py-2 text-right">스코어</th>
              <th className="px-3 py-2 text-right">반영도</th>
              <th className="px-3 py-2 text-right">시총</th>
              <th className="px-3 py-2 text-left">게이트</th>
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, 300).map((r) => (
              <tr key={r.code} className="border-t border-slate-800/60 hover:bg-slate-900/40">
                <td className="px-3 py-1.5">
                  {r.grade ? (
                    <span className="font-semibold" style={{ color: GRADE_COLOR[r.grade] }}>
                      {r.grade}
                    </span>
                  ) : (
                    <span className="text-slate-700">—</span>
                  )}
                </td>
                <td className="px-3 py-1.5">
                  <Link href={`/stock/${r.code}`} className="text-sky-400 hover:underline">
                    {r.name}
                  </Link>
                  <span className="ml-2 text-xs text-slate-400">{r.code}</span>
                </td>
                <td className="max-w-[12rem] truncate px-3 py-1.5 text-xs text-slate-400">
                  {r.industry ?? "—"}
                </td>
                <td className="px-3 py-1.5 text-slate-300">{r.quarter}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtNum(r.score)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{fmtNum(r.pri)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums text-slate-300">
                  {fmtCap(r.marketCap)}
                </td>
                <td className="px-3 py-1.5 text-xs">
                  {r.gatePassed === true ? (
                    <span className="text-emerald-400">통과</span>
                  ) : r.gatePassed === false ? (
                    // ★ 왜 떨어졌는지가 이 화면의 존재 이유다.
                    <span className="text-slate-400">{r.failReasons.join(" · ") || "탈락"}</span>
                  ) : (
                    <span className="text-slate-400">판정 불가</span>
                  )}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={8} className="px-3 py-10 text-center text-slate-400">
                  조건에 맞는 종목이 없다.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {filtered.length > 300 && (
        <p className="text-xs text-slate-400">
          상위 300종목만 표시한다 (스코어 순) · 조건이 {filtered.length.toLocaleString("ko-KR")}종목에
          걸렸다. 필터를 좁혀라.
        </p>
      )}
    </div>
  );
}
