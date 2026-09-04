// PRD Ref: §5, §7, §9 — 화면 분류와 LLM 대상의 단일 정의

export type GrowthCategory =
  | "growth"
  | "revenue_slow_op_accel"
  | "turnaround"
  | "other";

export interface GrowthCategoryInput {
  gate_passed?: boolean | null;
  turnaround?: boolean | null;
  gate_detail?: Record<string, unknown> | null;
}

/**
 * 화면의 다섯 선택 탭과 LLM 대상이 같은 정의를 쓰게 한다.
 * 흑전은 영업이익 YoY 비율을 계산하지 않으므로 성장 가속과 겹치지 않게 먼저 분리한다.
 */
export function growthCategory(row: GrowthCategoryInput): GrowthCategory {
  if (row.turnaround === true) return "turnaround";
  if (row.gate_passed === true) return "growth";
  if (row.gate_detail?.g1 === false && row.gate_detail?.g2 === true) {
    return "revenue_slow_op_accel";
  }
  return "other";
}

