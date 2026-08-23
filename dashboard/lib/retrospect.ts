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
    // ★★ **둘 다 음수면 어느 쪽 진입도 권하지 않는다.**
    //   인사이트 ①에는 이 부호 검사가 있는데 여기에는 없어서, 두 구간이 모두
    //   지수를 못 이긴 시즌에도 "발표 전 선제 진입 비중을 늘려라"가 나갔다.
    //   실측(2026.2Q): 발표 전 −1.70%p · 발표 후 −2.36%p인데 선제 진입을 권했고,
    //   같은 화면의 ①은 "확인 후 진입"이라 **두 조언이 서로 어긋난 채로** 떠 있었다.
    //   덜 나쁜 쪽은 비교 결과일 뿐 전략이 아니다 — 틀린 안내는 사람을 틀린 행동으로 이끈다(T83).
    const bothLost = pre.median <= 0 && post.median <= 0;
    insights.push({
      headline: bothLost
        ? "발표 전·후 **어느 쪽도 지수를 이기지 못했다** — 진입 시점을 바꾸는 것으로는 해결되지 않았다."
        : gap > 0
          ? "발표 **후**가 발표 **전**보다 좋았다 — 시장이 실적을 미리 알지 못했다."
          : "발표 **전**이 발표 **후**보다 좋았다 — 정보가 먼저 반영되는 경향이 있었다.",
      evidence:
        `발표 전 5일 ${fmtPp(pre.median)} (${pre.n}건) vs ` +
        `발표 후 5일 ${fmtPp(post.median)} (${post.n}건) · 차이 ${fmtPp(gap)}`,
      confidence: confidenceOf(Math.min(pre.n, post.n)),
      action: bothLost
        ? "타이밍이 아니라 **대상**을 좁혀야 한다 — 아래 섹터·특징별 표에서 플러스가 나온 묶음만 고른다."
        : gap > 0
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

// ═══════════════════════════════════════════════════════════════════
// 섹터 × 발표일 타이밍 — "그 섹터는 발표 전·당일·후 중 언제가 좋았나, 왜"
//                          (사용자 지정 2026-08-22)
// ═══════════════════════════════════════════════════════════════════

export interface SectorTiming {
  sector: string;
  /** 그 섹터의 전체 표본 수. */
  total: number;
  /** 가장 성적이 좋았던 시점. 표본이 모자라면 null. */
  best: Horizon | null;
  bestCell: Cell | null;
  /** 시점별 셀 — 표로 그대로 그린다. */
  cells: Map<Horizon, Cell>;
  /** **왜 그 시점이었나.** 규칙 기반 해석. */
  why: string;
  /** 그래서 이번 시즌 이 섹터를 어떻게 다룰 것인가. */
  action: string;
  confidence: Confidence;
  /** 해석의 재료 — 화면에 근거로 함께 보여준다. */
  medianPri: number | null;
  coverageRate: number | null;
}

/**
 * 발표일 기준으로 **언제가 가장 좋았는지**를 섹터별로 낸다.
 *
 * ★★ 왜 그랬는지를 지어내지 않는다. 쓸 수 있는 재료는 세 가지뿐이다:
 *   ① 최고 시점이 발표 **전**인가 **후**인가
 *   ② 그 섹터의 발표 시점 **주가반영도(PRI) 중앙값** — 이미 올라 있었나
 *   ③ 그 섹터의 **컨센서스 보유 비율** — 증권사가 미리 보고 있었나
 *   이 셋의 조합으로만 문장을 만든다. 산업 논리를 끌어오면 그럴듯하지만
 *   데이터가 뒷받침하지 않는 말이 된다.
 *
 * ★ 최고 시점의 중앙값이 **음수면 "좋았다"고 말하지 않는다.** 비교상 1위여도
 *   지수를 못 이긴 것이다 — 부호를 안 보면 데이터가 말하지 않은 조언이 나간다.
 */
export function sectorTiming(
  rows: EnrichedOutcome[],
  minSample = MIN_SAMPLE
): SectorTiming[] {
  const buckets = new Map<string, EnrichedOutcome[]>();
  for (const r of rows) {
    const list = buckets.get(r.sector) ?? [];
    list.push(r);
    buckets.set(r.sector, list);
  }

  const out: SectorTiming[] = [];
  for (const [sector, list] of buckets) {
    const cells = new Map<Horizon, Cell>();
    for (const days of HORIZONS) {
      const field = excessField(days);
      const values = list
        .map((r) => r[field])
        .filter((v): v is number => typeof v === "number");
      cells.set(days, summarize(values, list.length));
    }

    const ranked = HORIZONS.map((days) => ({ days, cell: cells.get(days) as Cell }))
      .filter((x) => x.cell.n >= minSample && x.cell.median != null)
      .sort((a, b) => (b.cell.median as number) - (a.cell.median as number));
    const top = ranked[0] ?? null;

    const priValues = list
      .map((r) => r.pri_at_announce)
      .filter((v): v is number => typeof v === "number");
    const medianPri = median(priValues);
    const judged = list.filter((r) => r.hasConsensus != null);
    const coverageRate = judged.length
      ? judged.filter((r) => r.hasConsensus).length / judged.length
      : null;

    let why: string;
    let action: string;

    if (!top) {
      why = `측정 표본이 ${minSample}건 미만이라 어느 시점이 좋았는지 말하지 않는다.`;
      action = "표본이 쌓일 때까지 이 섹터는 타이밍 근거 없이 개별 종목으로만 본다.";
    } else if ((top.cell.median as number) <= 0) {
      why =
        `어느 시점에서도 지수를 이기지 못했다. 가장 나았던 ${horizonLabel(top.days)}조차 ` +
        `중앙값 ${fmtPp(top.cell.median)}다 — 이 섹터는 실적 발표 자체가 촉매가 되지 못했다.`;
      action = "이번 시즌 이 섹터는 발표 이벤트만 보고 담지 않는다. 다른 근거가 필요하다.";
    } else if (top.days < 0) {
      // 발표 전이 최고 — 정보가 먼저 반영됐다.
      const covered = coverageRate != null && coverageRate >= 0.4;
      why =
        `발표 **전** 구간이 가장 좋았다(${fmtPp(top.cell.median)}). 실적이 나오기 전에 이미 올랐다는 뜻이다. ` +
        (covered
          ? `이 섹터는 컨센서스 보유 비율이 ${((coverageRate as number) * 100).toFixed(0)}%로 높다 — ` +
            "증권사가 미리 추정치를 내놓아 시장이 발표 전에 알고 있었을 가능성이 크다."
          : "컨센서스 커버리지는 낮은데도 미리 올랐다 — 업황 지표나 전방 고객사 동향처럼 " +
            "실적보다 먼저 나오는 신호가 있었을 가능성이 크다.") +
        (medianPri != null
          ? ` 발표 시점 반영도 중앙값이 ${medianPri.toFixed(0)}로 ` +
            (medianPri >= 65
              ? "이미 선반영 구간이었다."
              : medianPri >= 40
                ? "부분 반영 구간이었다."
                : "낮은 편이었다.")
          : "");
      action =
        "이번 시즌 이 섹터는 **발표를 보고 들어가면 늦는다.** 발표 일정을 미리 잡아 " +
        "직전 구간에 선제적으로 담되, 기저효과 경고가 붙은 종목은 뺀다.";
    } else if (top.days === 0) {
      why =
        `**발표 당일** 반응이 가장 컸다(${fmtPp(top.cell.median)}). 발표 내용 자체가 촉매였고 ` +
        "시장이 미리 알지 못했다는 뜻이다." +
        (medianPri != null && medianPri < 40
          ? ` 발표 시점 반영도 중앙값이 ${medianPri.toFixed(0)}로 낮아, 미반영 상태에서 실적을 맞은 구조였다.`
          : "");
      action =
        "이번 시즌 이 섹터는 **장중 대응 속도가 수익을 가른다.** 발표 알림을 우선순위로 올린다.";
    } else {
      // 발표 후가 최고 — 반영이 늦었다. 이 시스템이 가장 잘 통하는 모양이다.
      const uncovered = coverageRate != null && coverageRate < 0.4;
      why =
        `**발표 후 ${top.days}일** 구간이 가장 좋았다(${fmtPp(top.cell.median)}). ` +
        "발표를 확인하고 들어가도 늦지 않았다 — 시장이 실적을 소화하는 데 시간이 걸렸다는 뜻이다." +
        (uncovered
          ? ` 이 섹터는 컨센서스 보유 비율이 ${((coverageRate as number) * 100).toFixed(0)}%로 낮다 — ` +
            "증권사가 안 보는 종목이 많아 반영이 느렸을 가능성이 크다(ADR 1이 겨냥하는 구간이다)."
          : "") +
        (medianPri != null && medianPri < 40
          ? ` 발표 시점 반영도 중앙값 ${medianPri.toFixed(0)}로 미반영 구간이었던 것도 같은 방향이다.`
          : "");
      action =
        "이번 시즌 이 섹터는 **발표 확인 후 진입**을 기본으로 삼는다. " +
        `${horizonLabel(top.days)}까지 보유하는 구간이 실측상 가장 나았다.`;
    }

    out.push({
      sector,
      total: list.length,
      best: top?.days ?? null,
      bestCell: top?.cell ?? null,
      cells,
      why,
      action,
      confidence: confidenceOf(top?.cell.n ?? 0),
      medianPri,
      coverageRate,
    });
  }

  // 결론을 낼 수 있는 섹터를 위로, 그 안에서는 최고 성적 순.
  return out.sort((a, b) => {
    const am = a.bestCell?.median ?? -Infinity;
    const bm = b.bestCell?.median ?? -Infinity;
    return bm - am || b.total - a.total;
  });
}

// ═══════════════════════════════════════════════════════════════════
// 시즌 결론 — 이번 시즌은 무엇이었고, 다음 시즌엔 무엇을 할 것인가
//              (사용자 지정 2026-08-22)
// ═══════════════════════════════════════════════════════════════════

export interface SeasonConclusion {
  /** 이번 시즌을 한 문장으로. */
  verdict: string;
  /** 그 근거가 된 실측 숫자들. */
  evidence: string[];
  /** 다음 시즌 실행 항목. 근거가 불충분한 것은 담지 않는다. */
  nextSeason: string[];
  /** 결론을 낼 만한 표본이 있었는가. */
  grounded: boolean;
  /**
   * 결론을 **약하게 만드는 사실**. 없으면 null.
   *
   * ★ 최소 표본(8건)을 넘겼다고 해서 대표성이 있는 것은 아니다. 발표 후 20·60일은
   *   **먼저 발표한 종목만** 거래일이 찼기 때문에, 그 구간의 표본은 시즌 초반
   *   종목으로 치우친다. 이걸 밝히지 않으면 25건짜리 결론이 1,081건짜리 결론처럼 읽힌다.
   */
  caution: string | null;
}

/**
 * 이번 시즌 결론 + 다음 시즌 전략을 **한 덩어리로** 만든다.
 *
 * ★ `buildInsights`는 축별로 흩어진 관찰을 낸다. 사람이 읽고 종합해야 하는데
 *   화면 맨 위에서 필요한 건 **이미 종합된 한 문장**이다.
 * ★ 표본이 없으면 결론을 지어내지 않는다 — `grounded: false`로 그 사실을 말한다.
 */
export function seasonConclusion(
  rows: EnrichedOutcome[],
  tables: Map<string, Row[]>,
  timing: SectorTiming[]
): SeasonConclusion {
  const usable = usableHorizons(rows);
  const evidence: string[] = [];
  const nextSeason: string[] = [];

  if (usable.length === 0) {
    return {
      verdict:
        "이번 시즌은 아직 결론을 낼 수 없다 — 어느 시점도 측정 표본이 " +
        `${MIN_SAMPLE}건에 못 미친다.`,
      evidence: [`대상 ${rows.length}건 · 측정 가능한 시점 0개`],
      nextSeason: [],
      grounded: false,
      caution: null,
    };
  }

  // ── ① 시즌 전체 성적 ──────────────────────────────────────────
  const profile = timingProfile(rows).filter((p) => usable.includes(p.days));
  const best = [...profile].sort(
    (a, b) => (b.cell.median ?? -Infinity) - (a.cell.median ?? -Infinity)
  )[0];
  const beatIndex = best?.cell.median != null && best.cell.median > 0;

  evidence.push(
    `전체 ${rows.length}건 · 최선 구간 ${horizonLabel(best.days)} 중앙값 ${fmtPp(best.cell.median)} ` +
      `(측정 ${best.cell.n}건 · 플러스 비율 ${((best.cell.winRate ?? 0) * 100).toFixed(0)}%)`
  );

  // ── ② 어떤 섹터가 통했나 ──────────────────────────────────────
  const winners = timing.filter(
    (t) => t.bestCell?.median != null && (t.bestCell.median as number) > MEANINGFUL_EDGE
  );
  if (winners.length > 0) {
    evidence.push(
      "지수를 의미 있게 이긴 섹터: " +
        winners
          .slice(0, 4)
          .map((t) => `${t.sector} ${fmtPp(t.bestCell!.median)}(${horizonLabel(t.best!)})`)
          .join(" · ")
    );
  }

  // ── ③ 핵심 가설(미반영이 더 오르는가) ─────────────────────────
  const priTable = tables.get("주가반영도 구간") ?? [];
  let priHeld: boolean | null = null;
  for (const days of usable) {
    const low = priTable.find((r) => r.key.startsWith("반영도 20 미만"))?.cells.get(days);
    const high = priTable.find((r) => r.key.startsWith("반영도 66+"))?.cells.get(days);
    if (!low?.median || !high?.median) continue;
    if (low.n < MIN_SAMPLE || high.n < MIN_SAMPLE) continue;
    priHeld = low.median > high.median;
    evidence.push(
      `${horizonLabel(days)} · 미반영(20 미만) ${fmtPp(low.median)} vs 선반영(66+) ${fmtPp(high.median)}`
    );
    break;
  }

  // ── 결론 문장 ─────────────────────────────────────────────────
  let verdict: string;
  if (!beatIndex) {
    verdict =
      "**이번 시즌은 게이트 통과만으로는 지수를 이기지 못했다.** " +
      `최선 구간(${horizonLabel(best.days)})조차 중앙값 ${fmtPp(best.cell.median)}였다. ` +
      (winners.length > 0
        ? `다만 섹터를 좁히면 달랐다 — ${winners.length}개 섹터는 지수를 의미 있게 이겼다.`
        : "섹터를 좁혀도 지수를 의미 있게 이긴 곳이 없었다.");
  } else {
    verdict =
      `**이번 시즌은 ${horizonLabel(best.days)} 구간이 통했다** ` +
      `(중앙값 ${fmtPp(best.cell.median)} · 플러스 비율 ${((best.cell.winRate ?? 0) * 100).toFixed(0)}%). ` +
      (best.days < 0
        ? "정보가 발표 전에 반영되는 시즌이었다."
        : best.days === 0
          ? "발표 자체가 촉매인 시즌이었다."
          : "발표를 확인하고 들어가도 늦지 않은 시즌이었다.");
  }

  // ── 다음 시즌 실행 항목 ───────────────────────────────────────
  if (best.days < 0 && beatIndex) {
    nextSeason.push(
      "발표 **전**에 담는다 — 실적 캘린더로 발표 예정일을 미리 잡고 그 직전 구간에 진입한다."
    );
  } else if (best.days === 0 && beatIndex) {
    nextSeason.push("발표 **당일** 대응 속도가 전부다 — 즉시 알림을 최우선으로 둔다.");
  } else if (beatIndex) {
    nextSeason.push(
      `발표를 **확인하고** 진입한다 — ${horizonLabel(best.days)}까지 보유하는 구간이 가장 나았다.`
    );
  } else {
    nextSeason.push(
      "게이트 통과 전체를 담는 전략은 쓰지 않는다 — 아래에서 실제로 통한 섹터·특징으로 좁힌다."
    );
  }

  for (const t of winners.slice(0, 3)) {
    nextSeason.push(`**${t.sector}** — ${t.action}`);
  }

  if (priHeld === true) {
    nextSeason.push(
      "**반영도가 낮은 ★ 등급을 최우선으로 본다** — 미반영이 더 올랐다는 이 시스템의 핵심 가설이 이번 표본에서 지지됐다."
    );
  } else if (priHeld === false) {
    nextSeason.push(
      "반영도만으로 거르지 않는다 — 이번 표본에서는 미반영의 우위가 확인되지 않았다. 스코어·섹터를 함께 본다."
    );
  }

  nextSeason.push(
    "한 시즌 표본이다 — 다음 시즌 결과가 쌓이기 전까지 위 결론을 규칙으로 굳히지 않는다."
  );

  // ── 표본이 얇으면 그 사실을 결론에 붙인다 ─────────────────────
  // ★ 발표 후 20·60일은 **먼저 발표한 종목만** 거래일이 찬다. 그 구간이 1위로 뽑히면
  //   "시즌 초반 종목의 성적"을 "이번 시즌의 결론"으로 말하게 된다.
  const coverage = rows.length > 0 ? best.cell.n / rows.length : 0;
  const caution =
    best.days > 0 && coverage < 0.2
      ? `이 결론은 ${horizonLabel(best.days)} 표본 ${best.cell.n}건(전체 ${rows.length}건의 ` +
        `${(coverage * 100).toFixed(0)}%)에 기댄 것이다. 그 구간은 **먼저 발표한 종목만** ` +
        "거래일이 차 있어 시즌 초반 종목으로 치우친다 — 거래일이 쌓이면 결론이 바뀔 수 있다."
      : null;

  return { verdict, evidence, nextSeason, grounded: true, caution };
}
