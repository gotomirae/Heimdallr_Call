// PRD Ref: §9.1 — LLM 분석의 **검증**
//
// ★★ **이 모듈이 답하려는 질문(사용자 지정 2026-08-22):**
//   "LLM이 말한 숫자와 내러티브가 맞는가?"
//   "그 성장 스토리대로 실적이 실제로 가시화되고 있는가?"
//
// ★★ **여기서 하지 않는 것: 문장에서 숫자를 긁어내 대조하기.**
//   "3Q 매출 2,000억 이상"에서 2000을 뽑아 비교하고 싶지만, 그 숫자가 매출인지
//   시총인지 목표주가인지 문장을 읽지 않고는 알 수 없다. 정규식으로 뽑으면
//   **대부분 맞다가 가끔 조용히 틀린다** — 이 프로젝트에서 가장 비싼 종류의 버그다.
//   대신 **분석이 쓰인 분기 이후에 실제로 발표된 실적**과 대조한다. 이건 애매하지 않다.
//
// ★ 분석 시점 이후 새 실적이 없으면 **"검증 대기"**라고 말한다. 없는 검증을
//   "이상 없음"으로 바꿔치기하지 않는다 — 그게 가장 위험한 초록불이다.

import { qIndex } from "./format";
import type { AnalysisView } from "./analysis";
import type { FundamentalRow } from "./types";

/** 검증 한 줄의 판정. */
export type Verdict = "확인" | "미달" | "판정불가";

export interface Check {
  /** 무엇을 봤는가. */
  label: string;
  verdict: Verdict;
  /** 분석 시점의 값 → 그 뒤 실제 값. 숫자가 없으면 설명만. */
  detail: string;
  /** 왜 그렇게 판정했는가 — 한 줄. */
  note?: string;
}

export interface NarrativeCheck {
  /** 분석이 어느 분기를 보고 쓰였는가. */
  analyzedQuarter: string | null;
  /** 그 뒤로 실제 발표된 가장 최신 분기. 없으면 null. */
  latestQuarter: string | null;
  /** 분석 이후 새로 나온 분기 수. 0이면 아직 검증할 수 없다. */
  quartersSince: number;
  checks: Check[];
  /** 종합 한 줄. 표본이 없으면 그 사실을 말한다. */
  headline: string;
  /** 확률 합이 1.00인가 — 스키마가 강제하지 못하는 유일한 정합성 조건. */
  probabilityOk: boolean | null;
  probabilitySum: number | null;
  /** 예상 시점이 이미 지난 트리거 수. 확인해야 할 것들이다. */
  overdueTriggers: number;
  /** 지속 전망(분기)과 실제 경과 분기의 대비. */
  sustainabilityNote: string | null;
}

function fmtPct(v: number | null): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}
function fmtPp(v: number | null): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%p`;
}
function qLabel(f: { fiscal_year: number; fiscal_quarter: number }): string {
  return `${f.fiscal_year}.${f.fiscal_quarter}Q`;
}

/**
 * 화면에 보이는 자릿수(소수 1자리)보다 작은 차이는 **차이가 아니다.**
 *
 * ★★ 이 값이 없으면 `33.9% → 33.9%`가 '미달'로 찍힌다. 실측(110990):
 *   OPM이 소수점 아래 둘째 자리에서만 0.001%p 낮아졌는데 판정이 **미달**로 뒤집혔고,
 *   화면에는 같은 숫자 두 개와 "미달"이 나란히 떠 읽는 사람이 자기 눈을 의심하게 됐다.
 *   "보이는 것과 판정이 어긋나는" 것은 조용히 틀리는 것만큼 나쁘다.
 */
const EPSILON_PP = 0.05;

/**
 * 분석 시점 대비 그 지표가 유지·개선됐는가.
 *
 * ★ 값의 단위와 **차이의 단위가 다르다.** 성장률도 이익률도 값은 `%`지만,
 *   두 시점의 차이는 언제나 `%p`다. 둘을 같은 기호로 쓰면
 *   "-80.8% 낮아졌다"처럼 **80%가 줄었다는 뜻으로 읽히는 문장**이 나간다.
 *   실제로는 성장률이 80.8%**p** 낮아진 것이다.
 *
 * ★ 부호가 바뀌는 구간(흑전·적전)에서는 두 값 중 하나가 null이라 비교 자체가
 *   성립하지 않는다 — '미달'이 아니라 '판정불가'다. 여기를 뭉개면
 *   흑자전환한 회사가 "스토리 이탈"로 찍힌다.
 */
function compareLevel(label: string, before: number | null, after: number | null): Check {
  if (before == null || after == null) {
    return {
      label,
      verdict: "판정불가",
      detail: `${fmtPct(before)} → ${fmtPct(after)}`,
      note: "부호 전환 구간이거나 값이 아직 없다 — 0으로 보지 않는다.",
    };
  }
  const delta = after - before;
  const detail = `${fmtPct(before)} → ${fmtPct(after)} (${fmtPp(delta)})`;
  if (Math.abs(delta) < EPSILON_PP) {
    return { label, verdict: "확인", detail, note: "분석 시점과 사실상 같은 수준을 지켰다." };
  }
  return delta > 0
    ? { label, verdict: "확인", detail, note: "분석 시점보다 높아졌다." }
    : { label, verdict: "미달", detail, note: `분석 이후 ${fmtPp(delta)} 낮아졌다.` };
}

/**
 * 분석의 내러티브가 이후 실적으로 확인되는가.
 *
 * @param analysis  읽어 들인 LLM 분석
 * @param funds     그 종목의 분기 재무 **전체**(오름차순)
 * @param year      분석이 대상으로 삼은 회계연도
 * @param quarter   분석이 대상으로 삼은 분기
 */
export function checkNarrative(
  analysis: AnalysisView,
  funds: FundamentalRow[],
  year: number | null,
  quarter: number | null
): NarrativeCheck {
  const probabilitySum = analysis.probabilitySum;
  const probabilityOk =
    probabilitySum == null ? null : Math.abs(probabilitySum - 1) <= 0.01;

  // ── 예상 시점이 지난 트리거 ───────────────────────────────────
  // ★ `expected_date`는 자유 문자열이다("2026-11", "2026년 4분기"…).
  //   **`YYYY-MM` 꼴로 읽히는 것만** 센다. 파싱 실패를 '지났다'로 치면
  //   형식이 다른 것뿐인 트리거가 전부 연체로 찍힌다.
  const today = new Date();
  const thisMonth = today.getFullYear() * 12 + today.getMonth();
  const overdueTriggers = [...analysis.triggers3m, ...analysis.triggers6m].filter((t) => {
    const m = t.expectedDate?.match(/^(\d{4})-(\d{1,2})/);
    if (!m) return false;
    return Number(m[1]) * 12 + (Number(m[2]) - 1) < thisMonth;
  }).length;

  const base: NarrativeCheck = {
    analyzedQuarter: year && quarter ? `${year}.${quarter}Q` : null,
    latestQuarter: null,
    quartersSince: 0,
    checks: [],
    headline: "",
    probabilityOk,
    probabilitySum,
    overdueTriggers,
    sustainabilityNote: null,
  };

  if (year == null || quarter == null) {
    base.headline = "분석이 어느 분기를 봤는지 알 수 없어 대조하지 않았다.";
    return base;
  }

  const analyzedIdx = qIndex(year, quarter);
  const analyzed = funds.find(
    (f) => f.fiscal_year === year && f.fiscal_quarter === quarter
  );
  // ★ **분석 시점보다 뒤에 발표된** 분기만 본다. 앞 분기를 섞으면
  //   "분석 전에 이미 알던 것"으로 분석을 검증하는 셈이 된다.
  const later = funds
    .filter((f) => qIndex(f.fiscal_year, f.fiscal_quarter) > analyzedIdx)
    .filter((f) => f.revenue != null)
    .sort((a, b) => qIndex(a.fiscal_year, a.fiscal_quarter) - qIndex(b.fiscal_year, b.fiscal_quarter));
  const newest = later[later.length - 1] ?? null;

  base.latestQuarter = newest ? qLabel(newest) : base.analyzedQuarter;
  base.quartersSince = later.length;

  // ── 지속 전망 대비 경과 ───────────────────────────────────────
  if (analysis.sustainabilityQuarters != null) {
    base.sustainabilityNote =
      later.length === 0
        ? `가속이 ${analysis.sustainabilityQuarters}개 분기 이어진다고 봤다 — 아직 검증할 분기가 없다.`
        : `가속 지속 전망 ${analysis.sustainabilityQuarters}개 분기 중 ${later.length}개 분기가 지났다.`;
  }

  if (!newest || !analyzed) {
    base.headline = newest
      ? "분석 대상 분기의 재무를 찾지 못해 대조하지 않았다."
      : "분석 이후 새로 발표된 실적이 아직 없다 — **검증 대기**다. " +
        "다음 분기가 나오면 이 자리에서 자동으로 대조한다.";
    return base;
  }

  // ── 실제 대조 ─────────────────────────────────────────────────
  base.checks = [
    compareLevel("매출 YoY", analyzed.revenue_yoy, newest.revenue_yoy),
    compareLevel("영업이익 YoY", analyzed.op_yoy, newest.op_yoy),
    compareLevel("영업이익률(OPM)", analyzed.opm, newest.opm),
  ];

  const decided = base.checks.filter((c) => c.verdict !== "판정불가");
  const confirmed = decided.filter((c) => c.verdict === "확인").length;

  if (decided.length === 0) {
    base.headline =
      `${qLabel(newest)}가 나왔지만 부호 전환 구간이라 성장률로 대조할 수 없다. ` +
      "숫자 대신 아래 시나리오 조건을 직접 읽어라.";
  } else if (confirmed === decided.length) {
    base.headline =
      `**성장 스토리대로 가고 있다.** 분석(${base.analyzedQuarter}) 이후 발표된 ` +
      `${qLabel(newest)}에서 대조 가능한 ${decided.length}개 지표가 모두 분석 시점 수준을 지켰다.`;
  } else if (confirmed === 0) {
    base.headline =
      `**성장 스토리가 실적으로 확인되지 않는다.** ${qLabel(newest)}에서 대조 가능한 ` +
      `${decided.length}개 지표가 모두 분석 시점보다 낮아졌다. 아래 비관 시나리오의 조건과 대조하라.`;
  } else {
    base.headline =
      `**부분적으로만 가시화됐다.** ${qLabel(newest)} 기준 ${decided.length}개 중 ` +
      `${confirmed}개만 분석 시점 수준을 지켰다.`;
  }

  return base;
}
