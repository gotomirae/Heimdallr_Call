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

/**
 * 차트 계열 색 — **단일 출처**.
 *
 * ★ 차트 컴포넌트와 그 아래 설명 글이 서로 다른 파일에 있다. 색을 각자 적어 두면
 *   "초록 실선은 매출…"이라고 써 놓고 화면은 노란 선인 상태가 되는데,
 *   **둘 다 정상으로 보여서** 아무도 눈치채지 못한다.
 * ★ 이 상수는 **`lib/`에 있어야 한다.** `QuarterlyChart.tsx`는 "use client"라
 *   서버 컴포넌트가 그 파일에서 비컴포넌트 export를 가져오면 빌드는 통과하고
 *   런타임에 500이 난다(T41).
 */
export const SERIES_COLOR = {
  /** 영업이익 YoY — 노란 실선. 이 차트의 주인공. */
  OP_COLOR: "#facc15",
  OP_LABEL: "#fde047",
  /** 매출 YoY — 녹색 실선. */
  REVENUE_COLOR: "#34d399",
  REVENUE_LABEL: "#6ee7b7",
  /** 주가 — 빨간 점선. 현재 주가까지 이어 그린다. */
  PRICE_COLOR: "#f87171",
  /** TTM 매출 — 분홍 점선. */
  TTM_COLOR: "#f9a8d4",
  /** 축·눈금 — 계열 색이 아니다. 계열과 헷갈리지 않게 따로 둔다. */
  AXIS_COLOR: "#cbd5e1",
} as const;

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

// ═══════════════════════════════════════════════════════════════════
// 차트 한 줄 해설 — **영업이익 YoY 가속이 핵심 포인트다** (사용자 지정 2026-08-22)
// ═══════════════════════════════════════════════════════════════════

export interface ChartVerdict {
  /** 한 줄 결론. 차트 바로 아래에 굵게 놓는다. */
  headline: string;
  /** 그 근거가 된 실제 숫자. 문장만 있으면 검증할 수 없다. */
  evidence: string;
  /** 그래서 무엇을 보라는 것인가. */
  action: string;
  /** 강조 색 — 가속이면 노랑(주인공 선과 같은 색), 둔화면 회색. */
  tone: "accel" | "flat" | "slow" | "unknown";
}

function fmtYoy(v: number | null): string {
  return v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

/**
 * 9분기 차트에서 **투자 포인트 한 줄**을 뽑는다.
 *
 * ★ 규칙 기반이다 — LLM을 쓰지 않는다. 이 문장은 차트에 실제로 그려진 숫자에서
 *   직접 나와야 하고, 값이 없으면 없다고 말해야 한다.
 * ★ 보는 것은 **영업이익 YoY 하나**다. 매출·TTM·주가를 한 문장에 다 담으면
 *   무엇이 핵심인지가 사라진다 — 나머지는 아래 표에서 본다.
 * ★ 부호 전환 구간(흑전·적전)은 opYoy가 null이다(T25). 그 구간을 0으로 채워
 *   기울기를 만들면 흑자전환이 '급감'으로 그려진다 — 측정된 점만 쓴다.
 */
export function chartVerdict(points: ChartPoint[]): ChartVerdict {
  const measured = points.filter((p) => p.opYoy != null);
  const last = measured[measured.length - 1];
  const prev = measured[measured.length - 2];

  // 최근 발표 분기가 흑자전환이면 %가 없다 — 그건 결측이 아니라 가장 강한 형태다.
  const lastReported = [...points].reverse().find((p) => !p.isCurrentQuarter && p.op != null);
  if (lastReported && lastReported.opYoy == null && lastReported.opStatusLabel) {
    return {
      headline: `영업이익이 ${lastReported.opStatusLabel}했다 — 성장률(%)로는 잴 수 없는 구간이다.`,
      evidence: `${lastReported.label} 영업이익 ${lastReported.op == null ? "—" : lastReported.op.toFixed(0) + "억"}`,
      action: "부호가 바뀌는 구간이라 %를 만들지 않는다. 다음 분기에 흑자가 이어지는지가 핵심이다.",
      tone: "accel",
    };
  }

  if (!last || !prev) {
    return {
      headline: "영업이익 YoY를 두 분기 이상 재지 못해 가속 여부를 판정할 수 없다.",
      evidence: `측정된 분기 ${measured.length}개`,
      action: "판정 불가는 '가속 없음'이 아니다. 분기가 쌓이면 자동으로 채워진다.",
      tone: "unknown",
    };
  }

  const delta = last.opYoy! - prev.opYoy!;

  // 연속 가속 분기 수 — "이번만인가, 계속인가"가 지속성의 유일한 관측 가능한 단서다.
  let streak = 0;
  for (let i = measured.length - 1; i > 0; i--) {
    if (measured[i].opYoy! > measured[i - 1].opYoy!) streak++;
    else break;
  }

  const revDelta =
    last.revenueYoy != null && prev.revenueYoy != null
      ? last.revenueYoy - prev.revenueYoy
      : null;

  if (delta > 0) {
    return {
      headline:
        streak >= 2
          ? `영업이익 성장률이 **${streak}분기 연속 빨라지고 있다.**`
          : "영업이익 성장률이 **전분기보다 빨라졌다** — 가속이 시작된 구간이다.",
      evidence:
        `${prev.label} ${fmtYoy(prev.opYoy)} → ${last.label} ${fmtYoy(last.opYoy)} ` +
        `(${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%p)` +
        (revDelta != null
          ? ` · 매출 성장률 ${revDelta >= 0 ? "+" : ""}${revDelta.toFixed(1)}%p`
          : ""),
      action:
        revDelta != null && delta > revDelta
          ? "이익이 매출보다 빠르게 빨라졌다 — 마진이 벌어지는 구간이고, 이게 이 화면이 찾는 모양이다."
          : "노란 선의 기울기가 다음 분기에도 유지되는지가 전부다. 꺾이면 이번 분기가 정점이다.",
      tone: "accel",
    };
  }

  if (Math.abs(delta) < 1) {
    return {
      headline: "영업이익 성장률이 **전분기와 비슷하다** — 가속도 둔화도 아니다.",
      evidence: `${prev.label} ${fmtYoy(prev.opYoy)} → ${last.label} ${fmtYoy(last.opYoy)}`,
      action: "성장률 수준 자체가 높은지를 함께 봐라. 높은 수준에서의 유지는 둔화와 다르다.",
      tone: "flat",
    };
  }

  return {
    headline: "영업이익 성장률이 **전분기보다 낮아졌다** — 성장은 하되 속도가 줄었다.",
    evidence:
      `${prev.label} ${fmtYoy(prev.opYoy)} → ${last.label} ${fmtYoy(last.opYoy)} ` +
      `(${delta.toFixed(1)}%p)`,
    action:
      "성장률이 낮아진 것이지 이익이 준 것은 아니다. 전년 기저가 높았던 것인지 " +
      "실제로 꺾인 것인지 아래 분기 히스토리의 절대금액으로 확인하라.",
    tone: "slow",
  };
}
