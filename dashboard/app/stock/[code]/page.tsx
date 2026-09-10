// PRD Ref: §9.1 — 종목 상세. **시스템의 핵심 화면.**
import Link from "next/link";
import { notFound } from "next/navigation";
import QuarterlyChart from "@/components/QuarterlyChart";
import WeeklyPriceChart from "@/components/WeeklyPriceChart";
import { CHART_QUARTERS, SERIES_COLOR, chartVerdict, measuredCount, toChartPoints } from "@/lib/chart";
import { GradeBadge, WarningBadges } from "@/components/Badges";
import { PriBreakdown, ScoreBreakdown } from "@/components/ScoreBreakdown";
import { Term, TermTh } from "@/components/Term";
import { type TimelineItem } from "@/components/TriggerTimeline";
import AnalysisSection from "@/components/AnalysisSection";
import Emphasized from "@/components/Emphasized";
import { readAnalysis } from "@/lib/analysis";
import { deriveOrderDisclosureSignal } from "@/lib/orderSignals";
import { checkNarrative } from "@/lib/narrativeCheck";
import { sectorOf } from "@/lib/sector";
import { growthCategory } from "@/lib/growthCategory";
import { dartReportUrl, naverStockUrl, stockeasyStockUrl } from "@/lib/links";
import { trailing4qPer, ttmNetIncome } from "@/lib/valuation";
import { DASH, eok, growthOrLabel, marketCap, num, pct, quarterLabel } from "@/lib/format";
import { getOutcomesForCode } from "@/lib/outcome";
import { getNaverLiveSnapshot } from "@/lib/naver";
import { metricMeanings } from "@/lib/metricMeaning";
import { normalizeWeeklyRows, technicalIndicators } from "@/lib/technicalIndicators";
import {
  getAnalysis,
  getAnnualConsensus,
  getConsensus,
  getDisclosures,
  getDisclosureExcerpt,
  getFundamentals,
  getFundamentalsForQuarters,
  getLatestAnalysis,
  getLatestPrice,
  getWeeklyPrices,
  getScreenForCode,
  getScreensForQuarter,
  getUniverse,
} from "@/lib/queries";

export const dynamic = "force-dynamic";

function Card({
  title,
  children,
  note,
  id,
}: {
  title: string;
  children: React.ReactNode;
  note?: string;
  id?: string;
}) {
  return (
    <section id={id} className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <h2 className="mb-3 text-sm font-semibold text-slate-100">
        {title}
        {note && <span className="ml-2 font-normal text-slate-300">{note}</span>}
      </h2>
      {children}
    </section>
  );
}

/** 카드 안에서 "이게 무슨 뜻인가"를 한 줄로 붙인다. 숫자만 있으면 읽히지 않는다. */
function Note({ children }: { children: React.ReactNode }) {
  return <p className="mt-3 text-xs leading-relaxed text-slate-300">{children}</p>;
}

function median(values: Array<number | null | undefined>): number | null {
  const measured = values
    .filter((value): value is number => value != null && Number.isFinite(value))
    .sort((left, right) => left - right);
  if (measured.length === 0) return null;
  const middle = Math.floor(measured.length / 2);
  return measured.length % 2
    ? measured[middle]
    : (measured[middle - 1] + measured[middle]) / 2;
}

export default async function StockPage({ params }: { params: { code: string } }) {
  const code = params.code;

  const [universe, funds, price, screenResult, weeklyPrices, disclosures, outcomeResult, naverLive] =
    await Promise.all([
      getUniverse(),
      getFundamentals(code),
      getLatestPrice(code),
      getScreenForCode(code),
      getWeeklyPrices(code),
      getDisclosures(code),
      getOutcomesForCode(code),
      getNaverLiveSnapshot(code),
    ]);

  const stock = universe.get(code);
  if (!stock) notFound();

  const screen = screenResult.row;
  const currentCategory = screen == null ? null : growthCategory(screen);
  const isGrowthAcceleration = currentCategory === "growth";
  const latestFund = funds[funds.length - 1] ?? null;
  const year = screen?.fiscal_year ?? latestFund?.fiscal_year ?? null;
  const quarter = screen?.fiscal_quarter ?? latestFund?.fiscal_quarter ?? null;

  const [
    consensus,
    analysisPayload,
    annualConsensus,
    disclosureExcerpt,
    quarterScreenResult,
    quarterFundamentals,
  ] = await Promise.all([
    year && quarter ? getConsensus(code, year, quarter) : Promise.resolve(null),
    isGrowthAcceleration && year && quarter ? getAnalysis(code, year, quarter) : Promise.resolve(null),
    year ? getAnnualConsensus(code, year) : Promise.resolve(null),
    year && quarter ? getDisclosureExcerpt(code, year, quarter) : Promise.resolve(null),
    year && quarter
      ? getScreensForQuarter(year, quarter)
      : Promise.resolve({ rows: [], dropped: [] }),
    year && quarter
      ? getFundamentalsForQuarters([{ year, quarter }])
      : Promise.resolve([]),
  ]);

  // ★ 한 분기 발췌이므로 변화율을 만들지 않는다. 평가 분기와 같은 원문만
  //   "다음 보고서에서 다시 볼 확인 포인트"로 쓴다(T99/T100).
  const orderSignal =
    year && quarter
      ? deriveOrderDisclosureSignal(disclosureExcerpt, year, quarter)
      : null;

  // ★★ 평가 분기의 분석이 없으면 **가장 최근 분석으로 물러선다.**
  //   분석은 게이트 통과 상위만 돌리므로(비용 설계), 새 실적이 들어와 평가 분기가
  //   옮겨가면 직전 분기 분석이 화면에서 통째로 사라졌다 — 실측 63종목이 그 상태로
  //   "아직 분석하지 않았다"를 띄우고 있었다.
  //   ★ 그리고 이 종목들이야말로 **내러티브를 검증할 수 있는 유일한 대상**이다.
  //     분석 이후 실제 실적이 나왔기 때문이다.
  //   ★ 어느 분기 분석인지를 화면에 반드시 밝힌다 — 안 밝히면 옛 해석을
  //     이번 분기 해석으로 읽게 된다.
  const fallback = isGrowthAcceleration && !analysisPayload ? await getLatestAnalysis(code) : null;
  const analysis = readAnalysis(analysisPayload ?? fallback?.payload ?? null);
  const analysisYear = analysisPayload ? year : fallback?.fiscal_year ?? null;
  const analysisQuarter = analysisPayload ? quarter : fallback?.fiscal_quarter ?? null;
  const analysisIsStale = Boolean(fallback);
  const storedAnalysis = (analysisPayload ?? fallback?.payload ?? null) as Record<string, unknown> | null;
  const analysisMeta = storedAnalysis?._heimdallr as Record<string, unknown> | undefined;
  const removedFactualNumbers = Array.isArray(analysisMeta?.removed_factual_numbers)
    ? analysisMeta.removed_factual_numbers.length
    : 0;
  const analyzedFund = analysisYear && analysisQuarter
    ? funds.find((f) => f.fiscal_year === analysisYear && f.fiscal_quarter === analysisQuarter)
    : null;
  const analysisStage =
    analysisMeta?.analysis_stage === "report_final"
      ? "(3단계) 정기보고서 후 5거래일·최근 10일 리포트 반영 완료"
      : analysisMeta?.analysis_stage === "filing" || analysisMeta?.analysis_stage === "final"
        ? "(2단계) 분기/반기/사업보고서 공시 분석"
      : analysisMeta?.analysis_stage === "preliminary"
        ? "(1단계) 잠정실적 발표 초기 분석"
        : storedAnalysis && analyzedFund?.is_estimate
          ? "(1단계) 잠정실적 발표 초기 분석 · 단계 메타 보강 대기"
          : storedAnalysis
            ? "(2단계) 정기보고서 공시 분석 · 단계 메타 보강 대기"
            : "(1단계) 성장 가속 분석 대기";
  const analysisStageClass =
    analysisMeta?.analysis_stage === "report_final"
      ? "border-emerald-700 bg-emerald-950/30 text-emerald-200"
      : analysisMeta?.analysis_stage === "filing" || analysisMeta?.analysis_stage === "final"
        ? "border-sky-700 bg-sky-950/30 text-sky-200"
      : analysisMeta?.analysis_stage === "preliminary"
        ? "border-amber-700 bg-amber-950/30 text-amber-200"
        : storedAnalysis
          ? "border-amber-700 bg-amber-950/30 text-amber-200"
        : "border-slate-700 bg-slate-950/30 text-slate-300";
  const analysisStageCode = String(
    analysisMeta?.analysis_stage ??
      (storedAnalysis ? (analyzedFund?.is_estimate ? "preliminary" : "filing") : "")
  );
  const analysisStageRank = analysisStageCode === "report_final"
    ? 3
    : analysisStageCode === "filing" || analysisStageCode === "final"
      ? 2
      : analysisStageCode === "preliminary"
        ? 1
        : 0;
  const stageHistory = analysisMeta?.stage_history && typeof analysisMeta.stage_history === "object"
    ? analysisMeta.stage_history as Record<string, unknown>
    : {};
  const lastAttempt = analysisMeta?.last_attempt && typeof analysisMeta.last_attempt === "object"
    ? analysisMeta.last_attempt as Record<string, unknown>
    : {};
  const completedAt = (stage: string): string | null => {
    const stored = stageHistory[stage];
    if (typeof stored === "string") return stored.slice(0, 10);
    return lastAttempt.stage === stage && typeof lastAttempt.attempted_at === "string"
      ? lastAttempt.attempted_at.slice(0, 10)
      : null;
  };
  const flashDisclosureDate = disclosures
    .filter((row) =>
      row.fiscal_year === analysisYear && row.fiscal_quarter === analysisQuarter &&
      row.doc_type !== "periodic" && /잠정|영업\(잠정\)실적/.test(row.report_nm ?? "")
    )
    .map((row) => row.disclosed_at?.slice(0, 10) ?? "")
    .filter(Boolean)
    .sort()[0] ?? null;
  const periodicDisclosureDate = disclosures
    .filter((row) =>
      row.fiscal_year === analysisYear && row.fiscal_quarter === analysisQuarter &&
      row.doc_type === "periodic"
    )
    .map((row) => row.disclosed_at?.slice(0, 10) ?? "")
    .filter(Boolean)
    .sort()
    .at(-1) ?? null;
  const analysisSteps = [
    {
      key: "preliminary",
      title: "1단계 · 잠정실적",
      trigger: flashDisclosureDate ? `${flashDisclosureDate} 최초 잠정실적 발표` : "최초 잠정실적 발표 즉시",
      status: completedAt("preliminary")
        ? `${completedAt("preliminary")} 분석 완료`
        : analysisStageRank > 1
          ? "정기보고서 단계부터 직접 분석"
          : analysisStageRank === 1
            ? "분석 완료"
            : "발표·선별 대기",
      tone: analysisStageRank === 1 ? "border-amber-500 bg-amber-950/30" : "border-slate-700 bg-slate-950/30",
    },
    {
      key: "filing",
      title: "2단계 · 정기보고서",
      trigger: periodicDisclosureDate ? `${periodicDisclosureDate} 분기/반기/사업보고서 공시` : "정기보고서 공시 즉시",
      status: completedAt("filing")
        ? `${completedAt("filing")} 분석 완료`
        : analysisStageRank >= 2
          ? "분석 완료"
          : periodicDisclosureDate
            ? "확정 재무·공시 발췌 반영 대기"
            : "공시 대기",
      tone: analysisStageRank === 2 ? "border-sky-500 bg-sky-950/30" : "border-slate-700 bg-slate-950/30",
    },
    {
      key: "report_final",
      title: "3단계 · 리포트 최종",
      trigger: "2단계 뒤 5거래일 · 최근 10일 리포트 검색",
      status: completedAt("report_final")
        ? `${completedAt("report_final")} 최종 분석 완료`
        : analysisStageRank >= 3
          ? "최종 분석 완료"
          : analysisStageRank === 2
            ? "5거래일 창 완료 대기"
            : "2단계 완료 대기",
      tone: analysisStageRank === 3 ? "border-emerald-500 bg-emerald-950/30" : "border-slate-700 bg-slate-950/30",
    },
  ];

  // 스크리너가 평가한 바로 그 분기의 재무를 쓴다 — 최신 행과 다를 수 있다.
  const evaluated =
    year && quarter
      ? funds.find((f) => f.fiscal_year === year && f.fiscal_quarter === quarter) ?? latestFund
      : latestFund;

  // 상세 화면의 현재가·PER·F.PER·ROE는 같은 네이버 공개 JSON을 우선한다.
  // 네이버가 실패한 경우에만 마지막 DB 스냅샷으로 물러서고 그 기준일을 밝힌다.
  const liveQuote = naverLive?.quoteAvailable === true;
  const liveAnnual = naverLive?.annualAvailable === true;
  const currentClose = liveQuote ? naverLive.close : price?.close ?? null;
  const currentChgPct = liveQuote ? naverLive.chgPct : price?.chg_pct ?? null;
  const currentMarketCap = liveQuote
    ? naverLive.marketCapKrw ?? price?.market_cap_krw ?? stock.market_cap_krw
    : price?.market_cap_krw ?? stock.market_cap_krw;
  const currentHigh52w = liveQuote ? naverLive.high52w : price?.high_52w ?? null;
  const currentLow52w = liveQuote ? naverLive.low52w : price?.low_52w ?? null;
  const currentPos52w =
    currentClose != null && currentHigh52w != null && currentLow52w != null && currentHigh52w > currentLow52w
      ? (currentClose - currentLow52w) / (currentHigh52w - currentLow52w)
      : price?.pos_52w ?? null;
  const priceBasisDate = liveQuote ? naverLive.priceDate : price?.snap_date ?? null;
  const priceBasisLabel = liveQuote ? "네이버 현재 시세(최대 1분 캐시)" : "마지막 저장 시세";

  // ── 섹터 비교 ────────────────────────────────────────────────
  // 같은 평가 분기의 행끼리만 비교한다(T40). 상위 5개에 현재 종목이 없으면
  // 현재 종목을 한 줄 더 붙여 위치를 잃지 않게 한다.
  const stockSector = sectorOf(stock);
  const quarterFundByCode = new Map(quarterFundamentals.map((row) => [row.code, row]));
  const sectorScreens = quarterScreenResult.rows
    .filter((row) => sectorOf(universe.get(row.code)) === stockSector)
    .sort(
      (left, right) =>
        (right.score_final ?? right.score_flash ?? -Infinity) -
        (left.score_final ?? left.score_flash ?? -Infinity)
    );
  const topSectorScreens = sectorScreens.slice(0, 5);
  const currentSectorScreen = sectorScreens.find((row) => row.code === code);
  const displayedSectorScreens =
    currentSectorScreen && !topSectorScreens.some((row) => row.code === code)
      ? [...topSectorScreens, currentSectorScreen]
      : topSectorScreens;
  const sectorPeerRows = await Promise.all(
    displayedSectorScreens.map(async (peerScreen) => {
      const isCurrent = peerScreen.code === code;
      const [peerFunds, peerPrice, peerAnnual] = isCurrent
        ? [funds, price, annualConsensus]
        : await Promise.all([
            getFundamentals(peerScreen.code),
            getLatestPrice(peerScreen.code),
            year ? getAnnualConsensus(peerScreen.code, year) : Promise.resolve(null),
          ]);
      const peerFund = quarterFundByCode.get(peerScreen.code) ?? null;
      const peerCap =
        isCurrent
          ? currentMarketCap
          : peerPrice?.market_cap_krw ?? universe.get(peerScreen.code)?.market_cap_krw ?? null;
      const peerTtmNp =
        year && quarter ? ttmNetIncome(peerFunds, year, quarter) : null;
      return {
        code: peerScreen.code,
        name: universe.get(peerScreen.code)?.name ?? peerScreen.code,
        isCurrent,
        marketCap: peerCap,
        revenue: peerFund?.revenue ?? null,
        op: peerFund?.op ?? null,
        opm: peerFund?.opm ?? null,
        roeCurrent: isCurrent && liveAnnual ? naverLive.roe : peerAnnual?.roe_est ?? null,
        roeNext: isCurrent && liveAnnual ? naverLive.roeNext : peerAnnual?.roe_next_est ?? null,
        roeNextYear: isCurrent && liveAnnual ? naverLive.roeNextYear : peerAnnual?.roe_next_year ?? null,
        per4q: isCurrent && liveQuote ? naverLive.per4q : trailing4qPer(peerCap, peerTtmNp),
        forwardPer: isCurrent && liveQuote ? naverLive.fwdPer : peerAnnual?.fwd_per ?? null,
      };
    })
  );
  const sectorMedians = {
    marketCap: median(sectorPeerRows.map((row) => row.marketCap)),
    revenue: median(sectorPeerRows.map((row) => row.revenue)),
    op: median(sectorPeerRows.map((row) => row.op)),
    opm: median(sectorPeerRows.map((row) => row.opm)),
    roeCurrent: median(sectorPeerRows.map((row) => row.roeCurrent)),
    roeNext: median(sectorPeerRows.map((row) => row.roeNext)),
    per4q: median(sectorPeerRows.map((row) => row.per4q)),
    forwardPer: median(sectorPeerRows.map((row) => row.forwardPer)),
  };

  // ── 밸류에이션 ──────────────────────────────────────────────
  // ★ 시총은 시세 스냅샷 것을 우선한다 — 유니버스 값은 하루 늦을 수 있다.
  const capForPer = currentMarketCap;
  // ★ 평가 분기까지의 4분기 누적으로 잡는다. 그냥 마지막 4행을 쓰면 스크리너가
  //   본 분기와 다른 구간의 PER이 나와 텔레그램과 화면이 어긋난다.
  const ttmNp =
    year && quarter ? ttmNetIncome(funds, year, quarter) : null;
  const calculatedPer4q = trailing4qPer(capForPer, ttmNp);
  // 투자지표의 주 원천은 네이버다. 실시간 integration이 실패하면 저장된
  // 네이버 연간 스냅샷으로 물러서고, 다른 출처의 PER을 섞지 않는다.
  const per4q = liveQuote ? naverLive.per4q : annualConsensus?.per ?? null;
  const forwardPerValue = liveQuote ? naverLive.fwdPer : annualConsensus?.fwd_per ?? null;
  const currentRoe = liveAnnual ? naverLive.roe : annualConsensus?.roe_est ?? null;
  const currentRoeYear = liveAnnual ? naverLive.roeYear : annualConsensus?.fiscal_year ?? null;
  const nextRoe = liveAnnual ? naverLive.roeNext : annualConsensus?.roe_next_est ?? null;
  const nextRoeYear = liveAnnual ? naverLive.roeNextYear : annualConsensus?.roe_next_year ?? null;
  // PEG는 네이버 integration이 공개한 값만 사용한다. 공개하지 않는 종목은 결측이다.
  const referencePeg = liveQuote ? naverLive.peg : null;

  const chartPoints = toChartPoints(funds, CHART_QUARTERS);
  const chartStartFund = funds.slice(-CHART_QUARTERS)[0];
  const weeklyFromDate = chartStartFund
    ? `${chartStartFund.fiscal_year}-${String((chartStartFund.fiscal_quarter - 1) * 3 + 1).padStart(2, "0")}-01`
    : undefined;
  const visibleTechnicalPoints = technicalIndicators(normalizeWeeklyRows(weeklyPrices))
    .filter((point) => !weeklyFromDate || point.trade_date >= weeklyFromDate);
  const meanings = metricMeanings(chartPoints, visibleTechnicalPoints);

  // 트리거는 3개월·6개월 구간을 한 타임라인에 합친다 — 사람은 구간이 아니라
  // 시간 순서로 읽는다. 어느 구간에서 왔는지는 칩으로 남긴다.
  const timelineItems: TimelineItem[] = [
    ...analysis.triggers3m.map((t) => ({ ...t, window: "3개월 내", tone: "near" as const })),
    ...analysis.triggers6m.map((t) => ({ ...t, window: "6개월 내", tone: "far" as const })),
  ];
  // ★ 차트 한 줄 해설 — **영업이익 YoY 가속이 핵심**이다(사용자 지정).
  //   규칙 기반이라 차트에 실제로 그려진 숫자에서만 나온다.
  const verdict = chartVerdict(chartPoints);

  // ★ LLM이 쓴 스토리가 그 뒤 실적으로 확인되는가. 분석 이후 발표된 분기와만 대조한다.
  // ★★ 기준은 **분석이 실제로 본 분기**다(`analysisYear/Quarter`). 스크리너의 평가
  //   분기를 넘기면, 옛 분석을 최신 분기 것으로 착각해 "검증 대기"만 나온다 —
  //   검증이 가능한 종목에서 정확히 검증이 꺼지는 셈이다.
  const narrative = checkNarrative(analysis, funds, analysisYear, analysisQuarter);

  const opYoyMeasured = measuredCount(chartPoints, "opYoy");
  const revYoyMeasured = measuredCount(chartPoints, "revenueYoy");

  // ★ DART 원문은 **접수번호로만** 열린다. 회사명 검색 URL은 200을 주고도
  //   검색을 실행하지 않아 빈 화면이 뜬다(T58) — 없으면 링크를 만들지 않는다.
  const latestDisclosure = disclosures[0] ?? null;
  const baseEffectMeasurable = Boolean(
    (screen?.gate_detail as Record<string, unknown> | null)?.base_effect_measurable ?? true
  );

  return (
    <div className="space-y-5">
      {/* 1. 헤더 */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">
            {stock.name} <span className="text-slate-300">{code}</span>
          </h1>
          <p className="mt-1 text-sm text-slate-200">
            {stock.board} · {stock.industry ?? DASH} · 시총 {marketCap(currentMarketCap)}
          </p>
          {stock.products && (
            <p className="mt-1 text-xs text-slate-300">{stock.products}</p>
          )}
        </div>
        <div className="text-right">
          <div className="text-2xl font-semibold">{num(currentClose)}원</div>
          <div className="text-sm text-slate-200">{pct(currentChgPct, 2)}</div>
          <div className="mt-0.5 text-[11px] font-medium text-emerald-300">
            {priceBasisDate ?? "기준일 미상"} 기준 · {priceBasisLabel}
          </div>
          <div className="mt-1 text-xs text-slate-300">
            52주 {num(currentLow52w)} ~ {num(currentHigh52w)}
            {currentPos52w != null && ` (위치 ${(currentPos52w * 100).toFixed(0)}%)`}
          </div>
          <div className="text-xs text-slate-300">
            3개월 지수대비 {pct(price?.rel_ret_3m, 1, "%p")}
          </div>
        </div>
      </div>

      <div className="grid gap-2 text-sm sm:grid-cols-3 lg:grid-cols-6">
        {[
          ["3개월 절대", price?.ret_3m],
          ["3개월 지수대비", price?.rel_ret_3m],
          ["6개월 절대", price?.ret_6m],
          ["6개월 지수대비", price?.rel_ret_6m],
          ["12개월 절대", price?.ret_12m],
          ["12개월 지수대비", price?.rel_ret_12m],
        ].map(([label, value]) => (
          <div key={String(label)} className="rounded border border-slate-800 bg-slate-900/40 px-3 py-2">
            <div className="text-xs text-slate-300">{label}</div>
            <div className="mt-0.5 font-semibold text-slate-100">
              {pct(
                value as number | null | undefined,
                1,
                String(label).includes("지수대비") ? "%p" : "%"
              )}
            </div>
          </div>
        ))}
      </div>

      {screenResult.dropped.length > 0 && (
        <p className="rounded border border-amber-800/60 bg-amber-900/20 px-3 py-2 text-xs text-amber-300">
          ⚠ 아직 DB에 없는 컬럼을 제외하고 조회했다: {screenResult.dropped.join(", ")}.
          스키마 마이그레이션이 적용되면 사라진다.
        </p>
      )}

      {/* 2. 판정 카드 */}
      <Card
        title="판정"
        note={year && quarter ? `${quarterLabel(year, quarter)} 기준` : undefined}
      >
        {screen ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <GradeBadge grade={screen.grade} />
              <span className="text-sm text-slate-200">
                {currentCategory === "growth" ? "성장 가속" : currentCategory === "turnaround" ? "턴어라운드" : currentCategory === "revenue_slow_op_accel" ? "매출 둔화 + 영익 가속" : "기타"}
              </span>
              {screen.turnaround && (
                <span className="rounded border border-emerald-800/60 bg-emerald-900/20 px-2 py-0.5 text-xs text-emerald-300">
                  흑전/적자축소
                </span>
              )}
              {screen.pctile_in_quarter != null && (
                <span className="rounded border border-sky-800/60 bg-sky-900/20 px-2 py-0.5 text-xs text-sky-200">
                  분기 내 백분위 {screen.pctile_in_quarter.toFixed(1)}%
                </span>
              )}
            </div>
            <WarningBadges
              baseEffectWarning={screen.base_effect_warning}
              baseEffectMeasurable={baseEffectMeasurable}
              sectorCaveat={stock.sector_caveat}
              hasConsensus={screen.has_consensus}
              isEstimate={evaluated?.is_estimate ?? null}
            />
            <div className="grid gap-6 md:grid-cols-2">
              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase text-slate-200">기업 투자 매력도</h3>
                <Note>
                  산업·실적·밸류·ROE·현금흐름 종합 100점 · 미측정 축은 0점이 아니라{" "}
                  <strong className="text-slate-100">분모 제외</strong>
                </Note>
                <div className="mt-2">
                  <ScoreBreakdown screen={screen} />
                </div>
              </div>
              <div>
                <h3 className="mb-1 text-xs font-semibold uppercase text-slate-200">
                  주가반영도 (PRI)
                </h3>
                {/* ★ 숫자 바로 아래에 뜻을 붙인다 — 62점이 좋은 건지 나쁜 건지가
                    이 화면에서 가장 자주 막히는 지점이다. */}
                <Note>
                  <span className="block text-slate-100">
                    주가가 아는 정도 (0~100) ·{" "}
                    <strong className="text-amber-300">낮을수록 아직 안 올랐다</strong>
                  </span>
                  <span className="block">0~39 미반영 · 40~65 부분반영 · 66~100 선반영</span>
                  <span className="block">기업 점수와 <strong>합산하지 않는다</strong> · ★ = 기업 매력 높음 + 반영도 낮음</span>
                </Note>
                <div className="mt-2">
                  <PriBreakdown pri={screen.pri} detail={screen.pri_detail} />
                </div>
              </div>
            </div>
          </div>
        ) : (
          <p className="text-sm text-slate-300">스크리닝 결과가 없다.</p>
        )}
      </Card>

      {/* 3. 10분기 차트 — 성장률 라인이 주인공 */}
      <Card
        id="quarterly-trend"
        title={`분기 실적 추이 (${CHART_QUARTERS}분기)`}
        note="분기별 값 라벨 · 매출액 YoY와 영업이익 YoY를 같은 좌표에서 비교"
      >
        <QuarterlyChart points={chartPoints} />
        <WeeklyPriceChart points={weeklyPrices} fromDate={weeklyFromDate} />
        <Note>실제 주간 종가는 위 분기 실적 차트의 시작 분기부터 현재까지 같은 기간만 표시한다. 각 점은 ISO 주의 마지막 실제 거래일 종가다.</Note>

        {/* ★★ 핵심 투자 포인트 — **모양이 무엇을 뜻하는가**(사용자 지정 2026-08-23).
            "성장률이 빨라졌다"는 차트를 보면 누구나 아는 사실이다. 화면이 보태야 하는
            것은 그 다음 — 왜 그 모양이 중요한가. 규칙 기반이라 LLM을 쓰지 않는다. */}
        <div
          className={`mt-3 rounded-lg border-l-4 p-4 ${
            {
              accel: "border-amber-400 bg-amber-950/25",
              flat: "border-slate-500 bg-slate-900/40",
              slow: "border-sky-500 bg-sky-950/20",
              unknown: "border-slate-600 bg-slate-900/40",
            }[verdict.tone]
          }`}
        >
          <p className="text-base font-bold leading-relaxed text-slate-100">
            <Emphasized text={verdict.headline} tone={verdict.tone} />
          </p>
          <p className="mt-1.5 font-mono text-xs text-slate-200">{verdict.evidence}</p>

          <div className="mt-3 border-t border-slate-700/70 pt-3">
            <div className="text-[11px] font-bold uppercase tracking-wide text-amber-300">
              이 모양이 뜻하는 것
            </div>
            <p className="mt-1 text-sm leading-relaxed text-slate-100">
              <Emphasized text={verdict.meaning} tone={verdict.tone} />
            </p>
          </div>

          <div className="mt-2.5 rounded bg-slate-950/50 px-3 py-2">
            <span className="mr-1.5 text-[11px] font-bold text-sky-300">다음에 볼 것</span>
            <span className="text-sm text-slate-100">
              <Emphasized text={verdict.watch} tone={verdict.tone} />
            </span>
          </div>
        </div>

        <div className="mt-4">
          <h3 className="mb-2 text-sm font-semibold text-slate-100">현재 위치에서 각 지표가 뜻하는 것</h3>
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {meanings.map((item) => (
              <div key={item.label} className="rounded border border-slate-800 bg-slate-950/40 p-3">
                <div className="text-xs font-bold text-sky-200">{item.label}</div>
                <div className="mt-1 text-sm font-semibold text-slate-100">{item.value}</div>
                <p className="mt-1 text-xs leading-relaxed text-slate-300">{item.meaning}</p>
                <p className="mt-2 text-[11px] leading-relaxed text-amber-200">다음 확인: {item.watch}</p>
              </div>
            ))}
          </div>
        </div>

        <Note>
          <span className="text-slate-100">
            항목 순서: <strong>매출액 → 영업이익·OPM → 매출액·영업이익 YoY → 수주잔고·신규수주 → 실제 주간 종가·MACD·RSI</strong>.
            두 YoY는 실제 %를 같은 좌표에 놓고 모든 원값을 바로 아래에 병기한다. 수주 수치는
            단위를 확인한 구조화 값만 표시한다.
          </span>
          <span className="mt-1 block">
            측정 {opYoyMeasured}/{chartPoints.length}(영업익) · {revYoyMeasured}/
            {chartPoints.length}(매출) · OPM {chartPoints.filter((p) => p.opm != null).length}/{chartPoints.length}
            {opYoyMeasured < chartPoints.length && " · 빈 칸은 흑↔적 전환(0%가 아니다)"}
          </span>
        </Note>
      </Card>

      {/* 4. 분기 히스토리 표 */}
      <Card id="quarterly-history" title="분기 히스토리">
        <Note>
          <strong className="text-slate-100">흑전/적전</strong> 흑↔적 전환(%계산 불가) ·{" "}
          <strong className="text-slate-100">QoQ</strong> 참고용(점수 미반영)
        </Note>
        {/* ★ 높이를 제한해야 sticky가 먹는다 — `overflow-x-auto`만으로는
            세로 스크롤 영역이 만들어지지 않아 머리글이 그냥 밀려 올라간다(T64). */}
        <div className="mt-3 max-h-[60vh] overflow-auto">
          <table className="w-full min-w-[980px] text-right text-sm">
            <thead className="sticky top-0 z-20 bg-slate-900 text-xs uppercase text-slate-200 shadow-[0_1px_0_0_rgba(148,163,184,0.35)]">
              <tr className="border-b border-slate-800">
                <TermTh term="분기">분기</TermTh>
                <TermTh term="매출액" align="right">매출</TermTh>
                <TermTh term="YoY" align="right">매출 YoY</TermTh>
                <TermTh term="QoQ" align="right">매출 QoQ</TermTh>
                <TermTh term="영업이익" align="right">영업이익</TermTh>
                <TermTh term="YoY" align="right">영업이익 YoY</TermTh>
                <TermTh term="QoQ" align="right">영업이익 QoQ</TermTh>
                <TermTh term="OPM" align="right">OPM</TermTh>
                <TermTh term="FCF" align="right">FCF</TermTh>
                <TermTh term="잠정" align="center">구분</TermTh>
              </tr>
            </thead>
            <tbody>
              {[...funds].reverse().slice(0, CHART_QUARTERS).map((f) => (
                <tr
                  key={`${f.fiscal_year}-${f.fiscal_quarter}`}
                  className="border-b border-slate-800/60"
                >
                  <td className="py-1.5 text-left text-slate-100">
                    {quarterLabel(f.fiscal_year, f.fiscal_quarter)}
                  </td>
                  <td className="py-1.5">{eok(f.revenue)}</td>
                  <td className="py-1.5">{pct(f.revenue_yoy)}</td>
                  <td className="py-1.5">{pct(f.revenue_qoq)}</td>
                  <td className="py-1.5">{eok(f.op)}</td>
                  {/* ★ 부호 전환 구간은 %가 아니라 라벨이다(T25) */}
                  <td className="py-1.5">{growthOrLabel(f.op_yoy, f.op_status_label)}</td>
                  <td className="py-1.5">{pct(f.op_qoq)}</td>
                  <td className="py-1.5">{pct(f.opm)}</td>
                  <td className="py-1.5">{eok(f.fcf)}</td>
                  <td className="py-1.5 text-center text-xs text-slate-300">
                    {f.is_estimate ? "잠정" : "확정"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* ★★ 5. LLM 분석 — **분기 히스토리 바로 아래**다(사용자 지정 2026-08-22).
          숫자를 본 직후에 해석을 읽어야 대조가 된다. 밸류에이션·컨센서스를 지나
          맨 아래에 있으면 스크롤을 내리는 동안 방금 본 숫자를 잊는다. */}
      {isGrowthAcceleration ? <Card
        id="llm-analysis"
        title="LLM 분석"
        note={
          analysisYear && analysisQuarter
            ? `${quarterLabel(analysisYear, analysisQuarter)} 기준`
            : undefined
        }
      >
        <p className={"mb-3 inline-flex rounded border px-2 py-1 text-xs font-semibold " + analysisStageClass}>
          {analysisStage}
        </p>
        <div className="mb-3 grid gap-2 md:grid-cols-3">
          {analysisSteps.map((step) => (
            <div key={step.key} className={`rounded border p-3 ${step.tone}`}>
              <div className="text-xs font-bold text-slate-100">{step.title}</div>
              <div className="mt-1 text-[11px] leading-relaxed text-slate-300">시점: {step.trigger}</div>
              <div className="mt-2 text-xs font-semibold text-slate-100">{step.status}</div>
            </div>
          ))}
        </div>
        <p className="mb-3 text-xs leading-relaxed text-slate-300">
          각 단계는 같은 분기의 최신 해석으로 갱신된다. 1단계는 잠정 숫자, 2단계는 확정 재무와
          정기보고서 발췌, 3단계는 정기보고서 뒤 5거래일 동안 나온 최근 10일 증권사 리포트를
          반영한다. 시세 변화만으로는 재호출하지 않으며, 동일 단계·동일 근거의 실패도 반복 결제하지 않는다.
        </p>
        {removedFactualNumbers > 0 && (
          <p className="mb-3 rounded border border-slate-700 bg-slate-950/40 px-3 py-2 text-xs text-slate-300">
            입력에서 확인되지 않은 LLM 생성 숫자 {removedFactualNumbers}개를 자동 제거했다.
            정량 판단은 위 재무·주가 화면의 확정값을 기준으로 한다.
          </p>
        )}
        {analysisIsStale && analysisYear && analysisQuarter && (
          <p className="mb-3 rounded border border-amber-700/70 bg-amber-950/30 px-3 py-2 text-xs text-amber-200">
            ⚠ 이 해석은 <strong>{quarterLabel(analysisYear, analysisQuarter)}</strong> 기준이다 —
            그 뒤 {year && quarter ? quarterLabel(year, quarter) : "새 분기"} 실적이 나왔지만
            아직 다시 분석하지 않았다(성장 가속 종목만 분석한다).{" "}
            <strong className="text-amber-100">
              그래서 아래 내러티브 검증이 실제로 대조를 수행한다.
            </strong>
          </p>
        )}
        <AnalysisSection
          analysis={analysis}
          narrative={narrative}
          timelineItems={timelineItems}
          /* ★ 배수는 **화면이 계산한 값**을 넘긴다 — LLM 본문의 PER은 믿지 않는다. */
          valuation={{
            per4q,
            perForward: forwardPerValue,
            forwardBasis: liveQuote ? "네이버 증권 추정 PER" : "네이버 연간 컨센서스",
            roeCurrent: currentRoe,
            roeNext: nextRoe,
          }}
        />
      </Card> : <Card title="LLM 분석 제외">
        <p className="text-sm text-slate-300">
          이 종목은 현재 <strong className="text-slate-100">성장 가속</strong> 분류가 아니므로
          데이터 수집·스크리닝·차트·공시 갱신은 계속 수행하고 LLM 분석만 실행하지 않는다.
        </p>
      </Card>}

      {/* 공시에서 실제 수주 언어가 잡힌 종목에만 보인다. 목록 QoQ 컬럼이 아니다. */}
      {orderSignal && (
        <Card title="수주 확인 포인트" note={orderSignal.sourceLabel}>
          <div className="rounded-lg border border-sky-800/70 bg-sky-950/25 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded border border-sky-600/70 bg-sky-900/30 px-2 py-0.5 text-xs font-semibold text-sky-100">
                다음 정기보고서에서 재확인
              </span>
              {orderSignal.status === "limited" && (
                <span className="rounded border border-amber-600/70 bg-amber-900/30 px-2 py-0.5 text-xs text-amber-200">
                  비공개·판정 제한
                </span>
              )}
              {orderSignal.truncated && (
                <span className="rounded border border-amber-600/70 bg-amber-900/30 px-2 py-0.5 text-xs text-amber-200">
                  발췌 잘림
                </span>
              )}
            </div>
            <p className="mt-2 text-sm leading-relaxed text-slate-100">
              <Emphasized text={orderSignal.evidence} />
            </p>
            <Note>
              이 문장은 <strong className="text-slate-100">같은 분기 DART 발췌</strong>에서
              찾은 확인 신호다. 발췌가 한 분기뿐이라 <strong className="text-amber-200">QoQ나
              증가 판정이 아니며</strong>, 다음 보고서에서 수주잔고·신규 계약이 실제로
              이어지는지 원문으로 대조한다.
            </Note>
          </div>
        </Card>
      )}

      {/* 6. 컨센서스 대비 */}
      <Card title="컨센서스 대비">
        <Note>출처: 네이버 증권 기업실적분석 · 스냅샷 {consensus?.snapshot_at?.slice(0, 10) ?? DASH} · 추정기관 2곳 이상만 인정</Note>
        <div className="mt-3" />
        {consensus && (consensus.n_estimates ?? 0) >= 2 ? (
          <div className="grid gap-4 text-sm sm:grid-cols-3">
            <div>
              <div className="text-xs text-slate-300">추정기관 수</div>
              <div className="text-lg">{consensus.n_estimates}곳</div>
            </div>
            <div>
              <div className="text-xs text-slate-300">매출 서프라이즈</div>
              <div className="text-lg">
                {consensus.revenue_est && evaluated?.revenue
                  ? pct(((evaluated.revenue - consensus.revenue_est) / consensus.revenue_est) * 100)
                  : DASH}
              </div>
              <div className="text-xs text-slate-300">컨센 {eok(consensus.revenue_est)}</div>
            </div>
            <div>
              <div className="text-xs text-slate-300">영업이익 서프라이즈</div>
              <div className="text-lg">
                {/* 부호가 바뀌면 %를 만들지 않는다(T37) */}
                {consensus.op_est != null &&
                evaluated?.op != null &&
                consensus.op_est > 0 &&
                evaluated.op > 0
                  ? pct(((evaluated.op - consensus.op_est) / consensus.op_est) * 100)
                  : consensus.op_est != null && evaluated?.op != null
                    ? consensus.op_est <= 0 && evaluated.op > 0
                      ? "흑전 서프라이즈"
                      : "적자 구간 — % 계산 불가"
                    : DASH}
              </div>
              <div className="text-xs text-slate-300">컨센 {eok(consensus.op_est)}</div>
            </div>
          </div>
        ) : (
          <p className="text-sm text-slate-200">
            <strong className="text-slate-100">커버리지 없음.</strong> 추정기관이 2곳 미만이라
            컨센서스로 인정하지 않는다. C축을 <strong>분모에서 제외</strong>하고 정규화했다 —
            0점 처리가 아니다(ADR 2). 코스닥 상장사의 약 60%가 최근 1년 리포트 0건이며,
            이 시스템은 그 구간을 발굴 대상으로 삼는다.
          </p>
        )}
      </Card>

      {/* 7. 밸류에이션 — 최근 4분기 → 향후 4분기 순. 후행 PER은 싣지 않는다. */}
      <Card title="가치와 가격 비교" note="실적이 만든 가치와 시장이 붙인 가격을 반드시 함께 본다">
        <p className="mb-4 rounded border border-amber-700/60 bg-amber-950/25 px-3 py-2 text-sm leading-relaxed text-amber-100">
          <strong>현재 가격 {currentClose != null ? `${currentClose.toLocaleString("ko-KR")}원` : DASH}</strong>
          {priceBasisDate && ` (${priceBasisDate} 기준)`} ·
          최근 4분기 이익 기준 {per4q != null ? `${per4q.toFixed(2)}배` : DASH} ·
          네이버 F.PER {forwardPerValue != null ? `${forwardPerValue.toFixed(2)}배` : DASH}.
          이익 성장으로 배수가 낮아지는지와 PRI가 낮아 아직 가격이 덜 움직였는지를 함께 비교한다.
        </p>
        <div className="grid gap-5 text-sm sm:grid-cols-2 xl:grid-cols-5">
          <div className="rounded border border-slate-800 bg-slate-950/40 p-3">
            <div className="text-xs font-semibold text-slate-200">
              ① 최근 4개 분기 순이익 PER
            </div>
            <div className="mt-1 text-2xl font-semibold text-slate-100">
              {per4q != null ? per4q.toFixed(2) + "배" : DASH}
            </div>
            <p className="mt-1 text-xs leading-relaxed text-slate-300">
              {liveQuote ? <>
                출처: <strong>네이버 증권 현재 PER</strong>({priceBasisDate ?? "기준일 미상"}). 네이버가
                최근 4분기 지배주주 순이익과 수정 평균 발행 주 수로 계산한 값을 그대로 표시한다.
                {calculatedPer4q != null && <> DART·현재 시총 검산값은 {calculatedPer4q.toFixed(2)}배다.</>}
              </> : <>
                네이버 현재 조회가 실패해 DART 최근 4분기 순이익과 마지막 저장 시총으로 계산했다.
                {ttmNp != null && <> 분모는 {eok(ttmNp)}({quarterLabel(year ?? 0, quarter ?? 0)}까지 4분기 누적).</>}
              </>}
              {per4q == null && (
                <> 4개 분기가 다 모이지 않았거나 누적 순이익이 0 이하라 계산하지 않았다 —
                  연율화해서 만들어내지 않는다.</>
              )}
            </p>
          </div>
          <div className="rounded border border-slate-800 bg-slate-950/40 p-3">
            <div className="text-xs font-semibold text-slate-200">
              ② <Term term="PER선행">F.PER(선행)</Term>
            </div>
            <div className="mt-1 text-2xl font-semibold text-slate-100">
              {forwardPerValue != null ? forwardPerValue.toFixed(2) + "배" : DASH}
            </div>
            <p className="mt-1 text-xs leading-relaxed text-slate-300">
              출처: <strong>네이버 증권 추정PER</strong>({priceBasisDate ?? "기준일 미상"}). 최근
              3개월 증권사 예상 EPS 평균이며 네이버 공개값을 변형하지 않았다.
              {!liveQuote && annualConsensus?.fwd_per == null ? (
                <> <strong className="text-slate-200">연간 컨센서스가 없어 계산하지 않았다.</strong></>
              ) : null}
            </p>
          </div>
          <div className="rounded border border-slate-800 bg-slate-950/40 p-3">
            <div className="text-xs font-semibold text-slate-200">③ 올해 → 내년 ROE</div>
            <div className="mt-1 text-2xl font-semibold text-slate-100">
              {currentRoe != null ? `${currentRoe.toFixed(2)}%` : DASH}
              <span className="mx-1 text-base text-slate-400">→</span>
              {nextRoe != null ? `${nextRoe.toFixed(2)}%` : DASH}
            </div>
            <p className="mt-1 text-xs leading-relaxed text-slate-300">
              네이버 증권 연간 재무표의 {currentRoeYear ?? "올해"}(E)와 {nextRoeYear ?? "내년"}(E).
              비교군 중앙값은 {pct(sectorMedians.roeCurrent)} → {pct(sectorMedians.roeNext)}다.
              네이버에 두 번째 추정 연도가 없으면 다른 원천으로 채우지 않고 빈칸으로 둔다.
            </p>
          </div>
          <div className="rounded border border-slate-800 bg-slate-950/40 p-3">
            <div className="text-xs font-semibold text-slate-200">④ 과거 9분기 평균 PER 대비</div>
            <div className="mt-1 text-2xl font-semibold text-slate-100">
              {price?.per_vs_9q_avg_pct != null
                ? `${price.per_vs_9q_avg_pct >= 0 ? "+" : ""}${price.per_vs_9q_avg_pct.toFixed(1)}%`
                : DASH}
            </div>
            <p className="mt-1 text-xs leading-relaxed text-slate-300">
              현재 TTM PER {price?.per_current_ttm != null ? `${price.per_current_ttm.toFixed(1)}배` : DASH}
              {" · "}과거 {price?.per_avg_quarters ?? 0}개 분기 평균{" "}
              {price?.per_avg_9q != null ? `${price.per_avg_9q.toFixed(1)}배` : DASH}. 음수일수록
              과거 평균보다 싸고, 값이 없으면 아직 측정하지 않은 것이며 0으로 보지 않는다.
            </p>
          </div>
          <div className="rounded border border-slate-800 bg-slate-950/40 p-3">
            <div className="text-xs font-semibold text-slate-200">⑤ PEG (네이버)</div>
            <div className="mt-1 text-2xl font-semibold text-slate-100">
              {referencePeg != null ? referencePeg.toFixed(2) : DASH}
            </div>
            <p className="mt-1 text-xs leading-relaxed text-slate-300">
              네이버증권이 공개한 PEG만 표시한다. 네이버가 값을 제공하지 않으면 다른 성장률로
              대체하지 않고 —로 둔다.
            </p>
          </div>
        </div>

        {per4q != null && forwardPerValue != null && (
          <p className="mt-3 rounded border border-emerald-800/60 bg-emerald-900/20 px-3 py-2 text-xs text-emerald-300">
            <strong>밸류에이션:</strong> 최근 4분기 {per4q.toFixed(1)}배 → 올해 예상이익
            {forwardPerValue.toFixed(1)}배로{" "}
            <strong>
              {forwardPerValue < per4q
                ? `${(100 * (1 - forwardPerValue / per4q)).toFixed(0)}% 낮아진다`
                : `${(100 * (forwardPerValue / per4q - 1)).toFixed(0)}% 높아진다`}
            </strong>. 이익 전망이 현재 TTM보다 좋아지는지 나빠지는지를 직접 보여준다.
          </p>
        )}

        {(currentRoe != null || nextRoe != null) && (
          <p className="mt-3 rounded border border-sky-800/60 bg-sky-950/20 px-3 py-2 text-xs text-sky-200">
            <strong>ROE 섹터 비교:</strong> 올해 {pct(currentRoe)}
            {currentRoe != null && sectorMedians.roeCurrent != null &&
              ` (비교군 중앙값 대비 ${(currentRoe - sectorMedians.roeCurrent) >= 0 ? "+" : ""}${(currentRoe - sectorMedians.roeCurrent).toFixed(1)}%p)`}
            {" · "}내년 {pct(nextRoe)}
            {nextRoe != null && sectorMedians.roeNext != null &&
              ` (비교군 중앙값 대비 ${(nextRoe - sectorMedians.roeNext) >= 0 ? "+" : ""}${(nextRoe - sectorMedians.roeNext).toFixed(1)}%p)`}.
            ROE가 높아지면서 F.PER가 낮아지는 조합인지 확인한다.
          </p>
        )}

      </Card>

      <Card title="섹터 비교" note={stockSector + " · 같은 평가 분기 스코어 상위 5개"}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1260px] text-right text-sm">
            <thead className="text-xs text-slate-300">
              <tr className="border-b border-slate-800">
                <th className="py-2 text-left">종목</th>
                <th className="py-2">시총</th>
                <th className="py-2">최신 분기 매출</th>
                <th className="py-2">영업이익</th>
                <th className="py-2">OPM</th>
                <th className="py-2">올해 ROE</th>
                <th className="py-2">내년 ROE</th>
                <th className="py-2">최근 4분기 PER</th>
                <th className="py-2">F.PER</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-slate-700 bg-slate-800/30 font-semibold">
                <td className="py-2 text-left">표시 종목 중앙값 ({sectorPeerRows.length}종목)</td>
                <td className="py-2">{marketCap(sectorMedians.marketCap)}</td>
                <td className="py-2">{eok(sectorMedians.revenue)}</td>
                <td className="py-2">{eok(sectorMedians.op)}</td>
                <td className="py-2">{pct(sectorMedians.opm)}</td>
                <td className="py-2">{pct(sectorMedians.roeCurrent)}</td>
                <td className="py-2">{pct(sectorMedians.roeNext)}</td>
                <td className="py-2">{sectorMedians.per4q != null ? `${sectorMedians.per4q.toFixed(1)}배` : DASH}</td>
                <td className="py-2">{sectorMedians.forwardPer != null ? `${sectorMedians.forwardPer.toFixed(1)}배` : DASH}</td>
              </tr>
              {sectorPeerRows.map((peer) => (
                <tr
                  key={peer.code}
                  className={
                    "border-b border-slate-800/60 " +
                    (peer.isCurrent ? "bg-amber-950/25 font-semibold text-amber-100" : "")
                  }
                >
                  <td className="py-2 text-left">
                    <Link href={"/stock/" + peer.code} className="hover:underline">
                      {peer.isCurrent ? "현재 · " : ""}{peer.name} ({peer.code})
                    </Link>
                  </td>
                  <td className="py-2">{marketCap(peer.marketCap)}</td>
                  <td className="py-2">{eok(peer.revenue)}</td>
                  <td className="py-2">{eok(peer.op)}</td>
                  <td className="py-2">{pct(peer.opm)}</td>
                  <td className="py-2">{pct(peer.roeCurrent)}</td>
                  <td className="py-2">{pct(peer.roeNext)}</td>
                  <td className="py-2">{peer.per4q != null ? peer.per4q.toFixed(peer.isCurrent && liveQuote ? 2 : 1) + "배" : DASH}</td>
                  <td className="py-2">{peer.forwardPer != null ? peer.forwardPer.toFixed(peer.isCurrent && liveQuote ? 2 : 1) + "배" : DASH}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Note>
          매출·영업이익·OPM은 같은 최신 평가 분기끼리만 비교한다. 현재 종목의 PER·F.PER·ROE는
          위 가치 카드와 같은 네이버 현재값이고, 비교 종목은 저장된 최신 네이버/FnGuide 값과
          시총÷최근 4분기 순이익 검산값을 쓴다. 상위 5개만 비교하며 평균 대신 이상치에 덜 흔들리는
          중앙값을 썼다. 현재 종목이 상위 5개 밖이면 위치 확인을 위해 마지막에 별도로 붙인다.
        </Note>
      </Card>

      <Card title="종목별 결과 추적" note="실적 발표일 기준 실제 주가와 지수대비 성과">
        {outcomeResult.rows.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-right text-sm">
              <thead className="text-xs text-slate-300">
                <tr className="border-b border-slate-800">
                  <th className="py-2 text-left">분기</th>
                  <th className="py-2 text-left">발표일</th>
                  <th className="py-2 text-center">등급</th>
                  {["D+1", "D+5", "D+20", "D+60"].map((label) => (
                    <th key={label} className="py-2">
                      {label}<br /><span className="font-normal">수익 / 지수대비</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {outcomeResult.rows.map((row) => {
                  const horizons = [
                    { label: "D+1", ret: row.ret_d1, excess: row.excess_d1 },
                    { label: "D+5", ret: row.ret_d5, excess: row.excess_d5 },
                    { label: "D+20", ret: row.ret_d20, excess: row.excess_d20 },
                    { label: "D+60", ret: row.ret_d60, excess: row.excess_d60 },
                  ];
                  return (
                    <tr
                      key={row.fiscal_year + "-" + row.fiscal_quarter}
                      className="border-b border-slate-800/60"
                    >
                      <td className="py-2 text-left">{quarterLabel(row.fiscal_year, row.fiscal_quarter)}</td>
                      <td className="py-2 text-left text-slate-300">{row.announce_date ?? DASH}</td>
                      <td className="py-2 text-center">{row.grade_at_announce ?? DASH}</td>
                      {horizons.map((item) => (
                        <td key={item.label} className="py-2">
                          {pct(item.ret, 1)}<br />
                          <span className="text-xs text-slate-300">{pct(item.excess, 1, "%p")}</span>
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-slate-300">
            발표일과 기준가격이 모두 확보된 추적 행이 아직 없다.
          </p>
        )}
        {outcomeResult.dropped.length > 0 && (
          <Note>아직 DB에 없는 결과 컬럼은 제외했다: {outcomeResult.dropped.join(", ")}.</Note>
        )}
      </Card>

      {/* ★ 용어를 모아 둔 카드는 두지 않는다 — 아래로 내려가야 읽을 수 있으면
          정작 숫자를 볼 때는 안 읽는다. 각 항목 바로 아래에 필요한 것만 붙였다.
          전체 목록은 /settings에 있다. */}

      {/* 9. 바깥 링크 */}
      <div className="flex flex-wrap items-center gap-4 text-sm">
        <Link href="/" className="text-sky-300 hover:underline">← 발굴 목록</Link>
        <a
          href={naverStockUrl(code)}
          target="_blank"
          rel="noreferrer"
          className="text-sky-300 hover:underline"
          title="네이버 증권 — 시세·차트·공시·재무를 한 화면에서 본다"
        >
          네이버 증권 ↗
        </a>
        <a
          href={stockeasyStockUrl(code)}
          target="_blank"
          rel="noreferrer"
          className="text-sky-300 hover:underline"
          title="StockEasy 종목 분석"
        >
          StockEasy ↗
        </a>
        {/* ★ DART 원문은 **접수번호로만** 열린다(T58). 없으면 링크를 만들지 않고
            어디로 가면 되는지를 대신 알려 준다 — 죽은 링크보다 낫다. */}
        {latestDisclosure ? (
          <a
            href={dartReportUrl(latestDisclosure.rcept_no)}
            target="_blank"
            rel="noreferrer"
            className="text-sky-300 hover:underline"
            title={latestDisclosure.report_nm ?? undefined}
          >
            DART 공시 원문 ↗
          </a>
        ) : <span className="text-slate-400">DART 원문 접수번호 미수집</span>}
      </div>

      {disclosures.length > 0 && (
        <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
          <h2 className="mb-2 text-sm font-semibold text-slate-100">최근 공시</h2>
          <ul className="space-y-1 text-sm">
            {disclosures.map((d) => (
              <li key={d.rcept_no} className="flex flex-wrap gap-2">
                <span className="w-24 shrink-0 text-xs text-slate-300">
                  {d.disclosed_at?.slice(0, 10) ?? DASH}
                </span>
                <a
                  href={dartReportUrl(d.rcept_no)}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sky-300 hover:underline"
                >
                  {d.report_nm ?? d.rcept_no}
                </a>
              </li>
            ))}
          </ul>
          <Note>
            DART 원문으로 바로 연결된다. 회사명으로 DART를 검색하는 주소는 화면이 뜨긴 해도
            검색이 실행되지 않아 빈 목록이 나오므로 쓰지 않는다.
          </Note>
        </div>
      )}
    </div>
  );
}
