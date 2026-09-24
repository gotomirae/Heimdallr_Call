// PRD Ref: §9, §10 — 매일 07:00 KST 갱신하는 미국·글로벌 매크로 스냅샷.
// 외부 API는 별도 배치가 조회한다. 대시보드 렌더는 네트워크 요청을 하지 않는다(T159).
import snapshot from "./macro-daily.json";

function expectedUsSession(now: Date): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(now);
  const part = (type: string) => Number(parts.find((value) => value.type === type)?.value ?? 0);
  const day = new Date(Date.UTC(part("year"), part("month") - 1, part("day")));
  if (part("hour") < 16 || (part("hour") === 16 && part("minute") < 10)) {
    day.setUTCDate(day.getUTCDate() - 1);
  }
  while (day.getUTCDay() === 0 || day.getUTCDay() === 6) day.setUTCDate(day.getUTCDate() - 1);
  return day.toISOString().slice(0, 10);
}

export interface MacroItem {
  title: string;
  url: string;
  publishedAt: string | null;
}
export interface MacroBriefing extends MacroItem {
  summary: string;
  keyPoint?: string;
  marketImpact?: string;
}

export interface MacroMarketPoint { date: string; value: number }
export interface MacroMarketSeries {
  date: string;
  close: number;
  changePct: number;
  history?: MacroMarketPoint[];
}
export interface FearGreedSnapshot {
  date: string;
  value: number;
  label: string;
  history: MacroMarketPoint[];
  sourceUrl: string;
  sourceLabel: string;
}
export interface MacroEvent {
  date: string;
  event: string;
  source: string;
  url: string;
  watch: string;
  response: string;
  important?: boolean;
}

export interface MacroContext {
  source: string;
  checkedAt: string;
  marketDate: string;
  refreshOverdue?: boolean;
  items: MacroItem[];
  briefings?: MacroBriefing[];
  briefingOverdue?: boolean;
  markets?: Partial<Record<"sp500" | "nasdaq" | "dow" | "semiconductor" | "vix", MacroMarketSeries>>;
  fearGreed?: FearGreedSnapshot | null;
  nextEvents?: MacroEvent[];
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
  const now = new Date();
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", hourCycle: "h23",
  }).formatToParts(now);
  const part = (type: string) => parts.find((value) => value.type === type)?.value ?? "";
  const today = `${part("year")}-${part("month")}-${part("day")}`;
  // 휴장일에는 전 거래일이 맞을 수 있다. 경고만 표시하고 날짜를 임의로 채우지 않는다.
  const refreshOverdue = Number(part("hour")) >= 7 && (
    context.checkedAt.slice(0, 10) < today || context.marketDate < expectedUsSession(now)
  );
  const briefings = context.briefings ?? [];
  const cpiDate = briefings.find((item) => item.title.includes("소비자물가"))?.publishedAt;
  const briefingOverdue = !cpiDate || now.getTime() - new Date(`${cpiDate}T00:00:00Z`).getTime() > 45 * 86_400_000;
  return {
    ...context,
    refreshOverdue,
    briefingOverdue,
    briefings: [...briefings],
    items: [...context.items],
    preferredSectors: [...context.preferredSectors],
    nextEvents: [...(context.nextEvents ?? [])],
    markets: context.markets ? { ...context.markets } : {},
    fearGreed: context.fearGreed ? { ...context.fearGreed, history: [...context.fearGreed.history] } : null,
  };
}
