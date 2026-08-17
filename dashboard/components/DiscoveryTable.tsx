"use client";
// PRD Ref: §9 — 발굴 목록 + 스크리너 **한 화면**
//
// ★ 두 화면을 합친 이유: 보던 것이 같았다. 다른 건 "게이트 통과분만 보나,
//   탈락까지 보나"뿐인데 그건 **필터 하나**다. 탭이 둘이면 같은 종목을
//   두 곳에서 찾게 되고, 열 구성이 갈라져 어느 쪽이 최신인지 모르게 된다.
//
// ★ 기본은 '가속 중(통과)'이다. 이 시스템은 발굴 도구이고 탈락 767종목이
//   먼저 보이면 눈이 갈 곳을 잃는다. 탈락은 "왜 안 걸렸나"를 볼 때만 켠다.
import { useMemo, useState } from "react";
import Link from "next/link";
import { GRADE_COLOR, type Grade } from "@/lib/types";
import { HORIZONS, horizonLabel } from "@/lib/outcome";

export interface DiscoveryRow {
  code: string;
  name: string;
  board: string | null;
  sector: string | null;
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
  /** 최근 5거래일 상승률(%). */
  ret5d: number | null;
  /** 발표일 기준 초과수익(%p). 키는 Horizon. */
  excess: Partial<Record<(typeof HORIZONS)[number], number | null>>;
}

type GateFilter = "passed" | "failed" | "undecided" | "all";
type CapFilter = "all" | "large" | "mid" | "small";

const GATE_LABEL: Record<GateFilter, string> = {
  passed: "가속 중 (통과)",
  failed: "탈락",
  undecided: "판정 불가",
  all: "전 종목",
};

const CAP_BOUNDS: Record<Exclude<CapFilter, "all">, [number, number]> = {
  large: [1e12, Infinity],
  mid: [3e11, 1e12],
  small: [0, 3e11],
};
const CAP_LABEL: Record<CapFilter, string> = {
  all: "시총 전체",
  large: "1조 이상",
  mid: "3천억~1조",
  small: "3천억 미만",
};

const GRADE_ORDER: Grade[] = ["★", "○", "△", "·", "✕"];
const GRADE_RANK = new Map<Grade, number>(GRADE_ORDER.map((g, i) => [g, i]));
function gradeRank(grade: Grade | null): number {
  return grade == null ? GRADE_ORDER.length : (GRADE_RANK.get(grade) ?? GRADE_ORDER.length);
}

function fmtCap(v: number | null): string {
  if (v == null) return "—";
  return v >= 1e12 ? `${(v / 1e12).toFixed(1)}조` : `${Math.round(v / 1e8).toLocaleString("ko-KR")}억`;
}
function fmtNum(v: number | null, digits = 1): string {
  return v == null ? "—" : v.toFixed(digits);
}
function fmtPct(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}
/** 수익률 색 — 표에서 눈이 먼저 가야 하는 열이다. */
function tone(v: number | null | undefined): string {
  if (v == null) return "text-slate-300";
  if (v > 0) return "text-rose-300 font-semibold";
  if (v < 0) return "text-sky-300";
  return "text-slate-100";
}

/** 표시 상한. 넘으면 **잘랐다는 사실을 화면에 밝힌다** — 조용히 truncate 금지. */
const MAX_ROWS = 400;

export default function DiscoveryTable({ rows }: { rows: DiscoveryRow[] }) {
  const [query, setQuery] = useState("");
  const [gate, setGate] = useState<GateFilter>("passed");
  const [grade, setGrade] = useState<Grade | "all">("all");
  const [sector, setSector] = useState("all");
  const [cap, setCap] = useState<CapFilter>("all");
  const [consensus, setConsensus] = useState<"all" | "yes" | "no">("all");
  const [quarter, setQuarter] = useState("all");

  const sectors = useMemo(
    () =>
      [...new Set(rows.map((r) => r.sector ?? r.industry).filter((v): v is string => !!v))].sort(
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
        if (sector !== "all" && (r.sector ?? r.industry) !== sector) return false;
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
      // 등급 높은 순 → 같은 등급 안에서는 스코어 높은 순.
      .sort((a, b) => {
        const byGrade = gradeRank(a.grade) - gradeRank(b.grade);
        if (byGrade !== 0) return byGrade;
        return (b.score ?? -1) - (a.score ?? -1);
      });
  }, [rows, query, gate, grade, sector, cap, consensus, quarter]);

  const shown = filtered.slice(0, MAX_ROWS);
  const select =
    "rounded border border-slate-600 bg-slate-900 px-2 py-1 text-sm text-slate-100";
  // 탈락·판정불가를 볼 때는 스코어/반영도가 비어 있어 추적 열이 의미 없다.
  const showTracking = gate === "passed" || gate === "all";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="종목명 또는 코드"
          className={`${select} w-44 placeholder:text-slate-300`}
          aria-label="종목 검색"
        />
        <select value={gate} onChange={(e) => setGate(e.target.value as GateFilter)}
                className={select} aria-label="게이트">
          {(Object.keys(GATE_LABEL) as GateFilter[]).map((k) => (
            <option key={k} value={k}>{GATE_LABEL[k]}</option>
          ))}
        </select>
        <select value={grade} onChange={(e) => setGrade(e.target.value as Grade | "all")}
                className={select} aria-label="등급">
          <option value="all">등급 전체</option>
          {GRADE_ORDER.map((g) => <option key={g} value={g}>{g}</option>)}
        </select>
        <select value={sector} onChange={(e) => setSector(e.target.value)}
                className={`${select} max-w-[13rem]`} aria-label="섹터">
          <option value="all">섹터 전체 ({sectors.length})</option>
          {sectors.map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
        <select value={cap} onChange={(e) => setCap(e.target.value as CapFilter)}
                className={select} aria-label="시가총액">
          {(Object.keys(CAP_LABEL) as CapFilter[]).map((k) => (
            <option key={k} value={k}>{CAP_LABEL[k]}</option>
          ))}
        </select>
        <select value={consensus} onChange={(e) => setConsensus(e.target.value as "all" | "yes" | "no")}
                className={select} aria-label="컨센서스">
          <option value="all">컨센 전체</option>
          <option value="yes">컨센 있음</option>
          <option value="no">컨센 없음</option>
        </select>
        <select value={quarter} onChange={(e) => setQuarter(e.target.value)}
                className={select} aria-label="분기">
          <option value="all">분기 전체</option>
          {quarters.map((q) => <option key={q} value={q}>{q}</option>)}
        </select>
      </div>

      <p className="text-sm text-slate-100">
        <strong className="text-white">{filtered.length.toLocaleString("ko-KR")}종목</strong>
        <span className="text-slate-300"> / 전체 {rows.length.toLocaleString("ko-KR")}</span>
      </p>

      {/* ★ 높이를 제한해야 머리글 sticky가 먹는다(T64). */}
      <div className="max-h-[70vh] overflow-auto rounded-lg border border-slate-700">
        <table className="w-full min-w-[1180px] text-sm">
          <thead className="sticky top-0 z-20 bg-slate-900 text-xs uppercase text-slate-200 shadow-[0_1px_0_0_rgba(148,163,184,0.45)]">
            <tr>
              <th scope="col" className="px-3 py-2 text-left font-medium">섹터</th>
              <th scope="col" className="px-3 py-2 text-left font-medium">종목명</th>
              <th scope="col" className="px-3 py-2 text-center font-medium">등급</th>
              <th scope="col" className="px-3 py-2 text-left font-medium">분기</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">스코어</th>
              <th scope="col" className="px-3 py-2 text-right font-medium"
                  title="주가가 이 실적을 이미 아는 정도 — 낮을수록 아직 안 올랐다">
                반영도
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">시총</th>
              <th scope="col" className="px-3 py-2 text-right font-medium"
                  title="최근 5거래일 주가 상승률">
                최근 5일
              </th>
              {showTracking
                ? HORIZONS.map((d) => (
                    <th key={d} scope="col"
                        className="bg-slate-800/80 px-3 py-2 text-right font-medium text-indigo-200"
                        title={`실적 발표일 기준 ${horizonLabel(d)} 지수 대비 초과수익(영업일)`}>
                      {d < 0 ? `전 ${Math.abs(d)}일` : d === 0 ? "당일" : `후 ${d}일`}
                    </th>
                  ))
                : <th scope="col" className="px-3 py-2 text-left font-medium">탈락 사유</th>}
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.code} className="border-t border-slate-800 hover:bg-slate-900/60">
                <td className="whitespace-nowrap px-3 py-2 text-slate-200"
                    title={r.industry ?? undefined}>
                  {r.sector ?? r.industry ?? "—"}
                </td>
                <td className="whitespace-nowrap px-3 py-2">
                  <Link href={`/stock/${r.code}`} className="font-medium text-sky-300 hover:underline">
                    {r.name}
                  </Link>
                  <span className="ml-2 text-xs text-slate-300">{r.code}</span>
                </td>
                <td className="px-3 py-2 text-center">
                  {r.grade ? (
                    <span className="text-base font-bold" style={{ color: GRADE_COLOR[r.grade] }}>
                      {r.grade}
                    </span>
                  ) : (
                    <span className="text-slate-300">—</span>
                  )}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-slate-200">{r.quarter}</td>
                <td className="px-3 py-2 text-right font-semibold tabular-nums text-white">
                  {fmtNum(r.score)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-slate-100">{fmtNum(r.pri)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-slate-200">{fmtCap(r.marketCap)}</td>
                <td className={`px-3 py-2 text-right tabular-nums ${tone(r.ret5d)}`}>
                  {fmtPct(r.ret5d)}
                </td>
                {showTracking
                  ? HORIZONS.map((d) => (
                      <td key={d}
                          className={`bg-slate-900/50 px-3 py-2 text-right tabular-nums ${tone(r.excess[d])}`}>
                        {fmtPct(r.excess[d])}
                      </td>
                    ))
                  : (
                    <td className="px-3 py-2 text-xs text-slate-200">
                      {r.gatePassed === false
                        ? r.failReasons.join(" · ") || "탈락"
                        : "판정 불가 (데이터 부족)"}
                    </td>
                  )}
              </tr>
            ))}
            {shown.length === 0 && (
              <tr>
                <td colSpan={9 + (showTracking ? HORIZONS.length - 1 : 0)}
                    className="px-3 py-8 text-center text-slate-200">
                  조건에 맞는 종목이 없다.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {filtered.length > MAX_ROWS && (
        <p className="text-sm text-amber-200">
          ⚠ 상위 {MAX_ROWS}종목만 표시했다 (등급·스코어 순) — 조건에{" "}
          {filtered.length.toLocaleString("ko-KR")}종목이 걸렸다. 필터를 좁혀라.
        </p>
      )}
    </div>
  );
}
