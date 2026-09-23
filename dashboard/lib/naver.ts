// PRD Ref: §9.1-1, §9.1-3, §9.1-6 — 네이버 현재 시세·일봉·가치지표

const NAVER_BASE = "https://m.stock.naver.com/api/stock";
const NAVER_DAILY_URL = "https://api.finance.naver.com/siseJson.naver";
const NAVER_WISE_ANNUAL_URL = "https://navercomp.wisereport.co.kr/v2/company/cF1002.aspx";
const NAVER_REVALIDATE_SECONDS = 60;
const NAVER_TIMEOUT_MS = 5000;

type UnknownRecord = Record<string, unknown>;

export interface NaverLiveSnapshot {
  quoteAvailable: boolean;
  annualAvailable: boolean;
  priceDate: string | null;
  fetchedAt: string;
  close: number | null;
  chgPct: number | null;
  marketCapKrw: number | null;
  high52w: number | null;
  low52w: number | null;
  per4q: number | null;
  perYear: number | null;
  fwdPer: number | null;
  fwdPerYear: number | null;
  perHistory3yAvg: number | null;
  perHistoryYears: number[];
  eps: number | null;
  epsNext: number | null;
  pbr: number | null;
  roeYear: number | null;
  roe: number | null;
  roeNextYear: number | null;
  roeNext: number | null;
  fcfYear: number | null;
  /** 네이버 연간 기업실적분석의 FCF. 화면 표시 단위(억원)를 유지한다. */
  fcf: number | null;
}

export interface NaverDailyPrice {
  trade_date: string;
  close: number;
}

function record(value: unknown): UnknownRecord | null {
  return value != null && typeof value === "object" && !Array.isArray(value)
    ? (value as UnknownRecord)
    : null;
}

function numberOf(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string") return null;
  const cleaned = value.replace(/,/g, "").replace(/[^0-9.+-]/g, "").trim();
  if (!cleaned || cleaned === "+" || cleaned === "-") return null;
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}

function dateOf(value: unknown): string | null {
  const raw = typeof value === "string" ? value.replace(/[^0-9]/g, "") : "";
  return raw.length >= 8 ? `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}` : null;
}

/** 네이버의 `1조 8,654억` 표시를 원 단위로 바꾼다. 단위를 못 읽으면 추측하지 않는다. */
function marketCapOf(value: unknown): number | null {
  if (typeof value !== "string") return null;
  const jo = value.match(/([0-9,.]+)\s*조/);
  const eok = value.match(/([0-9,.]+)\s*억/);
  if (!jo && !eok) return null;
  const joValue = jo ? numberOf(jo[1]) : 0;
  const eokValue = eok ? numberOf(eok[1]) : 0;
  if (joValue == null || eokValue == null) return null;
  return joValue * 1_000_000_000_000 + eokValue * 100_000_000;
}

async function naverJson(path: string): Promise<UnknownRecord> {
  const response = await fetch(`${NAVER_BASE}/${path}`, {
    headers: { "User-Agent": "Mozilla/5.0 (compatible; HeimdallrCall/1.0)" },
    signal: AbortSignal.timeout(NAVER_TIMEOUT_MS),
    next: { revalidate: NAVER_REVALIDATE_SECONDS },
  });
  if (!response.ok) throw new Error(`Naver HTTP ${response.status}`);
  const body = record(await response.json());
  if (!body) throw new Error("Naver JSON object missing");
  return body;
}

function parseQuote(body: UnknownRecord) {
  const infos = Array.isArray(body.totalInfos) ? body.totalInfos : [];
  const values = new Map<string, unknown>();
  for (const item of infos) {
    const row = record(item);
    if (typeof row?.code === "string") values.set(row.code, row.value);
  }
  const trends = Array.isArray(body.dealTrendInfos) ? body.dealTrendInfos : [];
  const latest = record(trends[0]);
  const close = numberOf(latest?.closePrice) ?? numberOf(values.get("lastClosePrice"));
  const previous = numberOf(values.get("lastClosePrice"));
  const chgPct = close != null && previous != null && previous > 0
    ? (close / previous - 1) * 100
    : null;
  return {
    priceDate: dateOf(latest?.bizdate),
    close,
    chgPct,
    marketCapKrw: marketCapOf(values.get("marketValue")),
    high52w: numberOf(values.get("highPriceOf52Weeks")),
    low52w: numberOf(values.get("lowPriceOf52Weeks")),
    per4q: numberOf(values.get("per")),
    fwdPer: numberOf(values.get("cnsPer")),
    pbr: numberOf(values.get("pbr")),
  };
}

function parseAnnual(body: UnknownRecord) {
  const financeInfo = record(body.financeInfo);
  const titles = Array.isArray(financeInfo?.trTitleList) ? financeInfo.trTitleList : [];
  const parsedTitles = titles
    .map(record)
    .filter((row): row is UnknownRecord => row != null)
    .map((row) => ({
      key: typeof row.key === "string" ? row.key : "",
      year: typeof row.title === "string" ? Number(row.title.slice(0, 4)) : NaN,
      estimate: row.isConsensus === "Y",
    }))
    .filter((row) => row.key && Number.isFinite(row.year))
    .sort((left, right) => left.year - right.year);
  const estimates = parsedTitles.filter((row) => row.estimate);
  const actuals = parsedTitles.filter((row) => !row.estimate);
  const rows = Array.isArray(financeInfo?.rowList) ? financeInfo.rowList : [];
  const metricFor = (title: string, column: { key: string } | undefined) => {
    const metricRow = rows.map(record).find((row) => String(row?.title ?? "").replace(/\s/g, "").startsWith(title));
    const columns = record(metricRow?.columns);
    const cell = column && columns ? record(columns[column.key]) : null;
    return numberOf(cell?.value);
  };
  const metricAt = (title: string, index: number) => {
    const estimate = estimates[index];
    return {
      year: estimate?.year ?? null,
      value: metricFor(title, estimate),
    };
  };
  const history = actuals.slice(-3)
    .map((column) => ({ year: column.year, per: metricFor("PER", column) }))
    .filter((row): row is { year: number; per: number } => row.per != null && row.per > 0);
  return {
    current: { year: estimates[0]?.year ?? null, per: metricAt("PER", 0).value, roe: metricAt("ROE", 0).value, fcf: metricAt("FCF", 0).value, eps: metricAt("EPS", 0).value },
    next: { year: estimates[1]?.year ?? null, per: metricAt("PER", 1).value, roe: metricAt("ROE", 1).value, fcf: metricAt("FCF", 1).value, eps: metricAt("EPS", 1).value },
    history,
  };
}

function stripHtml(value: string): string {
  return value
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;|&#160;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/\s+/g, " ")
    .trim();
}

/** 모바일 연간 JSON이 다음 예상 연도를 생략하는 종목을 WiseReport 원표로 보완한다. */
function parseWiseAnnual(html: string) {
  const estimates: Array<{ year: number; per: number | null; roe: number | null; eps: number | null }> = [];
  const actuals: Array<{ year: number; per: number | null }> = [];
  for (const row of html.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)) {
    const cells = [...row[1].matchAll(/<(?:th|td)\b[^>]*>([\s\S]*?)<\/(?:th|td)>/gi)]
      .map((cell) => stripHtml(cell[1]));
    if (cells.length < 9) continue;
    const matched = cells[0].replace(/\s/g, "").match(/^(\d{4})\(([AE])\)$/);
    if (!matched) continue;
    const item = { year: Number(matched[1]), per: numberOf(cells[6]), roe: numberOf(cells[8]), eps: numberOf(cells[5]) };
    if (matched[2] === "E") estimates.push(item);
    else actuals.push({ year: item.year, per: item.per });
  }
  estimates.sort((left, right) => left.year - right.year);
  actuals.sort((left, right) => left.year - right.year);
  return {
    current: estimates[0] ?? { year: null, per: null, roe: null, eps: null },
    next: estimates[1] ?? { year: null, per: null, roe: null, eps: null },
    history: actuals.slice(-3).filter((row): row is { year: number; per: number } => row.per != null && row.per > 0),
  };
}

/** 한국시간 16:00을 지난 거래일 종가만 현재가로 인정한다. 장중 가격을 섞지 않는다. */
export function completedCloseAtKst16(points: NaverDailyPrice[], now = new Date()): {
  close: number;
  tradeDate: string;
  chgPct: number | null;
} | null {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", hourCycle: "h23",
  }).formatToParts(now);
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? "";
  const today = `${part("year")}-${part("month")}-${part("day")}`;
  const cutoff = new Date(`${today}T00:00:00+09:00`);
  if (Number(part("hour")) < 16) cutoff.setDate(cutoff.getDate() - 1);
  const cutoffDate = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(cutoff);
  const completed = points.filter((point) => point.trade_date <= cutoffDate);
  const latest = completed[completed.length - 1];
  if (!latest) return null;
  const previous = completed[completed.length - 2];
  return {
    close: latest.close,
    tradeDate: latest.trade_date,
    chgPct: previous?.close && previous.close > 0 ? (latest.close / previous.close - 1) * 100 : null,
  };
}

async function wiseAnnual(code: string) {
  const params = new URLSearchParams({ cmp_cd: code, finGubun: "MAIN", frq: "0" });
  const response = await fetch(`${NAVER_WISE_ANNUAL_URL}?${params}`, {
    headers: { "User-Agent": "Mozilla/5.0 (compatible; HeimdallrCall/1.0)" },
    signal: AbortSignal.timeout(NAVER_TIMEOUT_MS),
    next: { revalidate: NAVER_REVALIDATE_SECONDS },
  });
  if (!response.ok) throw new Error(`Naver WiseReport HTTP ${response.status}`);
  return parseWiseAnnual(await response.text());
}

/** 네이버 일봉. 같은 날짜 중복은 마지막 값만 남기고 일자 오름차순으로 돌려준다. */
export async function getNaverDailyPrices(
  code: string,
  years = 3
): Promise<NaverDailyPrice[]> {
  if (!/^[0-9A-Z]{6}$/.test(code)) return [];
  const end = new Date();
  const start = new Date(Date.UTC(end.getUTCFullYear() - years, end.getUTCMonth(), end.getUTCDate()));
  const ymd = (day: Date) =>
    `${day.getUTCFullYear()}${String(day.getUTCMonth() + 1).padStart(2, "0")}${String(day.getUTCDate()).padStart(2, "0")}`;
  const params = new URLSearchParams({
    symbol: code,
    requestType: "1",
    startTime: ymd(start),
    endTime: ymd(end),
    timeframe: "day",
  });
  try {
    const response = await fetch(`${NAVER_DAILY_URL}?${params}`, {
      headers: {
        Referer: "https://finance.naver.com/",
        "User-Agent": "Mozilla/5.0 (compatible; HeimdallrCall/1.0)",
      },
      signal: AbortSignal.timeout(NAVER_TIMEOUT_MS),
      next: { revalidate: 60 * 60 },
    });
    if (!response.ok) return [];
    const raw = await response.text();
    const rows = JSON.parse(raw.trim().replace(/'/g, '"')) as unknown;
    if (!Array.isArray(rows)) return [];
    const latest = new Map<string, NaverDailyPrice>();
    for (const rawRow of rows.slice(1)) {
      if (!Array.isArray(rawRow) || typeof rawRow[0] !== "string") continue;
      const date = dateOf(rawRow[0]);
      const close = numberOf(rawRow[4]);
      if (date && close != null && close > 0) latest.set(date, { trade_date: date, close });
    }
    return [...latest.values()].sort((left, right) => left.trade_date.localeCompare(right.trade_date));
  } catch {
    return [];
  }
}

/**
 * 상세 화면용 네이버 우선 스냅샷.
 *
 * 현재가는 integration 응답을 쓴다. PER·ROE는 같은 네이버 모바일 연간 재무
 * JSON의 `(E)` 열을 사용해 올해와 내년의 시간축을 정확히 맞춘다. 두 번째 추정
 * 연도가 없으면 저장 DB 값으로 꾸며내지 않고 null로 둔다.
 */
export async function getNaverLiveSnapshot(code: string): Promise<NaverLiveSnapshot | null> {
  if (!/^[0-9A-Z]{6}$/.test(code)) return null;
  const [quoteResult, annualResult, wiseResult] = await Promise.allSettled([
    naverJson(`${encodeURIComponent(code)}/integration`),
    naverJson(`${encodeURIComponent(code)}/finance/annual`),
    wiseAnnual(code),
  ]);
  const quote = quoteResult.status === "fulfilled" ? parseQuote(quoteResult.value) : null;
  const mobileAnnual = annualResult.status === "fulfilled" ? parseAnnual(annualResult.value) : null;
  const wise = wiseResult.status === "fulfilled" ? wiseResult.value : null;
  const annual = mobileAnnual || wise ? {
    current: {
      year: mobileAnnual?.current.year ?? wise?.current.year ?? null,
      per: mobileAnnual?.current.per ?? wise?.current.per ?? null,
      roe: mobileAnnual?.current.roe ?? wise?.current.roe ?? null,
      fcf: mobileAnnual?.current.fcf ?? null,
      eps: mobileAnnual?.current.eps ?? wise?.current.eps ?? null,
    },
    next: {
      year: mobileAnnual?.next.year ?? wise?.next.year ?? null,
      per: mobileAnnual?.next.per ?? wise?.next.per ?? null,
      roe: mobileAnnual?.next.roe ?? wise?.next.roe ?? null,
      fcf: mobileAnnual?.next.fcf ?? null,
      eps: mobileAnnual?.next.eps ?? wise?.next.eps ?? null,
    },
    history: mobileAnnual?.history?.length ? mobileAnnual.history : wise?.history ?? [],
  } : null;
  if (!quote && !annual) return null;
  return {
    quoteAvailable: quote != null,
    annualAvailable: annual != null,
    priceDate: quote?.priceDate ?? null,
    fetchedAt: new Date().toISOString(),
    close: quote?.close ?? null,
    chgPct: quote?.chgPct ?? null,
    marketCapKrw: quote?.marketCapKrw ?? null,
    high52w: quote?.high52w ?? null,
    low52w: quote?.low52w ?? null,
    per4q: annual?.current.per ?? null,
    perYear: annual?.current.year ?? null,
    fwdPer: annual?.next.per ?? null,
    fwdPerYear: annual?.next.year ?? null,
    perHistory3yAvg: annual?.history?.length
      ? annual.history.reduce((sum, row) => sum + row.per, 0) / annual.history.length
      : null,
    perHistoryYears: annual?.history?.map((row) => row.year) ?? [],
    eps: annual?.current.eps ?? null,
    epsNext: annual?.next.eps ?? null,
    pbr: quote?.pbr ?? null,
    roeYear: annual?.current.year ?? null,
    roe: annual?.current.roe ?? null,
    roeNextYear: annual?.next.year ?? null,
    roeNext: annual?.next.roe ?? null,
    fcfYear: annual?.current.year ?? null,
    fcf: annual?.current.fcf ?? null,
  };
}
