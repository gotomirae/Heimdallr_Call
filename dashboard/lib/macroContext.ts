// PRD Ref: §9, §10 — 매일 08:00 KST 갱신하는 미국·글로벌 매크로 스냅샷.
// 외부 API는 별도 배치가 조회한다. 대시보드 렌더는 네트워크 요청을 하지 않는다(T159).
import snapshot from "./macro-daily.json";

export interface MacroItem {
  title: string;
  url: string;
  publishedAt: string | null;
}

export interface MacroContext {
  source: string;
  checkedAt: string;
  marketDate: string;
  refreshOverdue?: boolean;
  items: MacroItem[];
  flags: {
    rates: boolean;
    industry: boolean;
    geopolitics: boolean;
  };
  /** PRI와 투자 점수를 합산하지 않고, 현재 거시국면에 맞춰 비교 순서만 바꾼다. */
  sortMode: "quality_price" | "earnings_growth" | "balanced";
  preferredSectors: string[];
  summary: {
    current: string;
    forward: string;
    recommendedSort: string;
  };
}

export async function getMacroContext(): Promise<MacroContext> {
  const context = snapshot as MacroContext;
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date());
  const part = (type: string) => parts.find((value) => value.type === type)?.value ?? "";
  const today = `${part("year")}-${part("month")}-${part("day")}`;
  const refreshOverdue = Number(part("hour")) >= 8 && context.checkedAt.slice(0, 10) < today;
  return { ...context, refreshOverdue, items: [...context.items], preferredSectors: [...context.preferredSectors] };
}
