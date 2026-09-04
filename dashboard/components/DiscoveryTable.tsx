"use client";
// PRD Ref: §9 — 발굴 목록 + 관심 종목
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
  type SortDir,
  type SortKey,
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
  turnaround: boolean | null;
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

/** 정렬 상태를 글로 알릴 때 쓰는 이름. 머리글 라벨과 **같은 말**이어야 한다. */
const SORT_LABEL: Partial<Record<SortKey, string>> = {
  score: "스코어",
  revenueYoy: "매출 YoY",
  opYoy: "영업익 YoY",
  opmYoyDelta: "OPM YoY",
  pri: "주가 반영도",
  marketCap: "시총",
  ret5d: "최근 5일",
  ...Object.fromEntries(
    HORIZONS.map((d) => [
      `d${d}`,
      d < 0 ? `전 ${Math.abs(d)}일` : d === 0 ? "당일" : `후 ${d}일`,
    ])
  ),
};

/** 기본 정렬 — 최신 분기 → 스코어 → 영업익 YoY → 시총. 결측은 맨 뒤. */
function byDefault(a: DiscoveryRow, b: DiscoveryRow): number {
  return (
    (b.quarterIndex - a.quarterIndex) ||
    ((b.score ?? -Infinity) - (a.score ?? -Infinity)) ||
    ((b.opYoy ?? -Infinity) - (a.opYoy ?? -Infinity)) ||
    ((b.marketCap ?? -Infinity) - (a.marketCap ?? -Infinity))
  );
}

/**
 * 정렬 키 → 그 행의 값. **없으면 `null`이지 0이 아니다.**
 *
 * ★ 0으로 바꾸면 미측정 종목이 '0%'인 것처럼 다른 종목 사이에 끼어 앉는다.
 *   이 프로젝트는 결측과 0을 반드시 구분한다(`False`와 `None`을 가르는 것과 같은 규칙).
 */
function sortValue(r: DiscoveryRow, key: SortKey): number | null {
  switch (key) {
    case "score": return r.score;
    case "revenueYoy": return r.revenueYoy;
    case "opYoy": return r.opYoy;
    case "opmYoyDelta": return r.opmYoyDelta;
    case "pri": return r.pri;
    case "marketCap": return r.marketCap;
    case "ret5d": return r.ret5d;
    default: {
      // `d-5`·`d0`·`d5`… — 실적 발표일 기준 초과수익
      const day = Number(key.slice(1));
      if (!Number.isFinite(day)) return null;
      return r.excess[day as (typeof HORIZONS)[number]] ?? null;
    }
  }
}

/**
 * 정렬 가능한 머리글 한 칸.
 *
 * ★ `<button>`이어야 한다. `<th onClick>`은 키보드로 닿지 않고 스크린리더가
 *   누를 수 있는 것으로 읽지 않는다. 다중 정렬에서는 1순위 열에만
 *   `aria-sort`를 붙이고 나머지 우선순위는 버튼의 읽기 이름으로 알린다.
 */
function SortableTh({
  label, sortKey, priority, dir, onSort, title, className = "", tone = "",
}: {
  label: string;
  sortKey: SortKey;
  priority: number | null;
  dir: SortDir | null;
  onSort: (k: SortKey) => void;
  title?: string;
  className?: string;
  tone?: string;
}) {
  const active = priority != null && dir != null;
  const state = !active ? "원본" : dir === "desc" ? "내림" : "오름";
  return (
    <th
      scope="col"
      aria-sort={priority === 1 ? (dir === "desc" ? "descending" : "ascending") : undefined}
      className={`border-l border-slate-700/70 px-3 py-2.5 text-right font-semibold ${tone} ${className}`}
      title={title}
    >
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className="inline-flex w-full items-center justify-end gap-1.5 whitespace-nowrap hover:text-white"
        // ★ 지금 상태와 **다음에 무슨 일이 일어나는지**를 함께 읽어 준다.
        aria-label={`${label} 기준 정렬 (${state}${active ? `, ${priority}순위` : ""})`}
      >
        <span>{label}</span>
        {active && (
          <span className="rounded-full bg-sky-400/20 px-1.5 py-0.5 text-[10px] text-sky-200" aria-hidden="true">
            {priority}
          </span>
        )}
        <span className={`rounded px-1 py-0.5 text-[10px] ${active ? "bg-sky-400/15 text-sky-200" : "bg-slate-800 text-slate-400"}`} aria-hidden="true">
          {state}
        </span>
      </button>
    </th>
  );
}

const GATE_LABEL: Record<GateFilter, string> = {
  passed: "가속 중 (통과) + 턴어라운드",
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
const FAVORITES_KEY = "heimdallr.favorite_codes.v1";

function loadFavorites(): string[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(FAVORITES_KEY) ?? "[]");
    return Array.isArray(parsed)
      ? parsed.filter(
          (code): code is string => typeof code === "string" && /^[0-9A-Z]{6}$/.test(code)
        )
      : [];
  } catch {
    return [];
  }
}

export default function DiscoveryTable({
  rows,
  favoriteOnly = false,
}: {
  rows: DiscoveryRow[];
  favoriteOnly?: boolean;
}) {
  // ★ 첫 렌더는 **반드시 기본값**이어야 한다. sessionStorage를 렌더 중에 읽으면
  //   서버가 그린 HTML과 달라져 하이드레이션이 깨진다(화면이 통째로 다시 그려진다).
  //   복원은 마운트 후 effect에서 한다.
  const [filters, setFilters] = useState<DiscoveryFilters>(DEFAULT_FILTERS);
  const [favorites, setFavorites] = useState<string[]>([]);
  const [favoritesRestored, setFavoritesRestored] = useState(false);
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
    setFilters(
      hadAny
        ? fromUrl
        : favoriteOnly
          ? { ...DEFAULT_FILTERS, gate: "all" }
          : loadStored() ?? DEFAULT_FILTERS
    );
    setRestored(true);
    setFavorites(loadFavorites());
    setFavoritesRestored(true);
  }, [favoriteOnly]);

  // ── 저장 + 주소 반영 ──────────────────────────────────────────
  // ★ `history.replaceState`를 쓴다. Next의 router.replace를 쓰면 서버 컴포넌트가
  //   다시 돌아 전 종목을 재조회한다 — 체크박스 하나에 왕복이 붙는다.
  useEffect(() => {
    if (!restored) return;
    if (!favoriteOnly) saveStored(filters);
    const q = toQuery(filters);
    const url = q ? `${window.location.pathname}?${q}` : window.location.pathname;
    window.history.replaceState(null, "", url);
  }, [favoriteOnly, filters, restored]);

  function toggleFavorite(code: string) {
    setFavorites((current) => {
      const next = current.includes(code)
        ? current.filter((item) => item !== code)
        : [...current, code];
      window.localStorage.setItem(FAVORITES_KEY, JSON.stringify(next));
      return next;
    });
  }

  function patch(next: Partial<DiscoveryFilters>) {
    setFilters((f) => ({ ...f, ...next }));
  }

  const { query, gate, grades, sectors, cap, consensus, quarter, sorts } = filters;

  /**
   * 머리글 클릭. 선택한 순서가 1·2·3차 정렬 순서다. 같은 열은
   * 원본 → 내림 → 오름 → 원본으로 순환한다.
   *
   * ★ 새 열을 처음 누르면 **내림차순**이다. 이 표에서 궁금한 것은 거의 언제나
   *   "가장 높은 종목"이므로, 오름차순으로 시작하면 매번 두 번씩 눌러야 한다.
   */
  function toggleSort(key: SortKey) {
    if (key === "default") return patch({ sorts: [] });
    const index = sorts.findIndex((rule) => rule.key === key);
    if (index < 0) return patch({ sorts: [...sorts, { key, dir: "desc" }] });
    if (sorts[index].dir === "desc") {
      return patch({ sorts: sorts.map((rule, i) => i === index ? { ...rule, dir: "asc" } : rule) });
    }
    return patch({ sorts: sorts.filter((_, i) => i !== index) });
  }

  function sortState(key: SortKey): { priority: number | null; dir: SortDir | null } {
    const index = sorts.findIndex((rule) => rule.key === key);
    return index < 0 ? { priority: null, dir: null } : { priority: index + 1, dir: sorts[index].dir };
  }

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
    const favoriteSet = new Set(favorites);
    return rows
      .filter((r) => {
        if (favoriteOnly && !favoriteSet.has(r.code)) return false;
        if (needle && !r.name.toLowerCase().includes(needle) && !r.code.includes(needle))
          return false;
        // 턴어라운드는 게이트 탈락이어도 '가속 중(통과)'와 같은 선택에서 함께 본다.
        if (gate === "passed" && r.gatePassed !== true && r.turnaround !== true) return false;
        // 선택지는 서로 겹치지 않는다. 턴어라운드는 위 통합 선택으로 옮겼다.
        if (gate === "failed" && (r.gatePassed !== false || r.turnaround === true)) return false;
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
      // ★★ 기본 정렬은 **필터와 무관하게 항상 같다**(사용자 지정 2026-08-22):
      //    ① 최신 분기 ② 스코어 높은 순 ③ 영업이익 증가율 높은 순 ④ 시총 큰 순
      //    등급으로 먼저 묶지 않는다 — 등급은 스코어×반영도의 파생값이라
      //    등급을 1순위로 두면 "스코어가 더 높은데 아래에 있는" 줄이 생긴다.
      //    결측은 항상 맨 뒤로 보낸다(−Infinity). 0으로 채우면 미측정이 '0%'로 섞인다.
      .sort((a, b) => {
        for (const rule of sorts) {
          const av = sortValue(a, rule.key);
          const bv = sortValue(b, rule.key);
          // ★★ **결측은 방향과 무관하게 언제나 맨 뒤다**(사용자 지정 2026-08-26).
          //   오름차순에서 부호만 뒤집으면 미측정 종목이 **맨 위로 올라온다** —
          //   "가장 낮은 종목"을 찾으려고 누른 사람에게 **측정조차 안 된 종목**이
          //   1등으로 보인다. 그건 답이 아니라 빈칸이다(T25·결측은 0이 아니다).
          if (av == null && bv == null) continue;
          if (av == null) return 1;
          if (bv == null) return -1;
          const diff = rule.dir === "asc" ? av - bv : bv - av;
          if (diff) return diff;
        }
        return byDefault(a, b);
      });
  }, [rows, favoriteOnly, favorites, query, gate, grades, sectors, cap, consensus, quarter, sorts]);

  const shown = filtered.slice(0, MAX_ROWS);
  const select =
    "rounded border border-slate-600 bg-slate-900 px-2 py-1 text-sm text-slate-100";
  // 탈락·판정불가를 볼 때는 스코어/주가 반영도가 비어 있어 추적 열이 의미 없다.
  const showTracking = gate === "passed" || gate === "all";
  const active =
    query.trim() !== "" || gate !== (favoriteOnly ? "all" : DEFAULT_FILTERS.gate) || grades.length > 0 ||
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
        {!favoriteOnly && (
          <select value={gate} onChange={(e) => patch({ gate: e.target.value as GateFilter })}
                  className={select} aria-label="게이트">
            {(Object.keys(GATE_LABEL) as GateFilter[]).map((k) => (
              <option key={k} value={k}>{GATE_LABEL[k]}</option>
            ))}
          </select>
        )}
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
            onClick={() => setFilters(
              favoriteOnly ? { ...DEFAULT_FILTERS, gate: "all" } : DEFAULT_FILTERS
            )}
            className="rounded border border-slate-600 px-2 py-1 text-sm text-slate-200 hover:bg-slate-800"
          >
            필터 초기화
          </button>
        )}
      </div>

      <p className="text-sm text-slate-100">
        <strong className="text-white">{filtered.length.toLocaleString("ko-KR")}종목</strong>
        <span className="text-slate-300">
          {favoriteOnly
            ? ` / 관심 종목 ${favorites.length.toLocaleString("ko-KR")}`
            : ` / 전체 ${rows.length.toLocaleString("ko-KR")}`}
        </span>
        {/* ★ 화면이 지금 무슨 순서인지 **글로도** 말한다. 화살표만으로는
            스크롤을 내린 뒤 "내가 뭘로 정렬했더라"를 알 수 없다. */}
        <span className="ml-2 text-xs text-slate-300">
          {sorts.length === 0 ? (
            "원본 순서: 최신 분기 → 스코어 → 영업이익 YoY → 시총"
          ) : (
            <>
              다중 정렬: {sorts.map((rule, index) => (
                <span key={rule.key}>
                  {index > 0 && <span className="text-slate-500"> → </span>}
                  <strong className="text-sky-300">{index + 1}. {SORT_LABEL[rule.key] ?? rule.key}</strong>{" "}
                  {rule.dir === "desc" ? "내림차순" : "오름차순"}
                </span>
              ))}
              <span className="text-slate-400"> · 미측정은 맨 뒤</span>
              <button type="button"
                      onClick={() => patch({ sorts: [] })}
                      className="ml-2 underline hover:text-white">
                원본으로
              </button>
            </>
          )}
        </span>
      </p>

      {/* ★ 높이를 제한해야 머리글 sticky가 먹는다(T64). */}
      <div className="max-h-[70vh] overflow-auto rounded-lg border border-slate-700">
        <table className="w-full min-w-[1360px] text-sm">
          <thead className="sticky top-0 z-20 bg-slate-950 text-xs text-slate-100 shadow-[0_1px_0_0_rgba(148,163,184,0.55)]">
            <tr className="border-b border-slate-700 text-[11px] font-bold tracking-[0.14em] text-slate-300">
              <th colSpan={5} className="bg-slate-900 px-3 py-1.5 text-left">종목 정보</th>
              <th colSpan={7} className="border-l border-slate-700 bg-slate-900 px-3 py-1.5 text-center">실적 · 가격</th>
              <th colSpan={showTracking ? HORIZONS.length : 1}
                  className="border-l border-indigo-700/60 bg-indigo-950/70 px-3 py-1.5 text-center text-indigo-100">
                {showTracking ? "분기실적 발표" : "게이트 판정"}
              </th>
            </tr>
            <tr>
              <th scope="col" className="px-3 py-2.5 text-left font-semibold">섹터</th>
              <th scope="col" className="px-3 py-2.5 text-center font-semibold">관심</th>
              <th scope="col" className="px-3 py-2.5 text-left font-semibold">종목명</th>
              <th scope="col" className="px-3 py-2.5 text-center font-semibold">등급</th>
              <th scope="col" className="px-3 py-2.5 text-left font-semibold">분기</th>
              <SortableTh label="스코어" sortKey="score" {...sortState("score")}
                          onSort={toggleSort} />
              {/* ★ 사용자 요청(2026-08-22): 게이트가 보는 성장률을 표에 직접 싣는다.
                  스코어만 있으면 "왜 이 점수인가"를 상세 화면에 들어가야 안다. */}
              <SortableTh label="매출 YoY" sortKey="revenueYoy" {...sortState("revenueYoy")}
                          onSort={toggleSort}
                          title="평가 분기의 매출 성장률(전년 동기 대비) — G1이 보는 값" />
              <SortableTh label="영업익 YoY" sortKey="opYoy" {...sortState("opYoy")}
                          onSort={toggleSort} tone="text-amber-200"
                          title="평가 분기의 영업이익 성장률(전년 동기 대비) — G2가 보는 값이자 기본 정렬 기준" />
              <SortableTh label="OPM YoY" sortKey="opmYoyDelta" {...sortState("opmYoyDelta")}
                          onSort={toggleSort}
                          title="영업이익률의 전년 동기 대비 변화(%p) — G4가 보는 값" />
              <SortableTh label="주가 반영도" sortKey="pri" {...sortState("pri")}
                          onSort={toggleSort}
                          title="주가가 이 실적을 이미 아는 정도 — 낮을수록 아직 안 올랐다" />
              <SortableTh label="시총" sortKey="marketCap" {...sortState("marketCap")}
                          onSort={toggleSort} title="현재 시가총액" />
              <SortableTh label="최근 5일" sortKey="ret5d" {...sortState("ret5d")}
                          onSort={toggleSort}
                          title="최근 5거래일 주가 상승률" />
              {showTracking
                ? HORIZONS.map((d) => (
                    <SortableTh
                      key={d}
                      label={d < 0 ? `전 ${Math.abs(d)}일` : d === 0 ? "당일" : `후 ${d}일`}
                      sortKey={`d${d}` as SortKey}
                      {...sortState(`d${d}` as SortKey)}
                      onSort={toggleSort}
                      tone="text-indigo-200"
                      className="bg-slate-800/80"
                      title={`실적 발표일 기준 ${horizonLabel(d)} 지수 대비 초과수익(영업일)`}
                    />
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
                <td className="px-3 py-2 text-center">
                  <button
                    type="button"
                    onClick={() => toggleFavorite(r.code)}
                    className={favorites.includes(r.code)
                      ? "text-xl leading-none text-amber-300"
                      : "text-xl leading-none text-slate-500 hover:text-amber-200"}
                    aria-label={`${r.name} ${favorites.includes(r.code) ? "관심 종목에서 제거" : "관심 종목으로 추가"}`}
                    title={favorites.includes(r.code) ? "관심 종목에서 제거" : "관심 종목으로 추가"}
                  >
                    {favorites.includes(r.code) ? "★" : "☆"}
                  </button>
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
                  {r.turnaround && (
                    <span className="ml-1 rounded bg-emerald-500/15 px-1 py-0.5 text-[10px] font-semibold text-emerald-300">
                      턴어라운드
                    </span>
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
            {favoritesRestored && shown.length === 0 && (
              <tr>
                <td colSpan={13 + (showTracking ? HORIZONS.length - 1 : 0)}
                    className="px-3 py-8 text-center text-slate-200">
                  {favoriteOnly
                    ? "관심 종목이 없다. 발굴 목록에서 ☆를 눌러 추가해라."
                    : "조건에 맞는 종목이 없다."}
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
