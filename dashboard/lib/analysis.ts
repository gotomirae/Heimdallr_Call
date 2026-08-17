// PRD Ref: §9.2 방어 1 — analyses.payload는 부분적으로만 채워질 수 있다.
//
// ★ HermesCall에서 실제로 터졌다: `payload && payload.scenarios.bull`처럼
//   **상위 객체만 확인하고 하위 필드를 읽으면 페이지 전체가 500**이 난다.
//   LLM 응답이 스키마를 통과해도 선택 필드는 빌 수 있고, 실패해 부분 저장될 수도 있다.
//   그래서 여기서 **필드 단위로** 좁혀 꺼낸다. 못 읽은 값은 전부 null이고,
//   화면은 null을 '—'로 그린다 — 없는 걸 0이나 빈 문자열로 바꾸지 않는다.

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value : null;
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
}

export interface Risk {
  risk: string | null;
  likelihood: string | null;
  impact: string | null;
}

export interface Scenario {
  name: string;
  probability: number | null;
  description: string | null;
}

export interface AnalysisView {
  thesis: string | null;
  whyNow: string | null;
  structuralDrivers: string[];
  temporaryDrivers: string[];
  sustainabilityQuarters: number | null;
  triggers3m: Trigger[];
  triggers6m: Trigger[];
  scenarios: Scenario[];
  probabilitySum: number | null;
  risks: Risk[];
  nextDataToCheck: string[];
  whyIMightBeWrong: string | null;
  isEmpty: boolean;
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
    };
  });
}

function readScenarios(node: unknown): Scenario[] {
  const bucket = asRecord(node);
  if (!bucket) return [];
  const out: Scenario[] = [];
  for (const name of ["bull", "base", "bear"]) {
    const s = asRecord(bucket[name]);
    if (!s) continue; // ★ 하나가 없다고 나머지를 버리지 않는다
    out.push({
      name,
      probability: asNumber(s.probability),
      description: asString(s.description),
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
    structuralDrivers: quality ? readStrings(quality, "structural_drivers") : [],
    temporaryDrivers: quality ? readStrings(quality, "temporary_drivers") : [],
    sustainabilityQuarters: quality ? asNumber(quality.sustainability_quarters) : null,
    triggers3m: root ? readTriggers(root.triggers, "within_3m") : [],
    triggers6m: root ? readTriggers(root.triggers, "within_6m") : [],
    scenarios,
    // 확률 합은 1.00이어야 한다. 어긋나면 화면에 드러내 검증 실패를 숨기지 않는다.
    probabilitySum: probs.length ? probs.reduce((a, b) => a + b, 0) : null,
    risks: root
      ? asArray(root.risks).map((raw) => {
          const r = asRecord(raw);
          return {
            risk: r ? asString(r.risk) : null,
            likelihood: r ? asString(r.likelihood) : null,
            impact: r ? asString(r.impact) : null,
          };
        })
      : [],
    nextDataToCheck: root ? readStrings(root, "next_data_to_check") : [],
    whyIMightBeWrong: root ? asString(root.why_i_might_be_wrong) : null,
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
