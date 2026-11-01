// PRD Ref: §9 · ADR50. Owner secret stays in this browser session.
export const ANALYSIS_SESSION_KEY = "heimdallr-analysis-access";
export function analysisHeaders(): Record<string, string> {
  return {"content-type": "application/json", authorization: `Bearer ${sessionStorage.getItem(ANALYSIS_SESSION_KEY) ?? ""}`};
}
