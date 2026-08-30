// PRD Ref: §9.1 — 종목 상세. **시스템의 핵심 화면.**
import Link from "next/link";
import { notFound } from "next/navigation";
import QuarterlyChart from "@/components/QuarterlyChart";
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
import { dartReportUrl, naverDisclosureUrl, naverStockUrl } from "@/lib/links";
import { forwardPer, trailing4qPer, ttmNetIncome } from "@/lib/valuation";
import { DASH, eok, growthOrLabel, marketCap, num, pct, quarterLabel } from "@/lib/format";
import { getOutcomesForCode } from "@/lib/outcome";
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
  getQuarterPrices,
  getScreenForCode,
  getScreensForQuarter,
  getUniverse,
} from "@/lib/queries";

export const dynamic = "force-dynamic";

function Card({
  title,
  children,
  note,
}: {
  title: string;
  children: React.ReactNode;
  note?: string;
}) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
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

function average(values: Array<number | null | undefined>): number | null {
  const measured = values.filter((value): value is number => value != null);
  if (measured.length === 0) return null;
  return measured.reduce((sum, value) => sum + value, 0) / measured.length;
}

export default async function StockPage({ params }: { params: { code: string } }) {
  const code = params.code;

  const [universe, funds, price, screenResult, quarterPrices, disclosures, outcomeResult] =
    await Promise.all([
      getUniverse(),
      getFundamentals(code),
      getLatestPrice(code),
      getScreenForCode(code),
      getQuarterPrices(code),
      getDisclosures(code),
      getOutcomesForCode(code),
    ]);

  const stock = universe.get(code);
  if (!stock) notFound();

  const screen = screenResult.row;
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
    year && quarter ? getAnalysis(code, year, quarter) : Promise.resolve(null),
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
  const fallback = analysisPayload ? null : await getLatestAnalysis(code);
  const analysis = readAnalysis(analysisPayload ?? fallback?.payload ?? null);
  const analysisYear = analysisPayload ? year : fallback?.fiscal_year ?? null;
  const analysisQuarter = analysisPayload ? quarter : fallback?.fiscal_quarter ?? null;
  const analysisIsStale = Boolean(fallback);

  // 스크리너가 평가한 바로 그 분기의 재무를 쓴다 — 최신 행과 다를 수 있다.
  const evaluated =
    year && quarter
      ? funds.find((f) => f.fiscal_year === year && f.fiscal_quarter === quarter) ?? latestFund
      : latestFund;

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
      const [peerFunds, peerPrice] = isCurrent
        ? [funds, price]
        : await Promise.all([
            getFundamentals(peerScreen.code),
            getLatestPrice(peerScreen.code),
          ]);
      const peerFund = quarterFundByCode.get(peerScreen.code) ?? null;
      const peerCap =
        peerPrice?.market_cap_krw ?? universe.get(peerScreen.code)?.market_cap_krw ?? null;
      const peerTtmNp =
        year && quarter ? ttmNetIncome(peerFunds, year, quarter) : null;
      return {
        code: peerScreen.code,
        name: universe.get(peerScreen.code)?.name ?? peerScreen.code,
        isCurrent,
        score: peerScreen.score_final ?? peerScreen.score_flash,
        revenueYoy: peerFund?.revenue_yoy ?? null,
        opm: peerFund?.opm ?? null,
        per: trailing4qPer(peerCap, peerTtmNp),
      };
    })
  );
  const sectorAverages = {
    score: average(sectorScreens.map((row) => row.score_final ?? row.score_flash)),
    revenueYoy: average(
      sectorScreens.map((row) => quarterFundByCode.get(row.code)?.revenue_yoy)
    ),
    opm: average(sectorScreens.map((row) => quarterFundByCode.get(row.code)?.opm)),
  };

  // ── 밸류에이션 ──────────────────────────────────────────────
  // ★ 시총은 시세 스냅샷 것을 우선한다 — 유니버스 값은 하루 늦을 수 있다.
  const capForPer = price?.market_cap_krw ?? stock.market_cap_krw;
  // ★ 평가 분기까지의 4분기 누적으로 잡는다. 그냥 마지막 4행을 쓰면 스크리너가
  //   본 분기와 다른 구간의 PER이 나와 텔레그램과 화면이 어긋난다.
  const ttmNp =
    year && quarter ? ttmNetIncome(funds, year, quarter) : null;
  const per4q = trailing4qPer(capForPer, ttmNp);
  const fwd = forwardPer(annualConsensus, funds, capForPer);
  // 표준 PEG(연간 예상 성장률)가 아니라, 현재 화면이 실제로 가진 같은 분기
  // EPS YoY를 분모로 한 참고값이다. 0 이하·결측은 만들지 않는다.
  const referencePeg =
    per4q != null && evaluated?.eps_yoy != null && evaluated.eps_yoy > 0
      ? per4q / evaluated.eps_yoy
      : null;

  // ★ 오늘 종가를 넘겨 주가 라인이 **현재까지** 닿게 한다. 실적 행만 따르면
  //   마지막 발표 분기에서 잘려 그 뒤 주가 흐름을 볼 수 없다.
  const chartPoints = toChartPoints(funds, CHART_QUARTERS, quarterPrices, price?.close ?? null);

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
  const priceMeasured = chartPoints.filter((p) => p.close != null).length;

  // ★ DART 원문은 **접수번호로만** 열린다. 회사명 검색 URL은 200을 주고도
  //   검색을 실행하지 않아 빈 화면이 뜬다(T58) — 없으면 링크를 만들지 않는다.
  const latestDisclosure = disclosures[0] ?? null;
  const screenByQuarter = new Map(
    screenResult.history.map((row) => [
      `${row.fiscal_year}-${row.fiscal_quarter}`,
      row,
    ])
  );
  const excerptSections = Object.entries(disclosureExcerpt?.sections ?? {}).filter(
    (entry): entry is [string, string] =>
      typeof entry[1] === "string" && entry[1].trim().length > 0
  );

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
            {stock.board} · {stock.industry ?? DASH} · 시총 {marketCap(stock.market_cap_krw)}
          </p>
          {stock.products && (
            <p className="mt-1 text-xs text-slate-300">{stock.products}</p>
          )}
        </div>
        <div className="text-right">
          <div className="text-2xl font-semibold">{num(price?.close)}원</div>
          <div className="text-sm text-slate-200">{pct(price?.chg_pct, 2)}</div>
          <div className="mt-1 text-xs text-slate-300">
            52주 {num(price?.low_52w)} ~ {num(price?.high_52w)}
            {price?.pos_52w != null && ` (위치 ${(price.pos_52w * 100).toFixed(0)}%)`}
          </div>
          <div className="text-xs text-slate-300">
            3개월 지수대비 {pct(price?.rel_ret_3m, 1, "%p")}
          </div>
        </div>
      </div>

      <div className="grid gap-2 text-sm sm:grid-cols-4">
        {[
          ["3개월 절대", price?.ret_3m],
          ["3개월 지수대비", price?.rel_ret_3m],
          ["6개월 절대", price?.ret_6m],
          ["12개월 절대", price?.ret_12m],
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
      <p className="-mt-3 text-right text-[11px] text-slate-400">
        6·12개월 지수대비 값은 아직 수집하지 않아 절대수익률로 표시한다.
      </p>

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
                게이트 {screen.gate_passed === true ? "통과" : screen.gate_passed === false ? "탈락" : "판정 불가"}
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
                <h3 className="mb-1 text-xs font-semibold uppercase text-slate-200">스코어</h3>
                <Note>
                  가속 강도 100점 만점 · 미측정 축은 0점이 아니라{" "}
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
                  <span className="block">스코어와 <strong>합산하지 않는다</strong> · ★ = 스코어 높음 + 반영도 낮음</span>
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

      {/* 3. 9분기 차트 — 성장률 라인이 주인공 */}
      <Card
        title={`분기 실적 추이 (${CHART_QUARTERS}분기)`}
        note="핵심은 노란 선 — 영업이익 YoY가 빨라지고 있는가"
      >
        <QuarterlyChart points={chartPoints} />

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

        <Note>
          <span className="text-slate-100">
            <strong style={{ color: SERIES_COLOR.OP_LABEL }}>영업이익 YoY</strong> 노란 선이
            주인공 · <strong style={{ color: SERIES_COLOR.REVENUE_LABEL }}>매출 YoY</strong> 녹색 ·{" "}
            <strong style={{ color: SERIES_COLOR.TTM_COLOR }}>TTM</strong> 최근 4분기 합 ·{" "}
            <strong style={{ color: SERIES_COLOR.PRICE_COLOR }}>주가</strong> 현재까지 ·{" "}
            <code>*</code> 실적 미발표
          </span>
          <span className="mt-1 block">
            측정 {opYoyMeasured}/{chartPoints.length}(영업익) · {revYoyMeasured}/
            {chartPoints.length}(매출) · {priceMeasured}/{chartPoints.length}(주가)
            {opYoyMeasured < chartPoints.length && " · 빈 칸은 흑↔적 전환(0%가 아니다)"}
          </span>
        </Note>
      </Card>

      {/* 4. 분기 히스토리 표 */}
      <Card title="분기 히스토리">
        <Note>
          <strong className="text-slate-100">TTM 매출</strong> 최근 4분기 합 ·{" "}
          <strong className="text-slate-100">흑전/적전</strong> 흑↔적 전환(%계산 불가) ·{" "}
          <strong className="text-slate-100">QoQ</strong> 참고용(점수 미반영)
        </Note>
        {/* ★ 높이를 제한해야 sticky가 먹는다 — `overflow-x-auto`만으로는
            세로 스크롤 영역이 만들어지지 않아 머리글이 그냥 밀려 올라간다(T64). */}
        <div className="mt-3 max-h-[60vh] overflow-auto">
          <table className="w-full min-w-[1040px] text-right text-sm">
            <thead className="sticky top-0 z-20 bg-slate-900 text-xs uppercase text-slate-200 shadow-[0_1px_0_0_rgba(148,163,184,0.35)]">
              <tr className="border-b border-slate-800">
                <TermTh term="분기">분기</TermTh>
                <TermTh term="매출액" align="right">매출</TermTh>
                <TermTh term="YoY" align="right">YoY</TermTh>
                <TermTh term="QoQ" align="right">QoQ</TermTh>
                <TermTh term="영업이익" align="right">영업이익</TermTh>
                <TermTh term="YoY" align="right">YoY</TermTh>
                <TermTh term="OPM" align="right">OPM</TermTh>
                <TermTh term="OPM" align="right">OPM YoY</TermTh>
                <TermTh term="EPS" align="right">EPS</TermTh>
                <TermTh term="EPS YoY" align="right">EPS YoY</TermTh>
                <TermTh term="FCF" align="right">FCF</TermTh>
                <TermTh term="TTM매출" align="right">TTM 매출</TermTh>
                <th className="px-2 py-2 text-right">스코어 Δ</th>
                <TermTh term="잠정" align="center">구분</TermTh>
              </tr>
            </thead>
            <tbody>
              {[...funds].reverse().slice(0, 12).map((f) => {
                const historicalScreen = screenByQuarter.get(
                  `${f.fiscal_year}-${f.fiscal_quarter}`
                );
                return (
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
                  <td className="py-1.5">{pct(f.opm)}</td>
                  <td className="py-1.5">{pct(f.opm_yoy_delta, 1, "%p")}</td>
                  <td className="py-1.5">{num(f.eps)}</td>
                  <td className="py-1.5">{pct(f.eps_yoy)}</td>
                  <td className="py-1.5">{eok(f.fcf)}</td>
                  <td className="py-1.5">{eok(f.ttm_revenue)}</td>
                  <td className="py-1.5">{pct(historicalScreen?.score_delta, 1, "점")}</td>
                  <td className="py-1.5 text-center text-xs text-slate-300">
                    {f.is_estimate ? "잠정" : "확정"}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {/* ★★ 5. LLM 분석 — **분기 히스토리 바로 아래**다(사용자 지정 2026-08-22).
          숫자를 본 직후에 해석을 읽어야 대조가 된다. 밸류에이션·컨센서스를 지나
          맨 아래에 있으면 스크롤을 내리는 동안 방금 본 숫자를 잊는다. */}
      <Card
        title="LLM 분석"
        note={
          analysisYear && analysisQuarter
            ? `${quarterLabel(analysisYear, analysisQuarter)} 기준`
            : undefined
        }
      >
        {analysisIsStale && analysisYear && analysisQuarter && (
          <p className="mb-3 rounded border border-amber-700/70 bg-amber-950/30 px-3 py-2 text-xs text-amber-200">
            ⚠ 이 해석은 <strong>{quarterLabel(analysisYear, analysisQuarter)}</strong> 기준이다 —
            그 뒤 {year && quarter ? quarterLabel(year, quarter) : "새 분기"} 실적이 나왔지만
            아직 다시 분석하지 않았다(게이트 통과 상위만 분석한다).{" "}
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
            perForward: fwd.per,
            forwardBasis: fwd.basis,
            pbr: price?.pbr ?? null,
            ttmNp,
          }}
        />
      </Card>

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
        <Note>추정기관 2곳 이상만 인정 · 없으면 감점이 아니라 분모 제외</Note>
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
      <Card title="밸류에이션" note="이익 대비 지금 주가가 몇 배인가">
        <div className="grid gap-5 text-sm sm:grid-cols-2 xl:grid-cols-4">
          <div className="rounded border border-slate-800 bg-slate-950/40 p-3">
            <div className="text-xs font-semibold text-slate-200">
              ① <Term term="PER최근4분기">최근 4개 분기 순이익 기준 PER</Term>
            </div>
            <div className="mt-1 text-2xl font-semibold text-slate-100">
              {per4q != null ? `${per4q.toFixed(1)}배` : DASH}
            </div>
            <p className="mt-1 text-xs leading-relaxed text-slate-300">
              시총 ÷ 최근 4분기 순이익 · <strong>실제로 번 돈</strong> 기준(추정 없음).
              {ttmNp != null && (
                <> 분모는 {eok(ttmNp)}({quarterLabel(year ?? 0, quarter ?? 0)}까지 4분기 누적).</>
              )}
              {per4q == null && (
                <> 4개 분기가 다 모이지 않았거나 누적 순이익이 0 이하라 계산하지 않았다 —
                  연율화해서 만들어내지 않는다.</>
              )}
            </p>
          </div>
          <div className="rounded border border-slate-800 bg-slate-950/40 p-3">
            <div className="text-xs font-semibold text-slate-200">
              ② <Term term="PER선행">향후 4개 분기 선행 PER</Term>
            </div>
            <div className="mt-1 text-2xl font-semibold text-slate-100">
              {fwd.per != null ? `${fwd.per.toFixed(1)}배` : DASH}
            </div>
            <p className="mt-1 text-xs leading-relaxed text-slate-300">
              시가총액 ÷ 향후 4개 분기 <strong>추정</strong> 순이익.{" "}
              <strong className="text-slate-200">이익이 늘 것을 반영한 배수</strong>라 가속
              구간에서는 ①보다 낮게 나온다.
              {fwd.basis ? (
                <> 근거: {fwd.basis} — 연간 컨센서스에서 이미 발표된 분기를 뺀 값이고, 모자란
                  분기는 연간 추정의 분기 평균으로 이어 붙였다(추정 위의 추정).</>
              ) : (
                <> <strong className="text-slate-200">연간 컨센서스가 없어 계산하지 않았다.</strong>{" "}
                  코스닥 상장사의 약 60%가 최근 1년 리포트 0건이다 — 없는 값을 만들어내지 않는다.</>
              )}
            </p>
          </div>
          <div className="rounded border border-slate-800 bg-slate-950/40 p-3">
            <div className="text-xs font-semibold text-slate-200">③ 3년 PER 밴드</div>
            <div className="mt-1 text-2xl font-semibold text-slate-100">
              {price?.per_pctile_3y != null ? `${price.per_pctile_3y.toFixed(0)}백분위` : DASH}
            </div>
            <p className="mt-1 text-xs leading-relaxed text-slate-300">
              이 종목의 최근 3년 PER 안에서 현재 위치. 0에 가까울수록 낮고 100에 가까울수록
              높다. 값이 없으면 아직 측정하지 않은 것이며 0으로 보지 않는다.
            </p>
          </div>
          <div className="rounded border border-slate-800 bg-slate-950/40 p-3">
            <div className="text-xs font-semibold text-slate-200">④ 참고 PEG</div>
            <div className="mt-1 text-2xl font-semibold text-slate-100">
              {referencePeg != null ? referencePeg.toFixed(2) : DASH}
            </div>
            <p className="mt-1 text-xs leading-relaxed text-slate-300">
              최근 4분기 PER ÷ 평가 분기 EPS YoY(%). 연간 예상 성장률을 쓰는 표준 PEG가
              아닌 참고값이다. EPS YoY가 0 이하이거나 없으면 계산하지 않는다.
            </p>
          </div>
        </div>

        {per4q != null && fwd.per != null && fwd.per < per4q && (
          <p className="mt-3 rounded border border-emerald-800/60 bg-emerald-900/20 px-3 py-2 text-xs text-emerald-300">
            이익이 늘면서 배수가 {per4q.toFixed(1)}배 → {fwd.per.toFixed(1)}배로{" "}
            <strong>{(100 * (1 - fwd.per / per4q)).toFixed(0)}% 낮아진다.</strong>{" "}
            지금 비싸 보여도 이익이 따라붙으면 그렇지 않게 된다는 뜻이다.
          </p>
        )}

        {price?.pbr != null && (
          <Note>PBR {price.pbr.toFixed(2)}배 — 주가 ÷ 주당 순자산.</Note>
        )}
      </Card>

      <Card title="섹터 비교" note={stockSector + " · 같은 평가 분기 스코어 상위 5개"}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-right text-sm">
            <thead className="text-xs text-slate-300">
              <tr className="border-b border-slate-800">
                <th className="py-2 text-left">종목</th>
                <th className="py-2">스코어</th>
                <th className="py-2">매출 YoY</th>
                <th className="py-2">OPM</th>
                <th className="py-2">최근 4분기 PER</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-slate-700 bg-slate-800/30 font-semibold">
                <td className="py-2 text-left">{stockSector} 평균 ({sectorScreens.length}종목)</td>
                <td className="py-2">{pct(sectorAverages.score, 1, "점")}</td>
                <td className="py-2">{pct(sectorAverages.revenueYoy)}</td>
                <td className="py-2">{pct(sectorAverages.opm)}</td>
                <td className="py-2 text-slate-400">—</td>
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
                  <td className="py-2">{pct(peer.score, 1, "점")}</td>
                  <td className="py-2">{pct(peer.revenueYoy)}</td>
                  <td className="py-2">{pct(peer.opm)}</td>
                  <td className="py-2">{peer.per != null ? peer.per.toFixed(1) + "배" : DASH}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Note>
          평균은 같은 분기에 측정된 값만 사용한다. PER은 오래된 스냅샷 값을 쓰지 않고
          각 종목의 시총 ÷ 최근 4분기 순이익으로 다시 계산했으며, 상위 5개만 비교한다(T92).
          현재 종목이 상위 5개 밖이면 위치 확인을 위해 마지막에 별도로 붙인다.
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

      <Card
        title="공시 발췌"
        note={year && quarter ? quarterLabel(year, quarter) + "와 같은 분기" : undefined}
      >
        {excerptSections.length > 0 ? (
          <details className="rounded border border-slate-800 bg-slate-950/40 p-3">
            <summary className="cursor-pointer text-sm font-semibold text-sky-200">
              정기보고서 발췌 보기 ({excerptSections.length}개 절 ·{" "}
              {num(disclosureExcerpt?.excerpt_chars)}자)
            </summary>
            <div className="mt-4 space-y-5">
              {excerptSections.map(([section, body]) => (
                <div key={section}>
                  <h3 className="mb-1 text-xs font-semibold text-amber-200">{section}</h3>
                  <pre className="max-h-80 overflow-auto whitespace-pre-wrap font-sans text-xs leading-relaxed text-slate-200">
                    {body}
                  </pre>
                </div>
              ))}
            </div>
            <Note>
              분석 입력 예산 안에서 고른 절별 발췌다. 원문 전체가 아니며, 접수번호가 있으면{" "}
              <a
                href={dartReportUrl(disclosureExcerpt!.rcept_no)}
                target="_blank"
                rel="noreferrer"
                className="text-sky-300 hover:underline"
              >
                DART 원문 ↗
              </a>
              에서 대조한다.
            </Note>
          </details>
        ) : (
          <p className="text-sm text-slate-300">
            평가 분기와 정확히 같은 정기보고서 발췌가 아직 없다. 다른 분기 원문으로 대체하지 않는다.
          </p>
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
        ) : (
          <a
            href={naverDisclosureUrl(code)}
            target="_blank"
            rel="noreferrer"
            className="text-slate-200 hover:underline"
            title="이 종목의 DART 접수번호를 아직 수집하지 못했다 — 네이버 공시 목록으로 연결한다"
          >
            공시 목록(네이버) ↗
          </a>
        )}
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
