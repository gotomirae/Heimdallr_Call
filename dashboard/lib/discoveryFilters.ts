// PRD Ref: §9 — 발굴 목록의 필터 상태
//
// ★★ **이 모듈이 있는 이유(사용자 요청 2026-08-22):**
//   ① 다른 탭을 보다 돌아오면 **직전에 보던 그대로**여야 한다.
//   ② 결과 추적의 섹터를 누르면 발굴 목록에서 **그 섹터만** 보여야 한다.
//
//   둘은 같은 문제다 — "이 화면의 상태를 어떻게 바깥에서 지정하고 되살리는가".
//   그래서 상태를 **한 곳에서** 직렬화한다. 두 기능이 각자 상태를 들고 있으면
//   섹터 링크로 들어온 뒤 탭을 옮겼다 오면 저장된 옛 필터가 링크를 덮어쓴다.
//
// ★ 우선순위는 **URL > 저장된 상태 > 기본값**이다. 링크로 들어온 의도가 항상 이긴다.

import type { Grade } from "./types";

export type GateFilter = "passed" | "failed" | "undecided" | "all";
export type CapFilter = "all" | "large" | "mid" | "small";
export type ConsensusFilter = "all" | "yes" | "no";

/**
 * 사용자가 머리글을 눌러 정렬할 수 있는 열.
 *
 * ★ `"default"`는 **"아무것도 안 눌렀다"**는 뜻이지 특정 열이 아니다.
 *   기본 정렬(최신 분기 → 스코어 → 영업익 YoY → 시총)은 여러 열을 순서대로 보므로
 *   단일 열로 표현할 수 없다. 눌러서 되돌아올 자리를 남기려면 별도 값이어야 한다.
 * ★ `d-5`/`d0`/`d5`…는 실적 발표일 기준 초과수익(`HORIZONS`)이다.
 */
export type SortKey =
  | "default"
  | "score"
  | "revenueYoy"
  | "opYoy"
  | "opmYoyDelta"
  | "pri"
  | "marketCap"
  | "ret5d"
  | `d${number}`;

export type SortDir = "asc" | "desc";
export interface SortRule {
  key: Exclude<SortKey, "default">;
  dir: SortDir;
}

/** 발굴 목록의 화면 상태 전부. 여기 없는 값은 저장되지도 복원되지도 않는다. */
export interface DiscoveryFilters {
  query: string;
  gate: GateFilter;
  /** 복수 선택. **빈 배열 = 전체**다(사용자 요청). */
  grades: Grade[];
  /** 복수 선택. 빈 배열 = 전체. */
  sectors: string[];
  cap: CapFilter;
  consensus: ConsensusFilter;
  quarter: string;
  /** 머리글을 누른 순서대로 적용하는 다중 정렬. 빈 배열이면 원본(기본) 순서다. */
  sorts: SortRule[];
}

export const DEFAULT_FILTERS: DiscoveryFilters = {
  query: "",
  gate: "passed",
  grades: [],
  sectors: [],
  cap: "all",
  consensus: "all",
  quarter: "all",
  sorts: [],
};

/** 정렬 가능한 열인지. **모르는 값은 받지 않는다** — URL로 아무 문자열이나 올 수 있다. */
export function isSortKey(value: string | null): value is SortKey {
  if (!value) return false;
  if (["default", "score", "revenueYoy", "opYoy", "opmYoyDelta", "pri", "marketCap", "ret5d"].includes(value)) {
    return true;
  }
  return /^d-?\d+$/.test(value);
}

function isActiveSortKey(value: string | null): value is Exclude<SortKey, "default"> {
  return isSortKey(value) && value !== "default";
}

/** sessionStorage 키. **session**인 것이 중요하다 — 탭을 닫으면 초기화되는 게 맞다. */
export const STORAGE_KEY = "heimdallr.discovery.filters.v2";

const GATES: GateFilter[] = ["passed", "failed", "undecided", "all"];
const CAPS: CapFilter[] = ["all", "large", "mid", "small"];
const CONSENSUS: ConsensusFilter[] = ["all", "yes", "no"];
const GRADES: Grade[] = ["★", "○", "△", "·", "✕"];

function oneOf<T extends string>(value: string | null, allowed: T[]): T | null {
  return value != null && (allowed as string[]).includes(value) ? (value as T) : null;
}

/** `,`로 이어 붙인 복수 선택을 되돌린다. 모르는 값은 **버린다**(빈 목록으로 만들지 않는다). */
function splitList(value: string | null): string[] {
  if (!value) return [];
  return [...new Set(value.split(",").map((v) => v.trim()).filter(Boolean))];
}

/**
 * URL 쿼리에서 상태를 읽는다. **지정된 키만** 덮어쓴다 —
 * `?sector=반도체` 하나만 와도 나머지는 기본값이 아니라 호출자가 준 base가 유지된다.
 */
export function fromQuery(
  search: string,
  base: DiscoveryFilters = DEFAULT_FILTERS
): { filters: DiscoveryFilters; hadAny: boolean } {
  const p = new URLSearchParams(search);
  const next: DiscoveryFilters = { ...base, grades: [...base.grades], sectors: [...base.sectors] };
  let hadAny = false;

  const q = p.get("q");
  if (q != null) { next.query = q; hadAny = true; }

  const gate = oneOf(p.get("gate"), GATES);
  if (gate) { next.gate = gate; hadAny = true; }

  // ★ `sector`(단수)도 받는다 — 결과 추적에서 섹터 하나를 눌러 들어오는 경로다.
  //   두 이름을 다 받지 않으면 링크가 조용히 무시되고 전체 목록이 뜬다.
  const sectors = p.has("sectors") ? splitList(p.get("sectors")) : splitList(p.get("sector"));
  if (p.has("sectors") || p.has("sector")) { next.sectors = sectors; hadAny = true; }

  if (p.has("grades") || p.has("grade")) {
    const raw = p.has("grades") ? splitList(p.get("grades")) : splitList(p.get("grade"));
    next.grades = raw.filter((g): g is Grade => (GRADES as string[]).includes(g));
    hadAny = true;
  }

  const cap = oneOf(p.get("cap"), CAPS);
  if (cap) { next.cap = cap; hadAny = true; }

  const consensus = oneOf(p.get("consensus"), CONSENSUS);
  if (consensus) { next.consensus = consensus; hadAny = true; }

  const quarter = p.get("quarter");
  if (quarter) { next.quarter = quarter; hadAny = true; }

  const sort = p.get("sort");
  const encodedSorts = splitList(p.get("sorts"));
  if (p.has("sorts")) {
    next.sorts = encodedSorts.flatMap((item): SortRule[] => {
      const [key, rawDir] = item.split(":");
      return isActiveSortKey(key) && (rawDir === "asc" || rawDir === "desc")
        ? [{ key, dir: rawDir }]
        : [];
    });
    hadAny = true;
  }
  // v1 링크도 깨뜨리지 않는다. 단일 정렬은 새 체인의 첫 규칙으로 옮긴다.
  const dir = oneOf(p.get("dir"), ["asc", "desc"] as SortDir[]);
  if (!p.has("sorts") && isActiveSortKey(sort)) {
    next.sorts = [{ key: sort, dir: dir ?? "desc" }];
    hadAny = true;
  }

  return { filters: next, hadAny };
}

/**
 * 상태를 쿼리 문자열로. **기본값과 같은 항목은 넣지 않는다** —
 * 안 그러면 아무것도 안 고른 화면의 주소가 여섯 개 파라미터로 길어져
 * "내가 뭘 걸어 뒀나"를 주소만 봐서는 알 수 없게 된다.
 */
export function toQuery(f: DiscoveryFilters): string {
  const p = new URLSearchParams();
  if (f.query.trim()) p.set("q", f.query.trim());
  if (f.gate !== DEFAULT_FILTERS.gate) p.set("gate", f.gate);
  if (f.grades.length) p.set("grades", f.grades.join(","));
  if (f.sectors.length) p.set("sectors", f.sectors.join(","));
  if (f.cap !== DEFAULT_FILTERS.cap) p.set("cap", f.cap);
  if (f.consensus !== DEFAULT_FILTERS.consensus) p.set("consensus", f.consensus);
  if (f.quarter !== DEFAULT_FILTERS.quarter) p.set("quarter", f.quarter);
  if (f.sorts.length) p.set("sorts", f.sorts.map((s) => `${s.key}:${s.dir}`).join(","));
  return p.toString();
}

/**
 * 저장된 상태를 읽는다. **모양이 깨졌으면 조용히 기본값으로 돌아간다** —
 * 저장 형식을 바꿨을 때 옛 값 때문에 화면이 500으로 죽으면 안 된다.
 */
export function loadStored(): DiscoveryFilters | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<DiscoveryFilters>;
    if (!parsed || typeof parsed !== "object") return null;
    return {
      query: typeof parsed.query === "string" ? parsed.query : DEFAULT_FILTERS.query,
      gate: oneOf(parsed.gate ?? null, GATES) ?? DEFAULT_FILTERS.gate,
      grades: Array.isArray(parsed.grades)
        ? parsed.grades.filter((g): g is Grade => (GRADES as string[]).includes(g as string))
        : [],
      sectors: Array.isArray(parsed.sectors)
        ? parsed.sectors.filter((s): s is string => typeof s === "string")
        : [],
      cap: oneOf(parsed.cap ?? null, CAPS) ?? DEFAULT_FILTERS.cap,
      consensus: oneOf(parsed.consensus ?? null, CONSENSUS) ?? DEFAULT_FILTERS.consensus,
      quarter: typeof parsed.quarter === "string" ? parsed.quarter : DEFAULT_FILTERS.quarter,
      sorts: Array.isArray(parsed.sorts)
        ? parsed.sorts.flatMap((item): SortRule[] => {
            if (!item || typeof item !== "object") return [];
            const key = (item as Partial<SortRule>).key;
            const dir = (item as Partial<SortRule>).dir;
            return typeof key === "string" && isActiveSortKey(key) &&
              (dir === "asc" || dir === "desc")
              ? [{ key, dir }]
              : [];
          })
        : [],
    };
  } catch {
    return null;
  }
}

export function saveStored(f: DiscoveryFilters): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(f));
  } catch {
    // 저장이 막혀 있어도(프라이빗 모드 등) 화면은 계속 동작해야 한다.
  }
}

/** 발굴 목록으로 가는 링크. 결과 추적의 섹터 행이 이걸 쓴다. */
export function discoveryHref(partial: Partial<DiscoveryFilters>): string {
  const q = toQuery({ ...DEFAULT_FILTERS, ...partial });
  return q ? `/?${q}` : "/";
}
