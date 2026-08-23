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
// 차트 해설 — **모양이 무엇을 뜻하는가** (사용자 지정 2026-08-23)
// ═══════════════════════════════════════════════════════════════════
//
// ★★ "영업이익 성장률이 빨라졌다"는 **차트를 읽으면 누구나 아는 사실**이다.
//   화면이 보태야 하는 것은 그 다음이다 — **왜 그 모양이 중요한가.**
//   같은 '가속'이라도 이익이 매출보다 빨라진 것과 그 반대는 뜻이 완전히 다르고,
//   높은 기저 위의 가속과 낮은 기저 위의 가속도 다르다.

export interface ChartVerdict {
  /** 한 줄 결론 — **모양의 이름**. */
  headline: string;
  /** 그 근거가 된 실제 숫자. 문장만 있으면 검증할 수 없다. */
  evidence: string;
  /** ★ 이 모양이 **무엇을 뜻하는가**. 이 화면이 보태는 값의 전부다. */
  meaning: string;
  /** 그래서 다음에 무엇을 확인해야 하는가. */
  watch: string;
  /** 강조 색 — 가속이면 노랑(주인공 선과 같은 색), 둔화면 회색. */
  tone: "accel" | "flat" | "slow" | "unknown";
}

function fmtYoy(v: number | null): string {
  return v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

/**
 * 9분기 차트에서 **투자 포인트**를 뽑는다.
 *
 * ★ 규칙 기반이다 — LLM을 쓰지 않는다. 차트에 실제로 그려진 숫자에서만 나온다.
 * ★ 보는 것은 **영업이익 YoY**가 중심이고, 매출 YoY와 OPM을 **대조**해 뜻을 만든다.
 * ★ 부호 전환 구간(흑전·적전)은 opYoy가 null이다(T25). 0으로 채워 기울기를 만들면
 *   흑자전환이 '급감'으로 그려진다 — 측정된 점만 쓴다.
 */
export function chartVerdict(points: ChartPoint[]): ChartVerdict {
  const measured = points.filter((p) => p.opYoy != null);
  const last = measured[measured.length - 1];
  const prev = measured[measured.length - 2];

  // 최근 발표 분기가 부호 전환이면 %가 없다 — 결측이 아니라 가장 강한 형태다.
  const lastReported = [...points].reverse().find((p) => !p.isCurrentQuarter && p.op != null);
  if (lastReported && lastReported.opYoy == null && lastReported.opStatusLabel) {
    const label = lastReported.opStatusLabel;
    const good = label === "흑전" || label === "적자축소";
    return {
      headline: `영업이익이 **${label}**했다 — 성장률(%)로는 잴 수 없는 구간이다.`,
      evidence: `${lastReported.label} 영업이익 ${
        lastReported.op == null ? "—" : `${lastReported.op.toFixed(0)}억`
      }`,
      meaning: good
        ? "적자에서 흑자로 넘어오는 구간은 **성장률이 가장 큰 폭으로 왜곡되는 자리**다. " +
          "전년이 적자면 분모가 음수라 몇 %가 늘었다는 말 자체가 성립하지 않는다. " +
          "대신 **흑자가 몇 분기 이어지는가**가 이 회사의 체질이 실제로 바뀌었는지를 가른다 — " +
          "한 분기짜리 흑전은 일회성 이익이나 원가 환입으로도 만들어진다."
        : "이익이 적자로 돌아섰다. 성장률로는 잴 수 없고, **적자의 원인이 구조적인지 " +
          "일시적인지**가 전부다 — 매출이 함께 줄었다면 수요 문제이고, 매출은 유지되는데 " +
          "이익만 무너졌다면 원가·판가 문제다.",
      watch: "다음 분기에도 흑자가 이어지는지, 그리고 매출이 함께 늘고 있는지를 같이 봐라.",
      tone: good ? "accel" : "slow",
    };
  }

  if (!last || !prev) {
    return {
      headline: "영업이익 YoY를 두 분기 이상 재지 못해 **가속 여부를 판정할 수 없다.**",
      evidence: `측정된 분기 ${measured.length}개`,
      meaning:
        "**판정 불가는 '가속 없음'이 아니다.** 부호 전환이 잦았거나 상장 이력이 짧아 " +
        "비교 대상이 없는 상태다. 이 구간에서는 성장률 대신 **절대 금액의 궤적**을 봐야 한다.",
      watch: "아래 분기 히스토리에서 매출·영업이익의 절대금액이 늘고 있는지 직접 확인하라.",
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
  // 이익이 매출보다 빠른가 — 마진이 벌어지는지 좁아지는지의 신호다.
  const leverage = revDelta != null ? delta - revDelta : null;

  // 전년 동기가 비정상적으로 낮았는가(기저효과의 육안 판정).
  const yearAgo = measured[measured.length - 5] ?? null;
  const lowBase =
    yearAgo?.opYoy != null && last.opYoy != null && yearAgo.opYoy < -20 && last.opYoy > 50;

  const base = {
    evidence:
      `${prev.label} ${fmtYoy(prev.opYoy)} → ${last.label} ${fmtYoy(last.opYoy)} ` +
      `(${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%p)` +
      (revDelta != null
        ? ` · 매출 성장률 ${revDelta >= 0 ? "+" : ""}${revDelta.toFixed(1)}%p`
        : ""),
  };

  if (delta > 0) {
    // ── 가속 구간 — 무엇 때문의 가속인가가 관건이다 ──
    let meaning: string;
    if (leverage != null && leverage > 5) {
      meaning =
        "**이익이 매출보다 빠르게 빨라졌다.** 고정비가 그대로인데 매출이 늘면 늘어난 " +
        "매출의 상당 부분이 그대로 이익이 된다(영업 레버리지). 이 모양은 **마진이 " +
        "구조적으로 벌어지는 구간**에서 나오고, 이 시스템이 찾는 형태가 정확히 이것이다. " +
        "다만 판가 인상이나 일회성 원가 환입으로도 같은 모양이 나오므로 **원인이 " +
        "물량인지 단가인지**를 아래 LLM 분석에서 확인해야 한다.";
    } else if (leverage != null && leverage < -5) {
      meaning =
        "**이익보다 매출이 더 빠르게 빨라졌다.** 많이 팔았는데 이익은 그만큼 못 따라온 " +
        "모양이라 **마진이 얇아지는 성장**일 수 있다 — 할인 판매, 원가 상승, 저마진 " +
        "제품 비중 확대가 대표적인 원인이다. 매출 성장에만 눈이 가면 이 신호를 놓친다.";
    } else {
      meaning =
        "매출과 이익이 **비슷한 속도로** 빨라졌다. 마진 구조가 그대로인 채 규모가 " +
        "커지는 모양이라, 성장이 이어지는 한 이익도 함께 늘지만 **레버리지에서 오는 " +
        "추가 이익은 기대하기 어렵다.**";
    }
    if (lowBase) {
      meaning +=
        " ⚠ 다만 **전년 동기가 크게 부진했다** — 낮은 기저 위의 성장률은 실제보다 " +
        "커 보인다. 절대 금액이 함께 늘고 있는지 반드시 확인하라.";
    }
    return {
      headline:
        streak >= 2
          ? `영업이익 성장률이 **${streak}분기 연속 빨라지고 있다.**`
          : "영업이익 성장률이 **전분기보다 빨라졌다** — 가속이 시작된 구간이다.",
      ...base,
      meaning,
      watch:
        streak >= 2
          ? "연속 가속은 **일회성으로는 만들기 어려운 모양**이다. 다음 분기에도 " +
            "기울기가 유지되는지가 핵심 — 꺾이면 이번 분기가 정점이었다는 뜻이다."
          : "한 분기 가속은 일회성 요인으로도 만들어진다. **다음 분기에 한 번 더** " +
            "가속해야 추세로 인정할 수 있다.",
      tone: "accel",
    };
  }

  if (Math.abs(delta) < 1) {
    return {
      headline: "영업이익 성장률이 **전분기와 거의 같다** — 가속도 둔화도 아니다.",
      ...base,
      meaning:
        "성장률이 **평평하다는 것은 성장이 멈췄다는 뜻이 아니다.** 같은 속도로 " +
        `계속 크고 있다는 뜻이다(현재 ${fmtYoy(last.opYoy)}). 이 시스템은 성장률의 ` +
        "**변화**를 보므로 이 구간은 점수를 거의 주지 않지만, 성장률 수준 자체가 " +
        "높다면 사업은 멀쩡한 상태다 — **낮은 점수와 나쁜 회사를 혼동하지 마라.**",
      watch: "성장률의 절대 수준이 높은지 낮은지를 함께 봐라. 높은 수준에서의 유지는 둔화와 다르다.",
      tone: "flat",
    };
  }

  return {
    headline: "영업이익 성장률이 **전분기보다 낮아졌다** — 성장은 하되 속도가 줄었다.",
    ...base,
    meaning:
      "**성장률이 낮아진 것이지 이익이 줄어든 것이 아니다.** 성장률은 전년 동기 대비라 " +
      "**작년이 좋았으면 올해가 멀쩡해도 숫자가 내려간다**(기저 효과). 그래서 이 모양은 " +
      "두 가지를 뜻할 수 있다 — 실제로 사업이 꺾였거나, 비교 대상이 높아졌을 뿐이거나. " +
      "둘을 가르는 방법은 하나뿐이다: **절대 금액을 보는 것.**" +
      (last.opYoy != null && last.opYoy > 0
        ? ` 현재 성장률은 여전히 ${fmtYoy(last.opYoy)}로 플러스다.`
        : " 현재 성장률이 마이너스라 이익 자체가 전년보다 줄었다."),
    watch:
      "아래 분기 히스토리에서 **영업이익 절대금액**이 늘고 있는지 확인하라. " +
      "금액이 늘고 있다면 성장률만 낮아진 것이다.",
    tone: "slow",
  };
}
