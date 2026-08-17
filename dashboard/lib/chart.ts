// PRD Ref: §9.1-3
//
// ★ 이 변환 함수는 **차트 컴포넌트 파일에 두면 안 된다.**
//   `QuarterlyChart.tsx`는 `"use client"`라 서버 컴포넌트가 그 파일에서
//   컴포넌트가 아닌 export를 가져오면 런타임에 `is not a function`으로 죽는다.
//   빌드와 타입 검사는 통과한다 — 실제로 페이지를 열어봐야 잡힌다.
import type { FundamentalRow } from "./types";

export interface ChartPoint {
  label: string;
  revenue: number | null;
  op: number | null;
  revenueYoy: number | null;
  ttmRevenue: number | null;
  isEstimate: boolean;
}

export function toChartPoints(rows: FundamentalRow[], count = 8): ChartPoint[] {
  return rows.slice(-count).map((r) => ({
    label: `${String(r.fiscal_year).slice(-2)}.${r.fiscal_quarter}Q`,
    // 억원 단위로 그린다. 원 단위 그대로면 축 라벨이 읽히지 않는다.
    revenue: r.revenue == null ? null : r.revenue / 1e8,
    op: r.op == null ? null : r.op / 1e8,
    // ★ 부호가 바뀌는 구간은 애초에 null로 저장돼 있다(T25). 여기서 만들어내지 않는다.
    revenueYoy: r.revenue_yoy,
    ttmRevenue: r.ttm_revenue == null ? null : r.ttm_revenue / 1e8,
    isEstimate: Boolean(r.is_estimate),
  }));
}
