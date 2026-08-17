// PRD Ref: §9.1 — 종목 상세. **시스템의 핵심 화면.**
import Link from "next/link";
import { notFound } from "next/navigation";
import QuarterlyChart from "@/components/QuarterlyChart";
import { CHART_QUARTERS, SERIES_COLOR, measuredCount, toChartPoints } from "@/lib/chart";
import { GradeBadge, WarningBadges } from "@/components/Badges";
import { PriBreakdown, ScoreBreakdown } from "@/components/ScoreBreakdown";
import { Term, TermTh } from "@/components/Term";
import TriggerTimeline, { type TimelineItem } from "@/components/TriggerTimeline";
import { readAnalysis } from "@/lib/analysis";
import { dartReportUrl, naverDisclosureUrl, naverStockUrl } from "@/lib/links";
import { forwardPer, trailing4qPer, ttmNetIncome } from "@/lib/valuation";
import { DASH, eok, growthOrLabel, marketCap, num, pct, quarterLabel } from "@/lib/format";
import {
  getAnalysis,
  getAnnualConsensus,
  getConsensus,
  getDisclosures,
  getFundamentals,
  getLatestPrice,
  getQuarterPrices,
  getScreenForCode,
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

export default async function StockPage({ params }: { params: { code: string } }) {
  const code = params.code;

  const [universe, funds, price, screenResult, quarterPrices, disclosures] =
    await Promise.all([
      getUniverse(),
      getFundamentals(code),
      getLatestPrice(code),
      getScreenForCode(code),
      getQuarterPrices(code),
      getDisclosures(code),
    ]);

  const stock = universe.get(code);
  if (!stock) notFound();

  const screen = screenResult.row;
  const latestFund = funds[funds.length - 1] ?? null;
  const year = screen?.fiscal_year ?? latestFund?.fiscal_year ?? null;
  const quarter = screen?.fiscal_quarter ?? latestFund?.fiscal_quarter ?? null;

  const [consensus, analysisPayload, annualConsensus] = await Promise.all([
    year && quarter ? getConsensus(code, year, quarter) : Promise.resolve(null),
    year && quarter ? getAnalysis(code, year, quarter) : Promise.resolve(null),
    year ? getAnnualConsensus(code, year) : Promise.resolve(null),
  ]);
  const analysis = readAnalysis(analysisPayload);

  // 스크리너가 평가한 바로 그 분기의 재무를 쓴다 — 최신 행과 다를 수 있다.
  const evaluated =
    year && quarter
      ? funds.find((f) => f.fiscal_year === year && f.fiscal_quarter === quarter) ?? latestFund
      : latestFund;

  // ── 밸류에이션 ──────────────────────────────────────────────
  // ★ 시총은 시세 스냅샷 것을 우선한다 — 유니버스 값은 하루 늦을 수 있다.
  const capForPer = price?.market_cap_krw ?? stock.market_cap_krw;
  // ★ 평가 분기까지의 4분기 누적으로 잡는다. 그냥 마지막 4행을 쓰면 스크리너가
  //   본 분기와 다른 구간의 PER이 나와 텔레그램과 화면이 어긋난다.
  const ttmNp =
    year && quarter ? ttmNetIncome(funds, year, quarter) : null;
  const per4q = trailing4qPer(capForPer, ttmNp);
  const fwd = forwardPer(annualConsensus, funds, capForPer);

  // ★ 오늘 종가를 넘겨 주가 라인이 **현재까지** 닿게 한다. 실적 행만 따르면
  //   마지막 발표 분기에서 잘려 그 뒤 주가 흐름을 볼 수 없다.
  const chartPoints = toChartPoints(funds, CHART_QUARTERS, quarterPrices, price?.close ?? null);

  // 트리거는 3개월·6개월 구간을 한 타임라인에 합친다 — 사람은 구간이 아니라
  // 시간 순서로 읽는다. 어느 구간에서 왔는지는 칩으로 남긴다.
  const timelineItems: TimelineItem[] = [
    ...analysis.triggers3m.map((t) => ({ ...t, window: "3개월 내", tone: "near" as const })),
    ...analysis.triggers6m.map((t) => ({ ...t, window: "6개월 내", tone: "far" as const })),
  ];
  const opYoyMeasured = measuredCount(chartPoints, "opYoy");
  const revYoyMeasured = measuredCount(chartPoints, "revenueYoy");
  const priceMeasured = chartPoints.filter((p) => p.close != null).length;

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
                  가속 강도를 100점으로 환산. 측정 못 한 축은 0점이 아니라{" "}
                  <strong className="text-slate-100">분모에서 빼고</strong> 정규화한다.
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
                  주가가 이 실적을 <strong className="text-slate-100">이미 아는 정도</strong>(0~100).{" "}
                  <strong className="text-amber-300">낮을수록 아직 안 올랐다</strong>는 뜻이라 좋은 신호다.
                  스코어와 <strong>더하지 않는다</strong> — 찾는 자리는{" "}
                  <strong className="text-amber-300">스코어 높고 반영도 낮은</strong> 구간(★)이다.
                  <span className="mt-0.5 block text-slate-200">
                    0~39 미반영 · 40~65 부분반영 · 66~100 선반영
                  </span>
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
        note="노란 선 = 영업이익 YoY (가장 중요)"
      >
        <QuarterlyChart points={chartPoints} />
        <Note>
          {/* ★ 기본 용어(막대·실선 색·YoY)는 적지 않는다(사용자 요청) —
              범례가 이미 말해 준다. 이 시스템에만 있는 것만 남긴다. */}
          <strong className="text-slate-100">선이 우상향하면 그게 가속이다</strong> —
          값이 높은 게 아니라 전분기보다 높아진 것을 본다.{" "}
          <strong style={{ color: SERIES_COLOR.TTM_COLOR }}>TTM 매출</strong>은 최근 4개 분기
          합으로, 계절성이 상쇄돼 연간 체력이 보인다.{" "}
          <strong style={{ color: SERIES_COLOR.PRICE_COLOR }}>주가</strong>는 현재까지 이어 그린다
          — 실적 선보다 늦게 올라오는 구간이 노리는 자리다.
          <span className="mt-1 block text-slate-200">
            측정 — 영업이익 YoY {opYoyMeasured}/{chartPoints.length} · 매출 YoY{" "}
            {revYoyMeasured}/{chartPoints.length} · 주가 {priceMeasured}/{chartPoints.length}.
            {opYoyMeasured < chartPoints.length &&
              " 빠진 분기는 흑자↔적자 전환이라 %를 계산할 수 없다(0%가 아니다)."}
            {" 분기 라벨의 "}<code>*</code>{"는 실적 미발표(주가만 있음)."}
          </span>
        </Note>
      </Card>

      {/* 4. 분기 히스토리 표 */}
      <Card title="분기 히스토리">
        <Note>
          {/* 기본 용어(YoY·QoQ·OPM)는 생략(사용자 요청). 이 시스템 고유의 것만. */}
          <strong className="text-slate-100">TTM 매출</strong>은 최근 4개 분기 합 ·{" "}
          <strong className="text-slate-100">잠정</strong>은 정식 보고서 전 회사 발표 ·{" "}
          <strong className="text-slate-100">흑전/적전</strong>은 흑자↔적자가 뒤바뀐 분기로
          %를 계산할 수 없어 라벨로 적는다. QoQ는 계절성이 커서 점수에 쓰지 않는다.
        </Note>
        {/* ★ 높이를 제한해야 sticky가 먹는다 — `overflow-x-auto`만으로는
            세로 스크롤 영역이 만들어지지 않아 머리글이 그냥 밀려 올라간다(T64). */}
        <div className="mt-3 max-h-[60vh] overflow-auto">
          <table className="w-full min-w-[720px] text-right text-sm">
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
                <TermTh term="TTM매출" align="right">TTM 매출</TermTh>
                <TermTh term="잠정" align="center">구분</TermTh>
              </tr>
            </thead>
            <tbody>
              {[...funds].reverse().slice(0, 12).map((f) => (
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
                  <td className="py-1.5">{eok(f.ttm_revenue)}</td>
                  <td className="py-1.5 text-center text-xs text-slate-300">
                    {f.is_estimate ? "잠정" : "확정"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* 5. 컨센서스 대비 */}
      <Card title="컨센서스 대비">
        <Note>
          추정기관 <strong className="text-slate-100">2곳 미만이면 컨센서스로 인정하지 않는다.</strong>{" "}
          없다고 감점하지 않고 분모에서 제외해 정규화한다.
        </Note>
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

      {/* 6. 밸류에이션 — 최근 4분기 → 향후 4분기 순. 후행 PER은 싣지 않는다. */}
      <Card title="밸류에이션" note="이익 대비 지금 주가가 몇 배인가">
        <div className="grid gap-5 text-sm sm:grid-cols-2">
          <div className="rounded border border-slate-800 bg-slate-950/40 p-3">
            <div className="text-xs font-semibold text-slate-200">
              ① <Term term="PER최근4분기">최근 4개 분기 순이익 기준 PER</Term>
            </div>
            <div className="mt-1 text-2xl font-semibold text-slate-100">
              {per4q != null ? `${per4q.toFixed(1)}배` : DASH}
            </div>
            <p className="mt-1 text-xs leading-relaxed text-slate-300">
              시가총액 ÷ 최근 4개 분기 순이익 합. <strong>지금까지 실제로 번 돈</strong> 기준이라
              추정이 섞이지 않는다.
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

      {/* 7. LLM 분석 */}
      <Card title="LLM 분석">
        {analysis.isEmpty ? (
          <p className="text-sm text-slate-300">
            아직 분석하지 않았다. 게이트 통과 상위 종목만 분석한다(비용 설계).
          </p>
        ) : (
          <div className="space-y-4 text-sm">
            {analysis.thesis && (
              <p className="text-base font-medium text-slate-100">💡 {analysis.thesis}</p>
            )}
            {analysis.whyNow && (
              <div>
                <div className="text-xs font-semibold uppercase text-slate-300">왜 지금인가</div>
                <p className="text-slate-100">{analysis.whyNow}</p>
              </div>
            )}

            {/* ★ 실적 변화 — 원인 / 결과 / 전망 (사용자 요청).
                2026-08-17 이전에 저장된 행에는 없다 → 있을 때만 그린다. */}
            {(analysis.earningsChange.cause ||
              analysis.earningsChange.effect ||
              analysis.earningsChange.outlook) && (
              <div className="rounded-lg border border-slate-700 bg-slate-950/40 p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs font-semibold uppercase text-slate-200">
                    실적 변화 — 원인 · 결과 · 전망
                  </span>
                  {analysis.earningsChange.confidence && (
                    <span
                      className={`rounded border px-1.5 py-0.5 text-[11px] ${
                        {
                          high: "border-emerald-500/60 bg-emerald-500/10 text-emerald-200",
                          medium: "border-amber-500/60 bg-amber-500/10 text-amber-200",
                          low: "border-slate-600 bg-slate-700/30 text-slate-200",
                        }[analysis.earningsChange.confidence]
                      }`}
                      title="전망의 확신도 — 근거가 약하면 모델이 스스로 낮춘다"
                    >
                      전망 확신도 {analysis.earningsChange.confidence}
                    </span>
                  )}
                </div>
                <div className="mt-3 space-y-3">
                  {analysis.earningsChange.cause && (
                    <div className="border-l-2 border-sky-500/70 pl-3">
                      <div className="text-xs font-bold text-sky-200">왜 이렇게 변했나 (원인)</div>
                      <p className="mt-0.5 text-slate-100">{analysis.earningsChange.cause}</p>
                    </div>
                  )}
                  {analysis.earningsChange.effect && (
                    <div className="border-l-2 border-violet-500/70 pl-3">
                      <div className="text-xs font-bold text-violet-200">무엇이 달라졌나 (결과)</div>
                      <p className="mt-0.5 text-slate-100">{analysis.earningsChange.effect}</p>
                    </div>
                  )}
                  {analysis.earningsChange.outlook && (
                    <div className="border-l-2 border-amber-500/70 pl-3">
                      <div className="text-xs font-bold text-amber-200">앞으로 어떻게 되나 (전망)</div>
                      <p className="mt-0.5 text-slate-100">{analysis.earningsChange.outlook}</p>
                    </div>
                  )}
                </div>
              </div>
            )}
            {(analysis.structuralDrivers.length > 0 || analysis.temporaryDrivers.length > 0) && (
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <div className="text-xs font-semibold uppercase text-slate-200">구조적 동인</div>
                  <Note>계속 이어질 이유 — 이게 많아야 가속이 오래간다.</Note>
                  <ul className="mt-1 list-disc pl-4 text-slate-100">
                    {analysis.structuralDrivers.map((d) => <li key={d}>{d}</li>)}
                  </ul>
                </div>
                <div>
                  <div className="text-xs font-semibold uppercase text-slate-200">일시적 동인</div>
                  <Note>이번 분기에만 통한 이유 — 여기에 쏠려 있으면 곧 꺾인다.</Note>
                  <ul className="mt-1 list-disc pl-4 text-slate-100">
                    {analysis.temporaryDrivers.map((d) => <li key={d}>{d}</li>)}
                  </ul>
                </div>
              </div>
            )}
            {analysis.sustainabilityQuarters != null && (
              <p className="text-slate-100">
                가속 지속 전망: <strong>{analysis.sustainabilityQuarters}개 분기</strong>
              </p>
            )}
            {analysis.scenarios.length > 0 && (
              <div>
                <div className="text-xs font-semibold uppercase text-slate-300">시나리오</div>
                <div className="mt-1 space-y-1">
                  {analysis.scenarios.map((s) => (
                    <div key={s.name} className="flex gap-2">
                      <span className="w-12 shrink-0 uppercase text-slate-200">{s.name}</span>
                      <span className="w-14 shrink-0 text-slate-100">
                        {s.probability != null ? `${(s.probability * 100).toFixed(0)}%` : DASH}
                      </span>
                      <span className="text-slate-200">{s.description ?? DASH}</span>
                    </div>
                  ))}
                </div>
                {analysis.probabilitySum != null &&
                  Math.abs(analysis.probabilitySum - 1) > 0.01 && (
                    <p className="mt-1 text-xs text-amber-400">
                      ⚠ 확률 합이 {analysis.probabilitySum.toFixed(2)}다 (1.00이어야 한다)
                    </p>
                  )}
              </div>
            )}
            {/* ★ 주가 상승 트리거 — 이 분석에서 가장 실행에 가까운 부분이라
                목록이 아니라 **타임라인**으로 그린다. 시점 순서가 곧 판단이다. */}
            {timelineItems.length > 0 && (
              <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-4">
                <div className="text-xs font-semibold uppercase text-slate-200">
                  주가 상승 트리거
                </div>
                <Note>
                  주가를 올릴 수 있는 <strong className="text-slate-100">확인 가능한 사건</strong>과
                  예상 시점. &lsquo;확인 지표&rsquo;로 실제 발생을 나중에 대조할 수 있다 —
                  그래야 예측이 아니라 검증이 된다.
                </Note>
                <div className="mt-3">
                  <TriggerTimeline items={timelineItems} />
                </div>
              </div>
            )}
            {analysis.risks.length > 0 && (
              <div>
                <div className="text-xs font-semibold uppercase text-slate-300">리스크</div>
                <table className="mt-1 w-full text-left text-xs">
                  <thead className="text-slate-300">
                    <tr>
                      <th className="py-1">리스크</th>
                      <th className="py-1">발생</th>
                      <th className="py-1">영향</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analysis.risks.map((r, i) => (
                      <tr key={i} className="border-t border-slate-800/60">
                        <td className="py-1 text-slate-100">{r.risk ?? DASH}</td>
                        <td className="py-1 text-slate-200">{r.likelihood ?? DASH}</td>
                        <td className="py-1 text-slate-200">{r.impact ?? DASH}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {analysis.whyIMightBeWrong && (
              <div>
                <div className="text-xs font-semibold uppercase text-slate-300">
                  내가 틀릴 수 있는 이유
                </div>
                <p className="text-slate-100">{analysis.whyIMightBeWrong}</p>
              </div>
            )}
          </div>
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
