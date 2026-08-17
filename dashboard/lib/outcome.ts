// PRD Ref: §2 검토⑥, §9 /outcome
//
// ★ 이 화면의 존재 이유: 스코어 배점에 이론적 근거가 없다.
//   데이터로 조정할 수 있는 구조를 지금 만들어 두지 않으면
//   이 시스템은 영구히 검증 불가능한 자의적 룰로 남는다.

import { selectAll } from "./supabase";
import type { Grade } from "./types";

export const HORIZONS = [1, 5, 20, 60] as const;
export type Horizon = (typeof HORIZONS)[number];

export interface OutcomeRow {
  code: string;
  fiscal_year: number;
  fiscal_quarter: number;
  announce_date: string | null;
  grade_at_announce: Grade | null;
  score_at_announce: number | null;
  pri_at_announce: number | null;
  ret_d1: number | null;
  ret_d5: number | null;
  ret_d20: number | null;
  ret_d60: number | null;
  excess_d1: number | null;
  excess_d5: number | null;
  excess_d20: number | null;
  excess_d60: number | null;
}

const COLUMNS =
  "code,fiscal_year,fiscal_quarter,announce_date,grade_at_announce," +
  "score_at_announce,pri_at_announce," +
  "ret_d1,ret_d5,ret_d20,ret_d60,excess_d1,excess_d5,excess_d20,excess_d60";

export async function getOutcomes(): Promise<OutcomeRow[]> {
  return selectAll<OutcomeRow>("outcome_tracking", COLUMNS);
}

export function excessField(days: Horizon): keyof OutcomeRow {
  return `excess_d${days}` as keyof OutcomeRow;
}

export function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[mid]
    : (sorted[mid - 1] + sorted[mid]) / 2;
}

export function quantile(values: number[], q: number): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return lo === hi ? sorted[lo] : sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

export interface GroupStat {
  key: string;
  total: number;
  /** 측정된 표본 수. **`total`과 다르다** — 거래일이 모자라면 측정이 안 된다. */
  n: number;
  unmeasured: number;
  median: number | null;
  p25: number | null;
  p75: number | null;
  min: number | null;
  max: number | null;
}

/**
 * 그룹별 초과수익 요약.
 *
 * ★ 측정 못 한 행을 조용히 빼면 "표본 26개"가 실제로는 2개인 걸 못 알아본다.
 *   `total`과 `n`을 **둘 다** 돌려주고 화면에서 함께 보여준다.
 */
export function groupStats(
  rows: OutcomeRow[],
  key: (row: OutcomeRow) => string,
  days: Horizon
): GroupStat[] {
  const field = excessField(days);
  const buckets = new Map<string, { total: number; values: number[] }>();

  for (const row of rows) {
    const k = key(row);
    const bucket = buckets.get(k) ?? { total: 0, values: [] };
    bucket.total += 1;
    const value = row[field];
    if (typeof value === "number") bucket.values.push(value);
    buckets.set(k, bucket);
  }

  return [...buckets.entries()].map(([k, b]) => ({
    key: k,
    total: b.total,
    n: b.values.length,
    unmeasured: b.total - b.values.length,
    median: median(b.values),
    p25: quantile(b.values, 0.25),
    p75: quantile(b.values, 0.75),
    min: b.values.length ? Math.min(...b.values) : null,
    max: b.values.length ? Math.max(...b.values) : null,
  }));
}

/**
 * 스피어만 순위상관(IC).
 *
 * ★ **둘 다 있는 쌍만** 쓴다. 한쪽이 null인 걸 0으로 채우면 상관이 조작된다.
 * ★ 3쌍 미만이면 계산하지 않는다 — 숫자가 나와도 의미가 없다.
 *   `src/analysis/outcome.py::spearman`과 같은 규칙이어야 한다.
 */
export function spearman(
  xs: (number | null)[],
  ys: (number | null)[]
): number | null {
  const pairs: [number, number][] = [];
  for (let i = 0; i < xs.length; i += 1) {
    const x = xs[i];
    const y = ys[i];
    if (typeof x === "number" && typeof y === "number") pairs.push([x, y]);
  }
  if (pairs.length < 3) return null;

  const rank = (values: number[]): number[] => {
    const order = values.map((v, i) => i).sort((a, b) => values[a] - values[b]);
    const ranks = new Array<number>(values.length).fill(0);
    let i = 0;
    while (i < order.length) {
      let j = i;
      while (j + 1 < order.length && values[order[j + 1]] === values[order[i]]) j += 1;
      const avg = (i + j) / 2 + 1;
      for (let k = i; k <= j; k += 1) ranks[order[k]] = avg;
      i = j + 1;
    }
    return ranks;
  };

  const a = rank(pairs.map((p) => p[0]));
  const b = rank(pairs.map((p) => p[1]));
  const n = pairs.length;
  const meanA = a.reduce((s, v) => s + v, 0) / n;
  const meanB = b.reduce((s, v) => s + v, 0) / n;
  let num = 0;
  let denA = 0;
  let denB = 0;
  for (let i = 0; i < n; i += 1) {
    num += (a[i] - meanA) * (b[i] - meanB);
    denA += (a[i] - meanA) ** 2;
    denB += (b[i] - meanB) ** 2;
  }
  if (denA === 0 || denB === 0) return null; // 한쪽이 전부 같은 값
  return num / Math.sqrt(denA * denB);
}

/** 측정 건수가 가장 많은 시점. D+20이 비면 D+5로 내려간다. */
export function bestHorizon(rows: OutcomeRow[]): Horizon {
  let best: Horizon = HORIZONS[0];
  let bestCount = -1;
  for (const days of HORIZONS) {
    const field = excessField(days);
    const count = rows.filter((r) => typeof r[field] === "number").length;
    if (count > bestCount) {
      best = days;
      bestCount = count;
    }
  }
  return best;
}
