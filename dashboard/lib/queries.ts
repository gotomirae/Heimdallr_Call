// PRD Ref: §9 · traps.md T7(페이징), T40(빈티지), T26(조용한 감점)
import { selectAll, selectWithOptionalColumns, supabase } from "./supabase";
import { qIndex } from "./format";
import type {
  ConsensusRow,
  DisclosureRow,
  FundamentalRow,
  PriceRow,
  QuarterPriceRow,
  ScreenRow,
  UniverseRow,
} from "./types";

const UNIVERSE_COLUMNS =
  "code,name,board,industry,products,market_cap_krw,sector_caveat,is_excluded,exclude_reason";

const SCREEN_COLUMNS = [
  "code", "fiscal_year", "fiscal_quarter", "gate_passed", "gate_detail",
  "base_effect_warning", "turnaround", "score_flash",
  "score_a", "score_b", "score_c", "score_d", "has_consensus",
  "pri", "pri_detail", "grade",
  "raw_a1", "raw_a2", "raw_a3", "raw_a4",
  "raw_b1", "raw_b2", "raw_b3", "raw_b4",
  "raw_c1", "raw_c2",
  "raw_d1", "raw_d2", "raw_d3", "raw_d4",
];

const FUND_COLUMNS = [
  "code", "fiscal_year", "fiscal_quarter", "revenue", "op", "np",
  "revenue_yoy", "op_yoy", "op_status_label", "opm", "opm_yoy_delta",
  "revenue_qoq", "eps", "eps_yoy", "fcf",
  "ttm_revenue", "ttm_opm", "ttm_opm_delta", "is_estimate", "source",
];

// ★ 배열로 둔다 — `ret_5d`는 마이그레이션 전까지 DB에 없어서 통째 조회가 42703으로
//   죽는다. `selectWithOptionalColumns`가 없는 컬럼을 걷어내려면 배열이어야 한다(T18).
const PRICE_COLUMNS = [
  "code", "snap_date", "close", "chg_pct", "high_52w", "low_52w", "pos_52w",
  "rel_ret_3m", "ret_5d",
  "market_cap_krw", "per", "pbr", "per_pctile_3y", "avg_value_20d",
];

/**
 * ★ `screen_results`는 분기 이력이 쌓이는 테이블이다(T40).
 *   종목당 여러 행이 남으므로 **반드시 종목별 최신 1행으로 접어야 한다.**
 *   그냥 집계하면 같은 종목이 여러 번 세어지고, PRI·C축 배선 이전에 저장된
 *   구 로직 값이 현재 값과 섞인다. 실측: 전체 집계 시 게이트 통과 511 vs 등급 344.
 */
export function foldLatest<T extends { code: string; fiscal_year: number; fiscal_quarter: number }>(
  rows: T[]
): Map<string, T> {
  const latest = new Map<string, T>();
  for (const row of rows) {
    const prev = latest.get(row.code);
    if (
      !prev ||
      qIndex(row.fiscal_year, row.fiscal_quarter) >
        qIndex(prev.fiscal_year, prev.fiscal_quarter)
    ) {
      latest.set(row.code, row);
    }
  }
  return latest;
}

export async function getUniverse(): Promise<Map<string, UniverseRow>> {
  const rows = await selectAll<UniverseRow>("krx_universe", UNIVERSE_COLUMNS);
  return new Map(rows.map((r) => [r.code, r]));
}

/**
 * 전 종목의 **최신** 스크리닝 결과. 누락 컬럼은 루프로 걷어낸다(§9.2).
 *
 * ★ `accelerating: true`(기본)이면 **게이트를 통과한 종목만** 돌려준다.
 *   이 대시보드는 "실적이 가속 중인 종목"을 보는 곳이다 —
 *   탈락·판정불가 767종목이 섞이면 매트릭스가 회색 점으로 덮이고
 *   목록에서도 눈이 갈 곳을 잃는다.
 *   전수가 필요한 화면(예: 향후 /screener)에서만 false를 준다.
 */
export async function getLatestScreens(
  { accelerating = true }: { accelerating?: boolean } = {}
): Promise<{
  rows: ScreenRow[];
  dropped: string[];
}> {
  const { rows, dropped } = await selectWithOptionalColumns<ScreenRow>(
    "screen_results",
    SCREEN_COLUMNS,
    (q, cols) => q.select(cols).range(0, 4999)
  );
  // range(0,4999)로도 PostgREST는 1,000행씩만 줄 수 있으므로 페이징으로 보강한다.
  const all =
    rows.length >= 1000
      ? await selectAll<ScreenRow>("screen_results", SCREEN_COLUMNS.filter((c) => !dropped.includes(c)).join(","))
      : rows;
  const latest = Array.from(foldLatest(all).values());
  return {
    rows: accelerating ? latest.filter((r) => r.gate_passed === true) : latest,
    dropped,
  };
}

export async function getScreenForCode(
  code: string
): Promise<{ row: ScreenRow | null; history: ScreenRow[]; dropped: string[] }> {
  const { rows, dropped } = await selectWithOptionalColumns<ScreenRow>(
    "screen_results",
    SCREEN_COLUMNS,
    (q, cols) => q.select(cols).eq("code", code)
  );
  const sorted = [...rows].sort(
    (a, b) =>
      qIndex(b.fiscal_year, b.fiscal_quarter) - qIndex(a.fiscal_year, a.fiscal_quarter)
  );
  return { row: sorted[0] ?? null, history: sorted, dropped };
}

export async function getFundamentals(code: string): Promise<FundamentalRow[]> {
  const { rows } = await selectWithOptionalColumns<FundamentalRow>(
    "quarterly_fundamentals",
    FUND_COLUMNS,
    (q, cols) =>
      q
        .select(cols)
        .eq("code", code)
        .order("fiscal_year", { ascending: true })
        .order("fiscal_quarter", { ascending: true })
  );
  return rows;
}

export async function getLatestPrice(code: string): Promise<PriceRow | null> {
  const { rows } = await selectWithOptionalColumns<PriceRow>(
    "price_snapshots",
    PRICE_COLUMNS,
    (q, cols) =>
      q.select(cols).eq("code", code).order("snap_date", { ascending: false }).limit(1)
  );
  return rows[0] ?? null;
}

export async function getAllLatestPrices(): Promise<{
  prices: Map<string, PriceRow>;
  dropped: string[];
}> {
  const { rows, dropped } = await selectWithOptionalColumns<PriceRow>(
    "price_snapshots",
    PRICE_COLUMNS,
    (q, cols) => q.select(cols).range(0, 4999)
  );
  // range(0,4999)로도 PostgREST는 1,000행씩만 줄 수 있다 — 잘리면 페이징으로 보강한다(T7).
  const all =
    rows.length >= 1000
      ? await selectAll<PriceRow>(
          "price_snapshots",
          PRICE_COLUMNS.filter((c) => !dropped.includes(c)).join(",")
        )
      : rows;
  const latest = new Map<string, PriceRow>();
  for (const row of all) {
    const prev = latest.get(row.code);
    if (!prev || row.snap_date > prev.snap_date) latest.set(row.code, row);
  }
  return { prices: latest, dropped };
}

/**
 * 분기말 종가 — 9분기 차트의 주가 라인.
 *
 * ★ 테이블 자체가 아직 없을 수 있다(마이그레이션 전). 그때는 **빈 맵**을 준다 —
 *   페이지 전체를 500으로 죽이지 않고 주가 라인만 빠지게 한다.
 *   키는 `qIndex`다. 연도 경계를 넘는 비교를 문자열로 하면 조용히 틀린다.
 */
export async function getQuarterPrices(code: string): Promise<Map<number, number>> {
  const out = new Map<number, number>();
  try {
    const { data, error } = await supabase
      .from("quarter_prices")
      .select("code,fiscal_year,fiscal_quarter,close,trade_date")
      .eq("code", code);
    if (error) return out;
    for (const row of (data as unknown as QuarterPriceRow[]) ?? []) {
      if (row.close != null) {
        out.set(qIndex(row.fiscal_year, row.fiscal_quarter), Number(row.close));
      }
    }
  } catch {
    return out;
  }
  return out;
}

/**
 * 그 종목의 DART 공시 — **최신순**. 첫 행이 '공시 원문' 링크가 된다.
 *
 * ★ 접수번호가 없으면 링크를 만들지 않는다. 회사명으로 DART 검색 URL을 조립하면
 *   200이 뜨지만 검색이 실행되지 않아 **빈 화면**이 나온다(T58).
 */
export async function getDisclosures(
  code: string,
  limit = 5
): Promise<DisclosureRow[]> {
  const { data, error } = await supabase
    .from("earnings_disclosures")
    .select("rcept_no,code,report_nm,doc_type,fiscal_year,fiscal_quarter,disclosed_at")
    .eq("code", code)
    .order("disclosed_at", { ascending: false })
    .limit(limit);
  if (error) return [];
  return (data as unknown as DisclosureRow[]) ?? [];
}

/**
 * 연간 컨센서스(`fiscal_quarter = 0`) — 선행 PER의 재료다.
 * 분기 컨센은 한 분기뿐이라 '향후 4분기'를 만들 수 없다.
 */
export async function getAnnualConsensus(
  code: string,
  fromYear: number
): Promise<ConsensusRow | null> {
  const { data, error } = await supabase
    .from("consensus_snapshots")
    .select("code,fiscal_year,fiscal_quarter,n_estimates,revenue_est,op_est,np_est")
    .eq("code", code)
    .eq("fiscal_quarter", 0)
    .gte("fiscal_year", fromYear)
    .order("fiscal_year", { ascending: true })
    .limit(1);
  if (error) return null;
  return ((data as unknown as ConsensusRow[]) ?? [])[0] ?? null;
}

export async function getConsensus(
  code: string,
  year: number,
  quarter: number
): Promise<ConsensusRow | null> {
  const { data, error } = await supabase
    .from("consensus_snapshots")
    .select("code,fiscal_year,fiscal_quarter,n_estimates,revenue_est,op_est,np_est")
    .eq("code", code)
    .eq("fiscal_year", year)
    .eq("fiscal_quarter", quarter)
    .limit(1);
  if (error) throw error;
  return ((data as unknown as ConsensusRow[]) ?? [])[0] ?? null;
}

/**
 * LLM 분석. `payload`는 **부분적으로만 채워질 수 있다**(§9.2 방어 1).
 * 상위 객체만 확인하고 하위를 읽으면 페이지 전체가 500이 난다 —
 * 읽는 쪽에서 필드 단위로 확인한다(`lib/analysis.ts`).
 */
export async function getAnalysis(
  code: string,
  year: number,
  quarter: number
): Promise<Record<string, unknown> | null> {
  const { data, error } = await supabase
    .from("analyses")
    .select("code,fiscal_year,fiscal_quarter,payload")
    .eq("code", code)
    .eq("fiscal_year", year)
    .eq("fiscal_quarter", quarter)
    .limit(1);
  if (error) throw error;
  const row = ((data as unknown as { payload: unknown }[]) ?? [])[0];
  return (row?.payload as Record<string, unknown>) ?? null;
}
