// PRD Ref: §9.1-1, §9.1-6 — 상세 화면의 네이버 현재 시세·가치지표

const NAVER_BASE = "https://m.stock.naver.com/api/stock";
const NAVER_REVALIDATE_SECONDS = 60;

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
  fwdPer: number | null;
  pbr: number | null;
  roeYear: number | null;
  roe: number | null;
  roeNextYear: number | null;
  roeNext: number | null;
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
  const estimates = titles
    .map(record)
    .filter((row): row is UnknownRecord => row != null && row.isConsensus === "Y")
    .map((row) => ({
      key: typeof row.key === "string" ? row.key : "",
      year: typeof row.title === "string" ? Number(row.title.slice(0, 4)) : NaN,
    }))
    .filter((row) => row.key && Number.isFinite(row.year))
    .sort((left, right) => left.year - right.year);
  const rows = Array.isArray(financeInfo?.rowList) ? financeInfo.rowList : [];
  const roeRow = rows.map(record).find((row) => row?.title === "ROE");
  const columns = record(roeRow?.columns);
  const roeAt = (index: number) => {
    const estimate = estimates[index];
    const cell = estimate && columns ? record(columns[estimate.key]) : null;
    return {
      year: estimate?.year ?? null,
      value: numberOf(cell?.value),
    };
  };
  return { current: roeAt(0), next: roeAt(1) };
}

/**
 * 상세 화면용 네이버 우선 스냅샷.
 *
 * 현재가·PER·F.PER은 같은 integration 응답에서 읽어 기준 시점을 섞지 않는다.
 * ROE는 같은 네이버 모바일 재무 JSON의 `(E)` 열만 사용한다. 두 번째 추정 연도가
 * 없으면 저장 DB 값으로 꾸며내지 않고 null로 둔다.
 */
export async function getNaverLiveSnapshot(code: string): Promise<NaverLiveSnapshot | null> {
  if (!/^[0-9A-Z]{6}$/.test(code)) return null;
  const [quoteResult, annualResult] = await Promise.allSettled([
    naverJson(`${encodeURIComponent(code)}/integration`),
    naverJson(`${encodeURIComponent(code)}/finance/annual`),
  ]);
  const quote = quoteResult.status === "fulfilled" ? parseQuote(quoteResult.value) : null;
  const annual = annualResult.status === "fulfilled" ? parseAnnual(annualResult.value) : null;
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
    per4q: quote?.per4q ?? null,
    fwdPer: quote?.fwdPer ?? null,
    pbr: quote?.pbr ?? null,
    roeYear: annual?.current.year ?? null,
    roe: annual?.current.value ?? null,
    roeNextYear: annual?.next.year ?? null,
    roeNext: annual?.next.value ?? null,
  };
}

