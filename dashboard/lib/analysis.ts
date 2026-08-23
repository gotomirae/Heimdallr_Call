// PRD Ref: §9.2 방어 1 — analyses.payload는 부분적으로만 채워질 수 있다.
//
// ★ HermesCall에서 실제로 터졌다: `payload && payload.scenarios.bull`처럼
//   **상위 객체만 확인하고 하위 필드를 읽으면 페이지 전체가 500**이 난다.
//   LLM 응답이 스키마를 통과해도 선택 필드는 빌 수 있고, 실패해 부분 저장될 수도 있다.
//   그래서 여기서 **필드 단위로** 좁혀 꺼낸다. 못 읽은 값은 전부 null이고,
//   화면은 null을 '—'로 그린다 — 없는 걸 0이나 빈 문자열로 바꾸지 않는다.
//
// ★★ **2026-08-22 — 키 이름이 저장된 것과 달라 네 곳이 통째로 비어 있었다.**
//   에러도 경고도 없이 카드만 안 그려져 "아직 분석이 부족하다"로 보였다.
//   실측(analyses 316행): 데이터는 멀쩡히 들어 있었고 읽는 쪽만 틀렸다.
//     scenarios[].description   → 저장은 `condition` + `implication`
//     acceleration_quality.*_drivers → 저장은 `growth_engine.drivers`
//     why_i_might_be_wrong      → 저장은 `how_i_could_be_wrong`
//     next_data_to_check        → 저장은 `next_data_to_watch`
//   **읽는 키는 `src/analysis/prompts.py`의 스키마에서 그대로 따온다.**
//   여기를 고칠 때는 반드시 그 파일을 열어 대조하라 — 기억으로 적으면 또 어긋난다.

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** 모델이 값 안에 흘려 넣는 마커. 여기서부터 뒤는 그 필드의 내용이 아니다. */
const LEAK_MARKERS = ["</", "<parameter", "<function_calls", "<invoke", "<"];

/**
 * 문자열 값에 새어 든 **XML 태그와 그 뒤 전부**를 잘라낸다 (T61).
 *
 * ★ 도구 호출로 받아도 모델이 값 **안쪽에** 닫는 태그와 다음 필드를 통째로
 *   흘려 넣을 때가 있다. 스키마 검증은 통과한다 — 타입은 여전히 문자열이다.
 *   실측(042700): `one_line_thesis` 334자 중 뒤 230자가
 *   `…구간이다.</one_line_thesis>\n<parameter name="why_now">…`였다.
 *
 * ★ 저장 시점(`src/analysis/analyze.py`)에서도 걷어내지만, **이미 저장된 행이
 *   있으므로** 읽는 쪽에서도 막는다. 파이썬 쪽 짝은 `strip_tag_leakage`다.
 */
export function stripTagLeakage(text: string): string {
  let cut = text.length;
  for (const marker of LEAK_MARKERS) {
    const found = text.indexOf(marker);
    if (found !== -1) cut = Math.min(cut, found);
  }
  const trimmed = text.slice(0, cut).trim();
  return trimmed || text.trim();
}

function asString(value: unknown): string | null {
  if (typeof value !== "string" || value.trim() === "") return null;
  const clean = stripTagLeakage(value);
  return clean === "" ? null : clean;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export interface Trigger {
  event: string | null;
  metric: string | null;
  expectedDate: string | null;
  /** 주가 영향 크기. 없으면 null — 구 스키마로 저장된 행이 있다. */
  impact: "high" | "medium" | "low" | null;
  /** 트리거 성격(실적·수주·증설·인증·규제 등). 자유 문자열이다. */
  kind: string | null;
}

/** 실적이 왜 변했고, 무엇이 달라졌고, 앞으로 어떻게 될 것인가. */
export interface EarningsChange {
  cause: string | null;
  effect: string | null;
  outlook: string | null;
  confidence: "high" | "medium" | "low" | null;
}

export interface Risk {
  risk: string | null;
  likelihood: string | null;
  impact: string | null;
  /** 그 리스크가 실현되는지 확인할 지표. */
  watchMetric: string | null;
}

export interface Scenario {
  name: "bull" | "base" | "bear";
  /** 한글 이름. 화면은 bull/base/bear를 그대로 쓰지 않는다. */
  label: string;
  probability: number | null;
  /** **무엇이 관측되면 이 시나리오인가.** 검증의 출발점이다. */
  condition: string | null;
  /** 그래서 주가·밸류에이션에 무슨 뜻인가. */
  implication: string | null;
}

/** 주가가 이미 아는 것과 아직 모르는 것. */
export interface PricePosition {
  verdict: string | null;
  reason: string | null;
  /** 과거부터 지금까지 주가가 왜 이렇게 움직였는가 — 구간별 원인. 2026-08-23 추가. */
  priceHistory: string | null;
  pricedIn: string[];
  notPricedIn: string[];
}

/** 성장 엔진 — 무엇이 성장을 만들고 있으며 그것이 구조적인가. */
export interface GrowthEngine {
  drivers: string[];
  /** 'structural' | 'temporary'. 구 스키마 행에는 없다. */
  nature: "structural" | "temporary" | null;
  evidence: string | null;
}

export interface AnalysisView {
  thesis: string | null;
  whyNow: string | null;
  /** 실적 변화의 원인·결과·전망. 구 스키마 행은 전부 null이다. */
  earningsChange: EarningsChange;
  growthEngine: GrowthEngine;
  /** 가속이 진짜인가에 대한 판단. */
  isGenuine: boolean | null;
  baseEffectAssessment: string | null;
  sustainabilityQuarters: number | null;
  triggers3m: Trigger[];
  triggers6m: Trigger[];
  scenarios: Scenario[];
  probabilitySum: number | null;
  pricePosition: PricePosition;
  risks: Risk[];
  nextDataToWatch: string[];
  howICouldBeWrong: string | null;
  isEmpty: boolean;
}

/**
 * 실적 변화 3단(원인·결과·전망).
 *
 * ★ 이 필드는 2026-08-17에 추가됐다. **그 전에 저장된 행에는 없다** —
 *   없으면 전부 null을 주고 화면이 그 사실을 밝힌다(빈 문자열로 채우지 않는다).
 */
function readEarningsChange(node: unknown): EarningsChange {
  const n = asRecord(node);
  return {
    cause: n ? asString(n.cause) : null,
    effect: n ? asString(n.effect) : null,
    outlook: n ? asString(n.outlook) : null,
    confidence: n ? (asString(n.confidence) as EarningsChange["confidence"]) : null,
  };
}

function readTriggers(node: unknown, key: string): Trigger[] {
  const bucket = asRecord(node);
  if (!bucket) return [];
  return asArray(bucket[key]).map((raw) => {
    const t = asRecord(raw);
    return {
      event: t ? asString(t.event) : null,
      metric: t ? asString(t.verifiable_metric) : null,
      expectedDate: t ? asString(t.expected_date) : null,
      impact: t ? (asString(t.impact) as Trigger["impact"]) : null,
      kind: t ? asString(t.kind) : null,
    };
  });
}

const SCENARIO_LABEL: Record<Scenario["name"], string> = {
  bull: "낙관",
  base: "기본",
  bear: "비관",
};

/**
 * 시나리오 — **`condition`과 `implication`이다.**
 *
 * ★ 예전에는 `description`을 읽었다. 그런 키는 저장된 적이 없어서 본문이
 *   **항상 '—'로 비어 있었다.** 확률만 보이니 "모델이 성의 없이 답했다"로 읽혔지만
 *   실제로는 조건과 함의가 멀쩡히 들어 있었다.
 */
function readScenarios(node: unknown): Scenario[] {
  const bucket = asRecord(node);
  if (!bucket) return [];
  const out: Scenario[] = [];
  for (const name of ["bull", "base", "bear"] as Scenario["name"][]) {
    const s = asRecord(bucket[name]);
    if (!s) continue; // ★ 하나가 없다고 나머지를 버리지 않는다
    out.push({
      name,
      label: SCENARIO_LABEL[name],
      probability: asNumber(s.probability),
      condition: asString(s.condition),
      implication: asString(s.implication),
    });
  }
  return out;
}

function readStrings(node: unknown, key: string): string[] {
  const bucket = asRecord(node);
  if (!bucket) return [];
  return asArray(bucket[key])
    .map((v) => asString(v))
    .filter((v): v is string => v !== null);
}

function readGrowthEngine(node: unknown): GrowthEngine {
  const n = asRecord(node);
  const nature = n ? asString(n.structural_or_temporary) : null;
  return {
    drivers: n ? readStrings(n, "drivers") : [],
    nature: nature === "structural" || nature === "temporary" ? nature : null,
    evidence: n ? asString(n.evidence) : null,
  };
}

function readPricePosition(node: unknown): PricePosition {
  const n = asRecord(node);
  return {
    verdict: n ? asString(n.verdict) : null,
    reason: n ? asString(n.reason) : null,
    // ★ 2026-08-23 추가 — 그 전에 저장된 행에는 없다. 없으면 null이고 화면이 안 그린다.
    priceHistory: n ? asString(n.price_history) : null,
    pricedIn: n ? readStrings(n, "priced_in") : [],
    notPricedIn: n ? readStrings(n, "not_priced_in") : [],
  };
}

export function readAnalysis(payload: unknown): AnalysisView {
  const root = asRecord(payload);
  const quality = root ? asRecord(root.acceleration_quality) : null;

  const scenarios = root ? readScenarios(root.scenarios) : [];
  const probs = scenarios
    .map((s) => s.probability)
    .filter((p): p is number => p !== null);

  const view: AnalysisView = {
    thesis: root ? asString(root.one_line_thesis) : null,
    whyNow: root ? asString(root.why_now) : null,
    earningsChange: readEarningsChange(root ? root.earnings_change : null),
    growthEngine: readGrowthEngine(root ? root.growth_engine : null),
    isGenuine:
      quality && typeof quality.is_genuine === "boolean" ? quality.is_genuine : null,
    baseEffectAssessment: quality ? asString(quality.base_effect_assessment) : null,
    sustainabilityQuarters: quality ? asNumber(quality.sustainability_quarters) : null,
    triggers3m: root ? readTriggers(root.triggers, "within_3m") : [],
    triggers6m: root ? readTriggers(root.triggers, "within_6m") : [],
    scenarios,
    // 확률 합은 1.00이어야 한다. 어긋나면 화면에 드러내 검증 실패를 숨기지 않는다.
    probabilitySum: probs.length ? probs.reduce((a, b) => a + b, 0) : null,
    pricePosition: readPricePosition(root ? root.price_position : null),
    risks: root
      ? asArray(root.risks).map((raw) => {
          const r = asRecord(raw);
          return {
            risk: r ? asString(r.risk) : null,
            likelihood: r ? asString(r.likelihood) : null,
            impact: r ? asString(r.impact) : null,
            watchMetric: r ? asString(r.watch_metric) : null,
          };
        })
      : [],
    nextDataToWatch: root ? readStrings(root, "next_data_to_watch") : [],
    howICouldBeWrong: root ? asString(root.how_i_could_be_wrong) : null,
    isEmpty: false,
  };

  view.isEmpty =
    !view.thesis &&
    !view.whyNow &&
    view.scenarios.length === 0 &&
    view.risks.length === 0 &&
    view.triggers3m.length === 0;

  return view;
}
