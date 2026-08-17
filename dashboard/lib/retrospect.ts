// PRD Ref: §2 검토⑥, §9 /outcome — 회고 분석
//
// ★★ **이 모듈이 답하려는 질문:**
//   "과거 실적 시즌으로 돌아간다면, 어떤 특징의 종목을 언제 샀어야 최고였나?"
//   그리고 "그래서 이번 시즌엔 무엇을 해야 하나?"
//
// ★ 이 분석은 **표본이 없으면 말하지 않는다.** 2건으로 "반도체가 최고"라고 쓰면
//   그럴듯하게 읽히지만 완전히 틀린 조언이 된다. 최소 표본을 못 넘기면
//   결론 대신 "아직 판단할 수 없다"와 그 이유를 돌려준다.
//
// ★ 초과수익(지수 대비)으로만 판단한다. 절대수익은 시장이 오른 건지
//   종목이 좋았던 건지 구분하지 못한다.

import {
  HORIZONS,
  type Horizon,
  type OutcomeRow,
  excessField,
  horizonLabel,
  median,
} from "./outcome";
import { sectorOf } from "./sector";
import type { ScreenRow, UniverseRow } from "./types";

/** 결론을 내기 위한 최소 표본. 이보다 적으면 **숫자를 보여주되 결론은 내지 않는다.** */
export const MIN_SAMPLE = 8;
/** "이 정도면 의미 있다"고 부를 초과수익 문턱(%p). */
export const MEANINGFUL_EDGE = 1.5;

export interface EnrichedOutcome extends OutcomeRow {
  name: string;
  sector: string;
  marketCap: number | null;
  hasConsensus: boolean | null;
  turnaround: boolean | null;
  baseEffect: boolean | null;
}

/**
 * outcome 행에 섹터·시총·특성을 붙인다. 없는 건 붙이지 않는다(추측 금지).
 *
 * ★ 스크린 행은 **그 outcome과 같은 분기**를 먼저 찾는다(T40).
 *   종목별 최신 행만 쓰면, 분기가 쌓인 뒤에는 2026.2Q 결과에 2026.3Q 판정을
 *   붙이게 된다 — 발표 시점에 우리가 뭘 알았는지가 요점인데 그게 뒤섞인다.
 *   지금은 outcome이 한 분기뿐이라 결과가 같지만(실측 175/117 동일),
 *   분기가 늘면 조용히 갈라진다.
 */
export function enrich(
  rows: OutcomeRow[],
  universe: Map<string, UniverseRow>,
  screens: Map<string, ScreenRow>,
  /** `code|year|quarter` → 스크린 행. 있으면 이걸 우선한다. */
  screensByQuarter?: Map<string, ScreenRow>
): EnrichedOutcome[] {
  return rows.map((r) => {
    const u = universe.get(r.code);
    const s =
      screensByQuarter?.get(`${r.code}|${r.fiscal_year}|${r.fiscal_quarter}`) ??
      screens.get(r.code);
    return {
      ...r,
      name: u?.name ?? r.code,
      sector: sectorOf(u),
      marketCap: u?.market_cap_krw ?? null,
      hasConsensus: s?.has_consensus ?? null,
      turnaround: s?.turnaround ?? null,
      baseEffect: s?.base_effect_warning ?? null,
    };
  });
}

// ═══════════════════════════════════════════════════════════════════
// 집계
// ═══════════════════════════════════════════════════════════════════
export interface Cell {
  /** 측정된 표본 수. `total`과 다르다 — 거래일이 모자라면 측정이 안 된다. */
  n: number;
  total: number;
  median: number | null;
  mean: number | null;
  /** 초과수익이 양(+)인 비율. 중앙값만 보면 "몇 종목이나 통했나"를 못 본다. */
  winRate: number | null;
}

export const EMPTY_CELL: Cell = { n: 0, total: 0, median: null, mean: null, winRate: null };

function summarize(values: number[], total: number): Cell {
  if (values.length === 0) return { ...EMPTY_CELL, total };
  const sum = values.reduce((a, b) => a + b, 0);
  return {
    n: values.length,
    total,
    median: median(values),
    mean: sum / values.length,
    winRate: values.filter((v) => v > 0).length / values.length,
  };
}

export interface Row {
  key: string;
  /** 시점별 결과. 키는 Horizon. */
  cells: Map<Horizon, Cell>;
  /** 전체 표본 수(측정 여부 무관). 그룹 크기 판단에 쓴다. */
  total: number;
}

/** 그룹 × 시점 표를 만든다. */
export function crosstab(
  rows: EnrichedOutcome[],
  keyOf: (r: EnrichedOutcome) => string | null
): Row[] {
  const buckets = new Map<string, EnrichedOutcome[]>();
  for (const r of rows) {
    const k = keyOf(r);
    if (k == null) continue;
    const list = buckets.get(k) ?? [];
    list.push(r);
    buckets.set(k, list);
  }
  return [...buckets.entries()]
    .map(([key, list]) => {
      const cells = new Map<Horizon, Cell>();
      for (const days of HORIZONS) {
        const field = excessField(days);
        const values = list
          .map((r) => r[field])
          .filter((v): v is number => typeof v === "number");
        cells.set(days, summarize(values, list.length));
      }
      return { key, cells, total: list.length };
    })
    .sort((a, b) => b.total - a.total);
}

// ═══════════════════════════════════════════════════════════════════
// 그룹 정의 — "어떤 특징"의 후보들
// ═══════════════════════════════════════════════════════════════════
export function scoreBucket(score: number | null): string | null {
  if (score == null) return null;
  if (score >= 90) return "스코어 90+";
  if (score >= 75) return "스코어 75~89";
  if (score >= 60) return "스코어 60~74";
  return "스코어 60 미만";
}

export function priBucket(pri: number | null): string | null {
  if (pri == null) return null;
  if (pri < 20) return "반영도 20 미만 (거의 미반영)";
  if (pri < 40) return "반영도 20~39 (미반영)";
  if (pri <= 65) return "반영도 40~65 (부분반영)";
  return "반영도 66+ (선반영)";
}

export function capBucket(cap: number | null): string | null {
  if (cap == null) return null;
  if (cap >= 1e12) return "대형주 (1조 이상)";
  if (cap >= 3e11) return "중형주 (3천억~1조)";
  return "소형주 (3천억 미만)";
}

export const FEATURE_GROUPS: {
  title: string;
  /** 무엇을 가르는 축인지. 표 위에 그대로 쓴다. */
  note: string;
  keyOf: (r: EnrichedOutcome) => string | null;
}[] = [
  {
    title: "등급",
    note: "스코어와 반영도를 교차한 최종 판정",
    keyOf: (r) => r.grade_at_announce ?? null,
  },
  {
    title: "섹터",
    note: "어떤 업종이 실적 시즌에 실제로 움직였는가",
    keyOf: (r) => r.sector,
  },
  {
    title: "스코어 구간",
    note: "실적 가속이 강할수록 더 올랐는가",
    keyOf: (r) => scoreBucket(r.score_at_announce),
  },
  {
    title: "주가반영도 구간",
    note: "★ 이 시스템의 핵심 가설 — 덜 반영된 종목이 더 오르는가",
    keyOf: (r) => priBucket(r.pri_at_announce),
  },
  {
    title: "시가총액",
    note: "소형주가 더 크게 반응하는가",
    keyOf: (r) => capBucket(r.marketCap),
  },
  {
    title: "컨센서스 유무",
    note: "증권사가 안 보는 종목이 오히려 기회인가(ADR 1의 전제)",
    keyOf: (r) =>
      r.hasConsensus == null ? null : r.hasConsensus ? "컨센서스 있음" : "컨센서스 없음",
  },
  {
    title: "흑자 전환",
    note: "적자에서 흑자로 돌아선 종목의 반응",
    keyOf: (r) => (r.turnaround == null ? null : r.turnaround ? "흑전·적자축소" : "해당 없음"),
  },
];

// ═══════════════════════════════════════════════════════════════════
// 인사이트 — 표에서 **문장**을 뽑는다
// ═══════════════════════════════════════════════════════════════════
export type Confidence = "확실" | "참고" | "불충분";

export interface Insight {
  /** 한 줄 결론. */
  headline: string;
  /** 근거가 된 실제 숫자. 문장만 있으면 검증할 수 없다. */
  evidence: string;
  confidence: Confidence;
  /** 이번 시즌에 무엇을 할 것인가. */
  action?: string;
}

function fmtPp(value: number | null): string {
  if (value == null) return "—";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%p`;
}

function confidenceOf(n: number): Confidence {
  if (n >= MIN_SAMPLE * 3) return "확실";
  if (n >= MIN_SAMPLE) return "참고";
  return "불충분";
}

/** 표본이 충분한 시점만 돌려준다. 없으면 빈 배열. */
export function usableHorizons(rows: EnrichedOutcome[]): Horizon[] {
  return HORIZONS.filter((days) => {
    const field = excessField(days);
    return rows.filter((r) => typeof r[field] === "number").length >= MIN_SAMPLE;
  });
}

/**
 * "언제 샀어야 했나" — 시점별 전체 중앙 초과수익.
 *
 * ★ 발표 **전** 구간이 크면 정보가 미리 반영된 것이고, 발표 **후**가 크면
 *   발표를 보고 들어가도 늦지 않았다는 뜻이다. 이 대비가 전략의 핵심이다.
 */
export function timingProfile(rows: EnrichedOutcome[]): { days: Horizon; cell: Cell }[] {
  return HORIZONS.map((days) => {
    const field = excessField(days);
    const values = rows
      .map((r) => r[field])
      .filter((v): v is number => typeof v === "number");
    return { days, cell: summarize(values, rows.length) };
  });
}

/** 한 시점에서 가장 성적이 좋았던 그룹 상위 N. 표본 미달은 제외한다. */
export function topGroups(
  table: Row[],
  days: Horizon,
  limit = 3,
  minSample = MIN_SAMPLE
): { key: string; cell: Cell }[] {
  return table
    .map((r) => ({ key: r.key, cell: r.cells.get(days) ?? EMPTY_CELL }))
    .filter((x) => x.cell.n >= minSample && x.cell.median != null)
    .sort((a, b) => (b.cell.median as number) - (a.cell.median as number))
    .slice(0, limit);
}

/**
 * 회고 인사이트를 만든다.
 *
 * ★ 규칙 기반이다 — LLM을 쓰지 않는다. 이 화면은 **숫자에서 직접 나온 말**만
 *   해야 하고, 표본이 부족하면 그 사실을 말해야 한다.
 */
export function buildInsights(
  rows: EnrichedOutcome[],
  tables: Map<string, Row[]>
): { insights: Insight[]; bestTiming: Horizon | null; caveats: string[] } {
  const insights: Insight[] = [];
  const caveats: string[] = [];

  const usable = usableHorizons(rows);
  const missing = HORIZONS.filter((d) => !usable.includes(d));
  if (missing.length) {
    caveats.push(
      `${missing.map(horizonLabel).join(" · ")}은 아직 측정 표본이 ${MIN_SAMPLE}건 미만이라 ` +
        `결론을 내지 않았다. 거래일이 쌓이면 자동으로 채워진다.`
    );
  }
  if (usable.length === 0) {
    return { insights, bestTiming: null, caveats };
  }

  // ── ① 언제 샀어야 했나 ────────────────────────────────────────
  const profile = timingProfile(rows).filter((p) => usable.includes(p.days));
  const best = [...profile].sort(
    (a, b) => (b.cell.median ?? -Infinity) - (a.cell.median ?? -Infinity)
  )[0];
  const pre = profile.find((p) => p.days === -5)?.cell;
  const post = profile.find((p) => p.days === 5)?.cell;

  if (best?.cell.median != null) {
    // ★★ **중앙값이 음수면 "가장 컸다"고 말해서는 안 된다.**
    //   비교상 1위여도 지수를 못 이긴 것이다. 여기서 부호를 안 보면
    //   "확인 후 진입이 유리했다"처럼 **데이터가 말하지 않은 조언**이 나간다.
    //   실측(2026.2Q): 최선 구간이 발표 후 5일인데 중앙값 −0.73%p였다.
    const positive = best.cell.median > 0;
    insights.push({
      headline: positive
        ? `초과수익이 가장 컸던 구간은 **${horizonLabel(best.days)}**이다 ` +
          `(중앙값 ${fmtPp(best.cell.median)}).`
        : `**어느 구간에서도 지수를 이기지 못했다.** 그중 가장 나았던 구간이 ` +
          `${horizonLabel(best.days)}인데 그마저 중앙값 ${fmtPp(best.cell.median)}다.`,
      evidence:
        `측정 ${best.cell.n}건 · 플러스 비율 ${((best.cell.winRate ?? 0) * 100).toFixed(0)}%`,
      confidence: confidenceOf(best.cell.n),
      action: positive
        ? best.days < 0
          ? "발표 전 구간이 가장 컸다 — 발표를 보고 들어가면 이미 늦는다. " +
            "발표 일정을 미리 잡아 선제적으로 담는 전략이 유효했다."
          : best.days === 0
            ? "발표 당일 반응이 가장 컸다 — 장중 대응 속도가 수익을 갈랐다."
            : "발표를 확인하고 들어가도 늦지 않았다 — 확인 후 진입이 위험 대비 유리했다."
        : "게이트 통과만으로 사는 전략은 이 시즌에 통하지 않았다. " +
          "아래 특징별 표에서 **플러스가 나온 묶음만** 골라 담는 쪽으로 좁혀야 한다.",
    });
  }

  // ★ 발표 전 vs 후 — 둘 다 표본이 있을 때만. 한쪽이 비면 비교 자체가 성립하지 않는다.
  if (pre?.median != null && post?.median != null && pre.n >= MIN_SAMPLE && post.n >= MIN_SAMPLE) {
    const gap = post.median - pre.median;
    insights.push({
      headline:
        gap > 0
          ? "발표 **후**가 발표 **전**보다 좋았다 — 시장이 실적을 미리 알지 못했다."
          : "발표 **전**이 발표 **후**보다 좋았다 — 정보가 먼저 반영되는 경향이 있었다.",
      evidence:
        `발표 전 5일 ${fmtPp(pre.median)} (${pre.n}건) vs ` +
        `발표 후 5일 ${fmtPp(post.median)} (${post.n}건) · 차이 ${fmtPp(gap)}`,
      confidence: confidenceOf(Math.min(pre.n, post.n)),
      action:
        gap > 0
          ? "이번 시즌도 발표 확인 후 진입을 기본으로 삼되, 발표 당일 급등한 종목은 추격을 피한다."
          : "이번 시즌은 발표 전 선제 진입 비중을 늘리되, 기저효과 경고가 붙은 종목은 뺀다.",
    });
  }

  // ── ② 어떤 섹터였나 ──────────────────────────────────────────
  const sectorTable = tables.get("섹터") ?? [];
  for (const days of usable) {
    const top = topGroups(sectorTable, days, 3);
    if (top.length === 0) continue;
    const head = top[0];
    if ((head.cell.median ?? 0) < MEANINGFUL_EDGE) continue;
    insights.push({
      headline:
        `**${horizonLabel(days)}** 기준으로 가장 강했던 섹터는 **${head.key}**다 ` +
        `(중앙 초과수익 ${fmtPp(head.cell.median)}).`,
      evidence: top
        .map((t) => `${t.key} ${fmtPp(t.cell.median)}(${t.cell.n}건)`)
        .join(" · "),
      confidence: confidenceOf(head.cell.n),
      action: `이번 시즌 ${head.key} 종목이 게이트를 통과하면 우선순위를 올린다.`,
    });
    break; // 가장 표본이 좋은 한 시점만 — 시점마다 반복하면 읽히지 않는다
  }

  // ── ③ 이 시스템의 핵심 가설: 미반영이 더 오르는가 ────────────
  const priTable = tables.get("주가반영도 구간") ?? [];
  for (const days of usable) {
    const low = priTable.find((r) => r.key.startsWith("반영도 20 미만"))?.cells.get(days);
    const high = priTable.find((r) => r.key.startsWith("반영도 66+"))?.cells.get(days);
    if (!low?.median || !high?.median) continue;
    if (low.n < MIN_SAMPLE || high.n < MIN_SAMPLE) continue;
    const gap = low.median - high.median;
    insights.push({
      headline:
        gap > 0
          ? "**미반영 종목이 선반영 종목보다 더 올랐다** — 이 시스템의 핵심 가설이 지지된다."
          : "미반영 종목이 선반영 종목보다 더 오르지 **않았다** — 가설이 이번 표본에서는 확인되지 않았다.",
      evidence:
        `${horizonLabel(days)} · 반영도 20 미만 ${fmtPp(low.median)}(${low.n}건) vs ` +
        `반영도 66+ ${fmtPp(high.median)}(${high.n}건) · 차이 ${fmtPp(gap)}`,
      confidence: confidenceOf(Math.min(low.n, high.n)),
      action:
        gap > 0
          ? "반영도가 낮은 ★ 등급을 최우선으로 본다."
          : "반영도만으로 거르지 말고 스코어·섹터를 함께 본다. 한 시즌 표본이므로 단정하지 않는다.",
    });
    break;
  }

  // ── ④ 커버리지 공백(ADR 1)이 실제로 기회였나 ────────────────
  const consTable = tables.get("컨센서스 유무") ?? [];
  for (const days of usable) {
    const no = consTable.find((r) => r.key === "컨센서스 없음")?.cells.get(days);
    const yes = consTable.find((r) => r.key === "컨센서스 있음")?.cells.get(days);
    if (!no?.median || !yes?.median) continue;
    if (no.n < MIN_SAMPLE || yes.n < MIN_SAMPLE) continue;
    const gap = no.median - yes.median;
    insights.push({
      headline:
        gap > 0
          ? "**증권사가 안 보는 종목이 더 올랐다** — 커버리지 공백을 겨냥한 설계(ADR 1)가 유효했다."
          : "컨센서스가 있는 종목이 더 올랐다 — 이번 표본에서는 커버리지 공백의 우위가 없었다.",
      evidence:
        `${horizonLabel(days)} · 컨센 없음 ${fmtPp(no.median)}(${no.n}건) vs ` +
        `컨센 있음 ${fmtPp(yes.median)}(${yes.n}건)`,
      confidence: confidenceOf(Math.min(no.n, yes.n)),
    });
    break;
  }

  // ── ⑤ 스코어가 실제로 작동했나 ──────────────────────────────
  const scoreTable = tables.get("스코어 구간") ?? [];
  for (const days of usable) {
    const hi = scoreTable.find((r) => r.key === "스코어 90+")?.cells.get(days);
    const lo = scoreTable.find((r) => r.key === "스코어 60 미만")?.cells.get(days);
    if (!hi?.median || !lo?.median) continue;
    if (hi.n < MIN_SAMPLE || lo.n < MIN_SAMPLE) continue;
    insights.push({
      headline:
        hi.median > lo.median
          ? "**스코어가 높을수록 더 올랐다** — 배점이 방향은 맞게 잡혀 있다."
          : "스코어가 높다고 더 오르지 않았다 — 배점 재검토가 필요하다.",
      evidence:
        `${horizonLabel(days)} · 90+ ${fmtPp(hi.median)}(${hi.n}건) vs ` +
        `60 미만 ${fmtPp(lo.median)}(${lo.n}건)`,
      confidence: confidenceOf(Math.min(hi.n, lo.n)),
    });
    break;
  }

  return { insights, bestTiming: best?.days ?? null, caveats };
}

/**
 * "이번 시즌 전략" — 위 인사이트에서 **실행 문장**만 추린다.
 *
 * ★ 근거가 '불충분'인 인사이트의 action은 내보내지 않는다.
 *   표본 2건에서 나온 조언이 확신에 찬 문장으로 보이면 안 된다.
 */
export function seasonPlaybook(insights: Insight[]): string[] {
  return insights
    .filter((i) => i.confidence !== "불충분" && i.action)
    .map((i) => i.action as string);
}
