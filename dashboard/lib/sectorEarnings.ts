// PRD Ref: §9 /outcome — 섹터별 실적 비교와 다음 분기 전망
//
// ★★ **이 모듈이 답하려는 질문(사용자 지정):**
//   "이번 분기에 어느 섹터 실적이 잘 나왔나?"
//   "지난 분기와 비교해 어느 섹터에 서프라이즈 종목이 많나?"
//   "그래서 다음 분기 실적은 어떻게 볼 것인가?"
//
// ★ 여기서 말하는 '서프라이즈'는 **컨센서스 대비가 아니다.** 코스닥 60%가 커버리지
//   0건이라 컨센 기준으로는 섹터 비교가 안 된다(ADR 1). 대신 이 시스템의 정의를 쓴다:
//   **게이트 통과 = 매출·영업이익 성장률이 둘 다 가속** → 그게 이 시스템의 서프라이즈다.
//
// ★ 표본이 적은 섹터는 **결론에 쓰지 않는다.** 2종목 섹터의 중앙값이 1위가 되면
//   화면은 그럴듯한데 조언으로는 틀린다(T67).

import type { ConsensusRow, FundamentalRow, ScreenRow, UniverseRow } from "./types";
import { median } from "./outcome";
import { sectorOf } from "./sector";

/** 섹터를 결론에 쓰기 위한 최소 종목 수. */
export const MIN_SECTOR_SAMPLE = 5;

export interface SectorEarnings {
  sector: string;
  /** 그 분기 재무가 있는 종목 수. */
  n: number;
  revenueYoy: number | null;
  opYoy: number | null;
  /** 게이트 통과(= 매출·이익 둘 다 가속) 종목 수. 이 시스템의 서프라이즈다. */
  accelerated: number;
  /** 통과 비율(0~1). 섹터 크기가 다르므로 비율로 비교해야 한다. */
  accelRate: number | null;
  /** 지난 분기 통과 비율. 없으면 null. */
  prevAccelRate: number | null;
  /** 통과 비율의 변화(%p). **이게 "서프라이즈가 늘었나"의 답이다.** */
  accelRateDelta: number | null;
  /** 지난 분기 대비 매출 성장률 중앙값 변화(%p) — 섹터 자체가 가속 중인가. */
  revenueYoyDelta: number | null;
  /** 지난 분기 대비 **영업이익** 성장률 중앙값 변화(%p). */
  opYoyDelta: number | null;
  /** 매출 성장률 사분위 범위(p25~p75) — 중앙값만 보면 섹터 안 편차를 못 본다. */
  revenueRange: [number, number] | null;
  /** 영업이익 성장률 사분위 범위. */
  opRange: [number, number] | null;
  /** 지난 분기 중앙값(전망 근거로 화면에 함께 보여준다). */
  prevRevenueYoy: number | null;
  prevOpYoy: number | null;
  /** 네이버의 다음 분기 종목 컨센서스를 섹터 중앙값으로 집계한 값. */
  nextRevenueYoy: number | null;
  nextOpYoy: number | null;
  nextRevenueQoq: number | null;
  nextOpQoq: number | null;
  nextCoverage: number;
  projectedAccelerated: number;
  projectedAccelRate: number | null;
  projectedAccelDelta: number | null;
}

/** 사분위. 중앙값 하나로는 "섹터 전체가 좋은가, 몇 종목만 좋은가"를 못 가른다. */
function quantile(values: number[], q: number): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return lo === hi ? sorted[lo] : sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

function range(values: number[]): [number, number] | null {
  const lo = quantile(values, 0.25);
  const hi = quantile(values, 0.75);
  return lo == null || hi == null ? null : [lo, hi];
}

function pick<T>(rows: T[], f: (r: T) => number | null | undefined): number[] {
  return rows
    .map(f)
    .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
}

/**
 * 섹터 × 분기 집계.
 *
 * ★ `screens`는 **그 분기의** 판정이어야 한다. 최신 행을 쓰면 지난 분기 통과율에
 *   이번 분기 판정이 섞인다(T40) — 비교 자체가 무의미해진다.
 */
export function aggregateSectors(
  universe: Map<string, UniverseRow>,
  funds: FundamentalRow[],
  screensByQuarter: Map<string, ScreenRow>,
  current: { year: number; quarter: number },
  previous: { year: number; quarter: number }
): SectorEarnings[] {
  const sectorFor = (code: string): string => sectorOf(universe.get(code));

  const bucket = new Map<
    string,
    { cur: FundamentalRow[]; prev: FundamentalRow[] }
  >();
  for (const f of funds) {
    const key = sectorFor(f.code);
    const b = bucket.get(key) ?? { cur: [], prev: [] };
    if (f.fiscal_year === current.year && f.fiscal_quarter === current.quarter) b.cur.push(f);
    else if (f.fiscal_year === previous.year && f.fiscal_quarter === previous.quarter) b.prev.push(f);
    bucket.set(key, b);
  }

  const passRate = (rows: FundamentalRow[], y: number, q: number): number | null => {
    // ★ 분모는 "그 분기에 판정이 있는 종목"이다. 재무만 있고 판정이 없는 종목을
    //   분모에 넣으면 통과율이 조용히 낮아진다.
    const judged = rows.filter((r) => screensByQuarter.has(`${r.code}|${y}|${q}`));
    if (judged.length === 0) return null;
    const passed = judged.filter(
      (r) => screensByQuarter.get(`${r.code}|${y}|${q}`)?.gate_passed === true
    ).length;
    return passed / judged.length;
  };

  const out: SectorEarnings[] = [];
  for (const [sector, b] of bucket) {
    if (b.cur.length === 0) continue;
    const revVals = pick(b.cur, (r) => r.revenue_yoy);
    const opVals = pick(b.cur, (r) => r.op_yoy);
    const rev = median(revVals);
    const op = median(opVals);
    const prevRev = median(pick(b.prev, (r) => r.revenue_yoy));
    const prevOp = median(pick(b.prev, (r) => r.op_yoy));
    const rate = passRate(b.cur, current.year, current.quarter);
    const prevRate = passRate(b.prev, previous.year, previous.quarter);
    const accelerated = b.cur.filter(
      (r) =>
        screensByQuarter.get(`${r.code}|${current.year}|${current.quarter}`)?.gate_passed === true
    ).length;

    out.push({
      sector,
      n: b.cur.length,
      revenueYoy: rev,
      opYoy: op,
      revenueRange: range(revVals),
      opRange: range(opVals),
      prevRevenueYoy: prevRev,
      prevOpYoy: prevOp,
      accelerated,
      accelRate: rate,
      prevAccelRate: prevRate,
      accelRateDelta: rate != null && prevRate != null ? (rate - prevRate) * 100 : null,
      revenueYoyDelta: rev != null && prevRev != null ? rev - prevRev : null,
      opYoyDelta: op != null && prevOp != null ? op - prevOp : null,
      nextRevenueYoy: null,
      nextOpYoy: null,
      nextRevenueQoq: null,
      nextOpQoq: null,
      nextCoverage: 0,
      projectedAccelerated: 0,
      projectedAccelRate: null,
      projectedAccelDelta: null,
    });
  }
  // ★★ 정렬 순서는 **영업이익 YoY → 매출 YoY → 가속 비율**이다(사용자 지정 2026-08-22).
  //   매출 우선에서 바꿨다 — 이 시스템이 찾는 것은 '많이 판 섹터'가 아니라
  //   '이익이 빨라진 섹터'다. 결측은 항상 맨 뒤로 보낸다(-Infinity).
  return out.sort(
    (a, b) =>
      ((b.opYoy ?? -Infinity) - (a.opYoy ?? -Infinity)) ||
      ((b.revenueYoy ?? -Infinity) - (a.revenueYoy ?? -Infinity)) ||
      ((b.accelRate ?? -Infinity) - (a.accelRate ?? -Infinity))
  );
}

function safeGrowth(current: number | null, base: number | null): number | null {
  return current != null && base != null && base > 0 ? ((current / base) - 1) * 100 : null;
}

/**
 * 종목별 다음 분기 컨센서스를 같은 분기 전년 실적·이번 분기 실적과 대조해 섹터 전망을 붙인다.
 * 영업이익 부호 전환은 성장률로 만들지 않는다. `None`과 0을 섞지 않는 동일 원칙이다.
 */
export function withNextQuarterConsensus(
  rows: SectorEarnings[],
  universe: Map<string, UniverseRow>,
  currentFunds: FundamentalRow[],
  yearAgoNextFunds: FundamentalRow[],
  nextConsensus: Map<string, ConsensusRow>
): SectorEarnings[] {
  const current = new Map(currentFunds.map((row) => [row.code, row]));
  const yearAgo = new Map(yearAgoNextFunds.map((row) => [row.code, row]));
  const grouped = new Map<string, Array<{
    revenueYoy: number | null; opYoy: number | null;
    revenueQoq: number | null; opQoq: number | null;
    accelerated: boolean | null;
  }>>();

  for (const [code, consensus] of nextConsensus) {
    const cur = current.get(code);
    const base = yearAgo.get(code);
    if (!cur || !base) continue;
    const revenueYoy = safeGrowth(consensus.revenue_est, base.revenue);
    const opYoy = safeGrowth(consensus.op_est, base.op);
    const revenueQoq = safeGrowth(consensus.revenue_est, cur.revenue);
    const opQoq = safeGrowth(consensus.op_est, cur.op);
    const accelerated = revenueYoy != null && opYoy != null &&
      cur.revenue_yoy != null && cur.op_yoy != null
      ? revenueYoy > cur.revenue_yoy && opYoy > cur.op_yoy
      : null;
    const sector = sectorOf(universe.get(code));
    const bucket = grouped.get(sector) ?? [];
    bucket.push({ revenueYoy, opYoy, revenueQoq, opQoq, accelerated });
    grouped.set(sector, bucket);
  }

  return rows.map((row) => {
    const bucket = grouped.get(row.sector) ?? [];
    const judged = bucket.filter((item) => item.accelerated != null);
    const projectedAccelerated = judged.filter((item) => item.accelerated).length;
    const projectedAccelRate = judged.length ? projectedAccelerated / judged.length : null;
    return {
      ...row,
      nextRevenueYoy: median(pick(bucket, (item) => item.revenueYoy)),
      nextOpYoy: median(pick(bucket, (item) => item.opYoy)),
      nextRevenueQoq: median(pick(bucket, (item) => item.revenueQoq)),
      nextOpQoq: median(pick(bucket, (item) => item.opQoq)),
      nextCoverage: bucket.length,
      projectedAccelerated,
      projectedAccelRate,
      projectedAccelDelta: projectedAccelRate != null && row.accelRate != null
        ? (projectedAccelRate - row.accelRate) * 100
        : null,
    };
  });
}

/** 결론에 쓸 수 있는 섹터만. */
export function usableSectors(rows: SectorEarnings[]): SectorEarnings[] {
  return rows.filter((r) => r.n >= MIN_SECTOR_SAMPLE);
}

// ═══════════════════════════════════════════════════════════════════
// 다음 분기 전망
// ═══════════════════════════════════════════════════════════════════
export type Momentum = "가속" | "유지" | "둔화" | "판정불가";

export interface SectorOutlook {
  sector: string;
  momentum: Momentum;
  /** 왜 그렇게 봤는지 — 숫자 근거. */
  basis: string;
  /** 다음 분기에 무엇을 확인할 것인가. */
  watch: string;
}

/**
 * 다음 분기 전망 — **추세의 방향**만 말한다.
 *
 * ★ 예측 모델이 아니다. 두 분기의 실적 추세와 통과율 변화가 같은 방향을 가리키면
 *   '가속', 반대면 '둔화', 한쪽이 없으면 '판정불가'다.
 *   **한 분기 데이터로 다음 분기를 맞히려 하지 않는다** — 방향만 짚는다.
 */
export function outlook(rows: SectorEarnings[]): SectorOutlook[] {
  return usableSectors(rows)
    .map((r) => {
      const hasConsensus = r.nextCoverage >= MIN_SECTOR_SAMPLE &&
        r.nextRevenueYoy != null && r.nextOpYoy != null;
      const revUp = hasConsensus && r.revenueYoy != null
        ? (r.nextRevenueYoy as number) - r.revenueYoy
        : r.revenueYoyDelta;
      const opUp = hasConsensus && r.opYoy != null
        ? (r.nextOpYoy as number) - r.opYoy
        : r.opYoyDelta;
      const rateUp = hasConsensus ? r.projectedAccelDelta : r.accelRateDelta;
      let momentum: Momentum = "판정불가";
      let basis: string;

      if (revUp == null || opUp == null || rateUp == null) {
        basis = "지난 분기 비교 데이터가 부족해 방향을 판단하지 않았다.";
      } else if (revUp > 0 && opUp > 0 && rateUp > 0) {
        momentum = "가속";
        basis = `${hasConsensus ? "네이버 다음 분기 컨센서스" : "직전 추세"}: 매출 ${revUp >= 0 ? "+" : ""}${revUp.toFixed(1)}%p, ` +
          `영업이익 ${opUp >= 0 ? "+" : ""}${opUp.toFixed(1)}%p, 가속 종목 비율 ${rateUp >= 0 ? "+" : ""}${rateUp.toFixed(0)}%p.`;
      } else if (revUp < 0 && opUp < 0 && rateUp < 0) {
        momentum = "둔화";
        basis = `${hasConsensus ? "네이버 다음 분기 컨센서스" : "직전 추세"}: 매출 ${revUp.toFixed(1)}%p, ` +
          `영업이익 ${opUp.toFixed(1)}%p, 가속 종목 비율 ${rateUp.toFixed(0)}%p.`;
      } else {
        momentum = "유지";
        basis = `${hasConsensus ? "네이버 다음 분기 컨센서스" : "직전 추세"}: 매출·영업이익·가속 비율의 방향이 엇갈린다.`;
      }

      const watch =
        momentum === "가속"
          ? "다음 분기에도 가속 종목 비율이 유지되는지 — 꺾이면 이번이 정점이다."
          : momentum === "둔화"
            ? "기저효과가 빠지는 구간인지 확인. 절대 매출이 늘고 있다면 성장률만 낮아진 것이다."
            : "매출과 이익 중 어느 쪽이 먼저 꺾이는지 — 이익이 먼저면 마진 압박이다.";

      return { sector: r.sector, momentum, basis, watch };
    })
    .sort((a, b) => {
      const rank: Record<Momentum, number> = { 가속: 0, 유지: 1, 둔화: 2, 판정불가: 3 };
      return rank[a.momentum] - rank[b.momentum];
    });
}

/** 서프라이즈(가속 종목)가 지난 분기보다 늘어난 섹터 상위 N. */
export function risingSectors(rows: SectorEarnings[], limit = 5): SectorEarnings[] {
  return usableSectors(rows)
    .filter((r) => r.accelRateDelta != null)
    .sort((a, b) => (b.accelRateDelta as number) - (a.accelRateDelta as number))
    .slice(0, limit);
}

/** 네이버 컨센서스상 다음 분기에 가속 종목 비율이 늘어나는 섹터. */
export function nextRisingSectors(rows: SectorEarnings[], limit = 5): SectorEarnings[] {
  return usableSectors(rows)
    .filter((r) => r.nextCoverage >= MIN_SECTOR_SAMPLE && (r.projectedAccelDelta ?? 0) > 0)
    .sort((a, b) => (b.projectedAccelDelta as number) - (a.projectedAccelDelta as number))
    .slice(0, limit);
}
