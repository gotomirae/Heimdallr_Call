// PRD Ref: §6 (스키마) · §4 (스코어·PRI)

export type Grade = "★" | "○" | "△" | "·" | "✕";

/** 발송 대상 등급. △·는 대시보드에만 남는다(constants.NOTIFY_GRADES와 같아야 한다). */
export const NOTIFY_GRADES: Grade[] = ["★", "○"];

export const GRADE_MEANING: Record<Grade, string> = {
  "★": "고스코어 · 미반영",
  "○": "고스코어 · 부분반영",
  "△": "고스코어 · 선반영 (조정 시 담을 구간)",
  "·": "중간",
  "✕": "저스코어 · 선반영",
};

export const GRADE_COLOR: Record<Grade, string> = {
  "★": "#f59e0b",
  "○": "#10b981",
  "△": "#6366f1",
  "·": "#94a3b8",
  "✕": "#ef4444",
};

export interface UniverseRow {
  code: string;
  name: string | null;
  board: string | null;
  industry: string | null;
  products: string | null;
  market_cap_krw: number | null;
  sector_caveat: string | null;
  is_excluded: boolean | null;
  exclude_reason: string | null;
}

export interface FundamentalRow {
  code: string;
  fiscal_year: number;
  fiscal_quarter: number;
  revenue: number | null;
  op: number | null;
  np: number | null;
  revenue_yoy: number | null;
  op_yoy: number | null;
  op_status_label: string | null;
  opm: number | null;
  opm_yoy_delta: number | null;
  revenue_qoq: number | null;
  eps: number | null;
  eps_yoy: number | null;
  fcf: number | null;
  ttm_revenue: number | null;
  ttm_opm: number | null;
  ttm_opm_delta: number | null;
  is_estimate: boolean | null;
  source: string | null;
}

export interface ScreenRow {
  code: string;
  fiscal_year: number;
  fiscal_quarter: number;
  gate_passed: boolean | null;
  gate_detail: Record<string, unknown> | null;
  base_effect_warning: boolean | null;
  turnaround: boolean | null;
  score_flash: number | null;
  score_a: number | null;
  score_b: number | null;
  score_c: number | null;
  score_d: number | null;
  has_consensus: boolean | null;
  pri: number | null;
  pri_detail: PriDetail | null;
  grade: Grade | null;
  raw_a1?: number | null; raw_a2?: number | null;
  raw_a3?: number | null; raw_a4?: number | null;
  raw_b1?: number | null; raw_b2?: number | null;
  raw_b3?: number | null; raw_b4?: number | null;
  raw_c1?: number | null; raw_c2?: number | null;
  raw_d1?: number | null; raw_d2?: number | null;
  raw_d3?: number | null; raw_d4?: number | null;
}

export interface PriDetail {
  parts?: Record<string, number | null>;
  raw_sum?: number;
  denominator?: number;
  excluded?: string[];
}

export interface PriceRow {
  code: string;
  snap_date: string;
  close: number | null;
  chg_pct: number | null;
  high_52w: number | null;
  low_52w: number | null;
  pos_52w: number | null;
  rel_ret_3m: number | null;
  /** 최근 5**거래일** 상승률(%). 수집 전에는 null이다 — 0으로 채우지 않는다. */
  ret_5d: number | null;
  market_cap_krw: number | null;
  per: number | null;
  pbr: number | null;
  per_pctile_3y: number | null;
  avg_value_20d: number | null;
}

/** 분기말 종가 — 9분기 차트에 주가를 겹쳐 그린다. **달력 분기** 기준이다. */
export interface QuarterPriceRow {
  code: string;
  fiscal_year: number;
  fiscal_quarter: number;
  close: number | null;
  trade_date: string | null;
}

/** DART 공시. `rcept_no`가 원문 링크의 유일한 열쇠다. */
export interface DisclosureRow {
  rcept_no: string;
  code: string;
  report_nm: string | null;
  doc_type: string | null;
  fiscal_year: number | null;
  fiscal_quarter: number | null;
  disclosed_at: string | null;
}

export interface ConsensusRow {
  code: string;
  fiscal_year: number;
  fiscal_quarter: number;
  n_estimates: number | null;
  revenue_est: number | null;
  op_est: number | null;
  np_est: number | null;
}

/** 스코어 축 정의 — 텔레그램 템플릿(`src/notify/templates.py`)과 같은 이름을 쓴다. */
export const AXES = [
  { key: "a", label: "성장 가속", max: 35 },
  { key: "b", label: "수익성", max: 32 },
  { key: "c", label: "서프라이즈", max: 15 },
  { key: "d", label: "회계 품질", max: 18 },
] as const;

export const AXIS_ITEMS: Record<string, { key: string; label: string; max: number }[]> = {
  a: [
    { key: "raw_a1", label: "매출 YoY 델타", max: 14 },
    { key: "raw_a2", label: "영업이익 YoY 델타", max: 10 },
    { key: "raw_a3", label: "TTM 매출 추세", max: 6 },
    { key: "raw_a4", label: "2분기 연속 가속", max: 5 },
  ],
  b: [
    { key: "raw_b1", label: "OPM YoY", max: 14 },
    { key: "raw_b2", label: "TTM OPM 추세", max: 7 },
    { key: "raw_b3", label: "영업레버리지", max: 6 },
    { key: "raw_b4", label: "업종 대비 OPM", max: 5 },
  ],
  c: [
    { key: "raw_c1", label: "영업이익 서프라이즈", max: 9 },
    { key: "raw_c2", label: "매출 서프라이즈", max: 6 },
  ],
  d: [
    { key: "raw_d1", label: "현금흐름 정합성", max: 6 },
    { key: "raw_d2", label: "주식수 희석", max: 4 },
    { key: "raw_d3", label: "운전자본", max: 4 },
    { key: "raw_d4", label: "유동성", max: 4 },
  ],
};

/** 축이 통째로 미측정일 때의 이유. **0점이 아니라 분모 제외**임을 밝힌다(ADR 2). */
export const AXIS_MISSING_REASON: Record<string, string> = {
  c: "컨센서스 없음 → 분모에서 제외 (0점이 아니다)",
  d: "확정 재무 대기 — 현금흐름·주식수는 정기보고서에서 온다",
};

export const PRI_PARTS = [
  { key: "p1", label: "3개월 상대수익률", max: 40 },
  { key: "p2", label: "52주 위치", max: 25 },
  { key: "p3", label: "3년 PER 밴드", max: 20 },
  { key: "p4", label: "발표 D+1 반응", max: 15 },
] as const;
