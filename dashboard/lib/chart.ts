// PRD Ref: §9.1-3
//
// ★ 이 변환 함수는 **차트 컴포넌트 파일에 두면 안 된다.**
//   `QuarterlyChart.tsx`는 `"use client"`라 서버 컴포넌트가 그 파일에서
//   컴포넌트가 아닌 export를 가져오면 런타임에 `is not a function`으로 죽는다.
//   빌드와 타입 검사는 통과한다 — 실제로 페이지를 열어봐야 잡힌다(T41).
import type { FundamentalRow } from "./types";
import { qIndex } from "./format";

export interface ChartPoint {
  label: string;
  revenue: number | null;
  op: number | null;
  /** ★ 이 화면의 주인공. 매출 성장률(YoY, %). */
  revenueYoy: number | null;
  /** ★★ 가장 중요한 라인. 영업이익 성장률(YoY, %). */
  opYoy: number | null;
  /** 부호 전환 구간 라벨('흑전'·'적전'…). %가 없을 때 대신 보여준다. */
  opStatusLabel: string | null;
  ttmRevenue: number | null;
  /** 분기말 종가(원). 없으면 null — 주가 라인만 끊긴다. */
  close: number | null;
  isEstimate: boolean;
  /** 아직 실적이 발표되지 않은 진행 중 분기. 주가만 있고 막대가 없다. */
  isCurrentQuarter: boolean;
}

/** 상세화면 차트의 기본 분기 수. 사용자 요청으로 8 → 9. */
export const CHART_QUARTERS = 9;

function qLabel(year: number, quarter: number): string {
  return `${String(year).slice(-2)}.${quarter}Q`;
}

export function toChartPoints(
  rows: FundamentalRow[],
  count = CHART_QUARTERS,
  /** 분기말 종가. 키는 `qIndex(연, 분기)`. 없으면 주가 라인이 그려지지 않는다. */
  quarterPrices?: Map<number, number>,
  /** 오늘 종가. 진행 중 분기 점을 여기로 덮어써 라인이 **현재까지** 닿게 한다. */
  latestClose?: number | null
): ChartPoint[] {
  const points: ChartPoint[] = rows.slice(-count).map((r) => ({
    label: qLabel(r.fiscal_year, r.fiscal_quarter),
    // 억원 단위로 그린다. 원 단위 그대로면 축 라벨이 읽히지 않는다.
    revenue: r.revenue == null ? null : r.revenue / 1e8,
    op: r.op == null ? null : r.op / 1e8,
    // ★ 부호가 바뀌는 구간은 애초에 null로 저장돼 있다(T25). 여기서 만들어내지 않는다.
    revenueYoy: r.revenue_yoy,
    opYoy: r.op_yoy,
    opStatusLabel: r.op_status_label,
    ttmRevenue: r.ttm_revenue == null ? null : r.ttm_revenue / 1e8,
    close: quarterPrices?.get(qIndex(r.fiscal_year, r.fiscal_quarter)) ?? null,
    isEstimate: Boolean(r.is_estimate),
    isCurrentQuarter: false,
  }));

  // ★ 주가는 **현재까지** 그린다.
  //   실적 행은 마지막 발표 분기에서 끝나지만 주가는 오늘도 있다. 실적 행만 따르면
  //   라인이 몇 달 전에서 잘려 "그 뒤로 주가가 어떻게 됐나"를 볼 수 없다 —
  //   실적과 주가의 시차를 보는 게 이 차트의 목적이라 거기서 끊기면 안 된다.
  const lastFund = rows[rows.length - 1];
  if (!lastFund) return points;
  const lastIndex = qIndex(lastFund.fiscal_year, lastFund.fiscal_quarter);

  const laterQuarters = [...(quarterPrices?.keys() ?? [])]
    .filter((k) => k > lastIndex)
    .sort((a, b) => a - b);

  for (const key of laterQuarters) {
    const year = Math.floor(key / 4);
    const quarter = (key % 4) + 1;
    points.push({
      label: qLabel(year, quarter),
      revenue: null, op: null, revenueYoy: null, opYoy: null,
      opStatusLabel: null, ttmRevenue: null,
      close: quarterPrices?.get(key) ?? null,
      isEstimate: false,
      // 아직 실적이 안 나온 분기다 — 막대가 없는 게 결측이 아니라 '미발표'임을 밝힌다.
      isCurrentQuarter: true,
    });
  }

  // 가장 마지막 점은 오늘 종가로 덮는다. 분기말 종가는 그 분기 마지막 '거래일'이라
  // 진행 중 분기에서는 며칠 뒤처져 있다.
  const tail = points[points.length - 1];
  if (tail && latestClose != null && tail.isCurrentQuarter) {
    tail.close = latestClose;
  }
  return points;
}

/**
 * 성장률 라인이 실제로 값을 가진 분기가 몇 개인가.
 *
 * ★ 0이면 라인이 아예 안 그려지는데 축은 그대로 남아 "0% 근처에 붙어 있다"로
 *   잘못 읽힌다. 화면에서 그 사실을 밝히기 위해 세어 둔다.
 */
export function measuredCount(points: ChartPoint[], key: "revenueYoy" | "opYoy"): number {
  return points.filter((p) => p[key] != null).length;
}
