"use client";
// PRD Ref: §9 — 발굴 목록 + 스크리너 **한 화면**
//
// ★ 두 화면을 합친 이유: 보던 것이 같았다. 다른 건 "게이트 통과분만 보나,
//   탈락까지 보나"뿐인데 그건 **필터 하나**다. 탭이 둘이면 같은 종목을
//   두 곳에서 찾게 되고, 열 구성이 갈라져 어느 쪽이 최신인지 모르게 된다.
//
// ★ 기본은 '가속 중(통과)'이다. 이 시스템은 발굴 도구이고 탈락 종목이
//   먼저 보이면 눈이 갈 곳을 잃는다. 탈락은 "왜 안 걸렸나"를 볼 때만 켠다.
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import MultiSelect from "@/components/MultiSelect";
import { GRADE_COLOR, GRADE_MEANING, type Grade } from "@/lib/types";
import { HORIZONS, horizonLabel } from "@/lib/outcome";
import {
  DEFAULT_FILTERS,
  fromQuery,
  loadStored,
  saveStored,
  toQuery,
  type CapFilter,
  type ConsensusFilter,
  type DiscoveryFilters,
  type GateFilter,
} from "@/lib/discoveryFilters";

export interface DiscoveryRow {
  code: string;
  name: string;
  board: string | null;
  sector: string;
  industry: string | null;
  marketCap: number | null;
  quarter: string;
  /** 정렬 1순위. `연*4 + (분기−1)` — 문자열로 비교하면 연도 경계에서 조용히 틀린다. */
  quarterIndex: number;
  gatePassed: boolean | null;
  grade: Grade | null;
  score: number | null;
  pri: number | null;
  hasConsensus: boolean | null;
  baseEffect: boolean | null;
  failReasons: string[];
  /** 평가 분기의 매출 성장률(%). */
  revenueYoy: number | null;
  /** 평가 분기의 영업이익 성장률(%). 정렬 3순위이자 이 표의 주인공이다. */
  opYoy: number | null;
  /** 부호 전환 라벨('흑전'·'적전'…). opYoy가 null일 때 대신 보여준다(T25). */
  opStatusLabel: string | null;
  /** 영업이익률 YoY 변화(%p) — G4가 보는 값이다. */
  opmYoyDelta: number | null;
  /** 최근 5거래일 상승률(%). */
  ret5d: number | null;
  /** 발표일 기준 초과수익(%p). 키는 Horizon. */
  excess: Partial<Record<(typeof HORIZONS)[number], number | null>>;
}

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
/**
 * 성장률 칸. 부호가 바뀌는 구간은 **%가 아니라 라벨**이다(T25) —
 * 여기서 0%로 채우면 흑자전환이 '성장 없음'으로 보인다.
 */
function growthCell(value: number | null, label: string | null): string {
  if (value != null) return fmtPct(value);
  return label ?? "—";
}

/** 표시 상한. 넘으면 **잘랐다는 사실을 화면에 밝힌다** — 조용히 truncate 금지. */
const MAX_ROWS = 400;

export default function DiscoveryTable({ rows }: { rows: DiscoveryRow[] }) {
  // ★ 첫 렌더는 **반드시 기본값**이어야 한다. sessionStorage를 렌더 중에 읽으면
  //   서버가 그린 HTML과 달라져 하이드레이션이 깨진다(화면이 통째로 다시 그려진다).
  //   복원은 마운트 후 effect에서 한다.
  const [filters, setFilters] = useState<DiscoveryFilters>(DEFAULT_FILTERS);
  // ★★ **ref가 아니라 state여야 한다.** ref로 두면 복원 effect가 `true`로 바꾼 값을
  //   같은 커밋의 저장 effect가 곧바로 읽어, 아직 **기본값인** filters를 저장해
  //   방금 복원한 값을 덮어쓴다. 실측: 결과 추적 탭에 갔다 돌아오면 필터가 초기화됐다.
  //   개발 모드의 StrictMode 이중 실행이 이걸 한 번 더 확실히 깨뜨린다
  //   (지워진 저장소를 두 번째 실행이 다시 읽어 기본값을 확정한다).
  //   state면 저장 effect가 **복원된 filters와 같은 렌더**에서만 켜지므로 순서가 보장된다.
  const [restored, setRestored] = useState(false);

  // ── 복원: URL > 저장된 상태 > 기본값 ─────────────────────────
  // ★ URL이 이긴다. 결과 추적에서 `?sectors=반도체`로 들어왔는데 저장된 옛 필터가
  //   덮어쓰면 **링크가 조용히 무시된다** — 누른 사람은 그 섹터를 봤다고 믿는다.
  useEffect(() => {
    const { filters: fromUrl, hadAny } = fromQuery(window.location.search);
    setFilters(hadAny ? fromUrl : loadStored() ?? DEFAULT_FILTERS);
    setRestored(true);
  }, []);

  // ── 저장 + 주소 반영 ──────────────────────────────────────────
  // ★ `history.replaceState`를 쓴다. Next의 router.replace를 쓰면 서버 컴포넌트가
  //   다시 돌아 전 종목을 재조회한다 — 체크박스 하나에 왕복이 붙는다.
  useEffect(() => {
    if (!restored) return;
    saveStored(filters);
    const q = toQuery(filters);
    const url = q ? `${window.location.pathname}?${q}` : window.location.pathname;
    window.history.replaceState(null, "", url);
  }, [filters, restored]);

  function patch(next: Partial<DiscoveryFilters>) {
    setFilters((f) => ({ ...f, ...next }));
  }

  const { query, gate, grades, sectors, cap, consensus, quarter } = filters;

  const sectorOptions = useMemo(() => {
    const counts = new Map<string, number>();
    for (const r of rows) counts.set(r.sector, (counts.get(r.sector) ?? 0) + 1);
    return [...counts.entries()]
      .sort((a, b) => a[0].localeCompare(b[0], "ko"))
      .map(([value, n]) => ({ value, hint: String(n) }));
  }, [rows]);

  const gradeOptions = useMemo(() => {
    const counts = new Map<string, number>();
    for (const r of rows) if (r.grade) counts.set(r.grade, (counts.get(r.grade) ?? 0) + 1);
    return GRADE_ORDER.map((g) => ({
      value: g,
      label: `${g}  ${GRADE_MEANING[g]}`,
      hint: String(counts.get(g) ?? 0),
      color: GRADE_COLOR[g],
    }));
  }, [rows]);

  const quarters = useMemo(
    () => [...new Set(rows.map((r) => r.quarter))].sort().reverse(),
    [rows]
  );

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    // ★ 복수 선택은 Set으로 본다. 배열 includes를 행마다 돌리면 1,100행 × 30섹터다.
    const gradeSet = new Set<string>(grades);
    const sectorSet = new Set<string>(sectors);
    return rows
      .filter((r) => {
        if (needle && !r.name.toLowerCase().includes(needle) && !r.code.includes(needle))
          return false;
        if (gate === "passed" && r.gatePassed !== true) return false;
        if (gate === "failed" && r.gatePassed !== false) return false;
        if (gate === "undecided" && r.gatePassed != null) return false;
        // 빈 선택 = 전체다. 아무것도 안 고른 상태를 "아무것도 안 보임"으로 읽으면 안 된다.
        if (gradeSet.size > 0 && (r.grade == null || !gradeSet.has(r.grade))) return false;
        if (sectorSet.size > 0 && !sectorSet.has(r.sector)) return false;
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
      // ★★ 정렬은 **필터와 무관하게 항상 같다**(사용자 지정 2026-08-22):
      //    ① 최신 분기 ② 스코어 높은 순 ③ 영업이익 증가율 높은 순 ④ 시총 큰 순
      //    등급으로 먼저 묶지 않는다 — 등급은 스코어×반영도의 파생값이라
      //    등급을 1순위로 두면 "스코어가 더 높은데 아래에 있는" 줄이 생긴다.
      //    결측은 항상 맨 뒤로 보낸다(−Infinity). 0으로 채우면 미측정이 '0%'로 섞인다.
      .sort((a, b) =>
        (b.quarterIndex - a.quarterIndex) ||
        ((b.score ?? -Infinity) - (a.score ?? -Infinity)) ||
        ((b.opYoy ?? -Infinity) - (a.opYoy ?? -Infinity)) ||
        ((b.marketCap ?? -Infinity) - (a.marketCap ?? -Infinity))
      );
  }, [rows, query, gate, grades, sectors, cap, consensus, quarter]);

  const shown = filtered.slice(0, MAX_ROWS);
  const select =
    "rounded border border-slate-600 bg-slate-900 px-2 py-1 text-sm text-slate-100";
  // 탈락·판정불가를 볼 때는 스코어/반영도가 비어 있어 추적 열이 의미 없다.
  const showTracking = gate === "passed" || gate === "all";
  const active =
    query.trim() !== "" || gate !== DEFAULT_FILTERS.gate || grades.length > 0 ||
    sectors.length > 0 || cap !== "all" || consensus !== "all" || quarter !== "all";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={query}
          onChange={(e) => patch({ query: e.target.value })}
          placeholder="종목명 또는 코드"
          className={`${select} w-44 placeholder:text-slate-300`}
          aria-label="종목 검색"
        />
        <select value={gate} onChange={(e) => patch({ gate: e.target.value as GateFilter })}
                className={select} aria-label="게이트">
          {(Object.keys(GATE_LABEL) as GateFilter[]).map((k) => (
            <option key={k} value={k}>{GATE_LABEL[k]}</option>
          ))}
        </select>
        {/* ★ 등급·섹터는 복수 선택이다(사용자 요청). 빈 선택 = 전체. */}
        <MultiSelect
          label="등급"
          options={gradeOptions}
          selected={grades}
          onChange={(next) => patch({ grades: next as Grade[] })}
          widthClass="w-40"
        />
        <MultiSelect
          label="섹터"
          options={sectorOptions}
          selected={sectors}
          onChange={(next) => patch({ sectors: next })}
          widthClass="w-52"
        />
        <select value={cap} onChange={(e) => patch({ cap: e.target.value as CapFilter })}
                className={select} aria-label="시가총액">
          {(Object.keys(CAP_LABEL) as CapFilter[]).map((k) => (
            <option key={k} value={k}>{CAP_LABEL[k]}</option>
          ))}
        </select>
        <select value={consensus}
                onChange={(e) => patch({ consensus: e.target.value as ConsensusFilter })}
                className={select} aria-label="컨센서스">
          <option value="all">컨센 전체</option>
          <option value="yes">컨센 있음</option>
          <option value="no">컨센 없음</option>
        </select>
        <select value={quarter} onChange={(e) => patch({ quarter: e.target.value })}
                className={select} aria-label="분기">
          <option value="all">분기 전체</option>
          {quarters.map((q) => <option key={q} value={q}>{q}</option>)}
        </select>
        {active && (
          <button
            type="button"
            onClick={() => setFilters(DEFAULT_FILTERS)}
            className="rounded border border-slate-600 px-2 py-1 text-sm text-slate-200 hover:bg-slate-800"
          >
            필터 초기화
          </button>
        )}
      </div>

      <p className="text-sm text-slate-100">
        <strong className="text-white">{filtered.length.toLocaleString("ko-KR")}종목</strong>
        <span className="text-slate-300"> / 전체 {rows.length.toLocaleString("ko-KR")}</span>
        <span className="ml-2 text-xs text-slate-300">
          정렬: 최신 분기 → 스코어 → 영업이익 YoY → 시총
        </span>
      </p>

      {/* ★ 높이를 제한해야 머리글 sticky가 먹는다(T64). */}
      <div className="max-h-[70vh] overflow-auto rounded-lg border border-slate-700">
        <table className="w-full min-w-[1360px] text-sm">
          <thead className="sticky top-0 z-20 bg-slate-900 text-xs uppercase text-slate-200 shadow-[0_1px_0_0_rgba(148,163,184,0.45)]">
            <tr>
              <th scope="col" className="px-3 py-2 text-left font-medium">섹터</th>
              <th scope="col" className="px-3 py-2 text-left font-medium">종목명</th>
              <th scope="col" className="px-3 py-2 text-center font-medium">등급</th>
              <th scope="col" className="px-3 py-2 text-left font-medium">분기</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">스코어</th>
              {/* ★ 사용자 요청(2026-08-22): 게이트가 보는 성장률을 표에 직접 싣는다.
                  스코어만 있으면 "왜 이 점수인가"를 상세 화면에 들어가야 안다. */}
              <th scope="col" className="px-3 py-2 text-right font-medium"
                  title="평가 분기의 매출 성장률(전년 동기 대비) — G1이 보는 값">
                매출 YoY
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium text-amber-200"
                  title="평가 분기의 영업이익 성장률(전년 동기 대비) — G2가 보는 값이자 정렬 기준">
                영업익 YoY
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium"
                  title="영업이익률의 전년 동기 대비 변화(%p) — G4가 보는 값">
                OPM YoY
              </th>
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
                  {r.sector}
                </td>
                {/* ★ 종목코드는 표시하지 않는다(사용자 요청). 검색은 코드로도 된다. */}
                <td className="whitespace-nowrap px-3 py-2">
                  <Link href={`/stock/${r.code}`} className="font-medium text-sky-300 hover:underline">
                    {r.name}
                  </Link>
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
                <td className={`px-3 py-2 text-right tabular-nums ${tone(r.revenueYoy)}`}>
                  {fmtPct(r.revenueYoy)}
                </td>
                <td className={`whitespace-nowrap px-3 py-2 text-right tabular-nums ${tone(r.opYoy)}`}>
                  {growthCell(r.opYoy, r.opStatusLabel)}
                </td>
                <td className={`px-3 py-2 text-right tabular-nums ${tone(r.opmYoyDelta)}`}>
                  {r.opmYoyDelta == null
                    ? "—"
                    : `${r.opmYoyDelta >= 0 ? "+" : ""}${r.opmYoyDelta.toFixed(1)}%p`}
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
                <td colSpan={12 + (showTracking ? HORIZONS.length - 1 : 0)}
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
          ⚠ 상위 {MAX_ROWS}종목만 표시했다 (최신 분기 · 스코어 순) — 조건에{" "}
          {filtered.length.toLocaleString("ko-KR")}종목이 걸렸다. 필터를 좁혀라.
        </p>
      )}
    </div>
  );
}
