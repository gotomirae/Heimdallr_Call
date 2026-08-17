// PRD Ref: §9.1 — 종목 상세. **시스템의 핵심 화면.**
import Link from "next/link";
import { notFound } from "next/navigation";
import QuarterlyChart from "@/components/QuarterlyChart";
import { CHART_QUARTERS, measuredCount, toChartPoints } from "@/lib/chart";
import { GradeBadge, WarningBadges } from "@/components/Badges";
import { PriBreakdown, ScoreBreakdown } from "@/components/ScoreBreakdown";
import { Glossary, Term, TermTh } from "@/components/Term";
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
      <h2 className="mb-3 text-sm font-semibold text-slate-300">
        {title}
        {note && <span className="ml-2 font-normal text-slate-500">{note}</span>}
      </h2>
      {children}
    </section>
  );
}

/** 카드 안에서 "이게 무슨 뜻인가"를 한 줄로 붙인다. 숫자만 있으면 읽히지 않는다. */
function Note({ children }: { children: React.ReactNode }) {
  return <p className="mt-3 text-xs leading-relaxed text-slate-500">{children}</p>;
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

  const chartPoints = toChartPoints(funds, CHART_QUARTERS, quarterPrices);
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
            {stock.name} <span className="text-slate-500">{code}</span>
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            {stock.board} · {stock.industry ?? DASH} · 시총 {marketCap(stock.market_cap_krw)}
          </p>
          {stock.products && (
            <p className="mt-1 text-xs text-slate-500">{stock.products}</p>
          )}
        </div>
        <div className="text-right">
          <div className="text-2xl font-semibold">{num(price?.close)}원</div>
          <div className="text-sm text-slate-400">{pct(price?.chg_pct, 2)}</div>
          <div className="mt-1 text-xs text-slate-500">
            52주 {num(price?.low_52w)} ~ {num(price?.high_52w)}
            {price?.pos_52w != null && ` (위치 ${(price.pos_52w * 100).toFixed(0)}%)`}
          </div>
          <div className="text-xs text-slate-500">
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
              <span className="text-sm text-slate-400">
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
                <h3 className="mb-2 text-xs font-semibold uppercase text-slate-500">스코어</h3>
                <ScoreBreakdown screen={screen} />
              </div>
              <div>
                <h3 className="mb-2 text-xs font-semibold uppercase text-slate-500">
                  주가반영도 (PRI · 낮을수록 미반영)
                </h3>
                <PriBreakdown pri={screen.pri} detail={screen.pri_detail} />
              </div>
            </div>
          </div>
        ) : (
          <p className="text-sm text-slate-500">스크리닝 결과가 없다.</p>
        )}
      </Card>

      {/* 3. 9분기 차트 — 성장률 라인이 주인공 */}
      <Card
        title={`분기 실적 추이 (${CHART_QUARTERS}분기)`}
        note="초록 = 영업이익 YoY (가장 중요)"
      >
        <QuarterlyChart points={chartPoints} />
        <Note>
          <strong className="text-slate-300">막대</strong>는 그 분기의 매출·영업이익 금액(억원),{" "}
          <strong className="text-emerald-400">초록 실선</strong>은{" "}
          <Term term="영업이익">영업이익 성장률(YoY)</Term>,{" "}
          <strong className="text-amber-400">주황 실선</strong>은{" "}
          <Term term="매출액">매출 성장률(YoY)</Term>이다. 두 선 위의 숫자가 그 분기의
          성장률이며, <strong className="text-slate-300">선이 우상향하면 그게 가속이다</strong> —
          값이 높은 것이 아니라 <em>전분기보다 높아진 것</em>이 이 시스템이 찾는 신호다.
          <span className="mt-1 block">
            <strong className="text-slate-400">회색 점선(TTM 매출)</strong>은{" "}
            <Term term="TTM">최근 4개 분기 매출의 합</Term>이다. 한 분기만 보면 계절성과
            일회성에 흔들리지만, 4분기를 더하면 계절 요인이 상쇄돼 &ldquo;지금 이 회사의 연간
            체력&rdquo;이 보인다. 이 선이 계속 최고치를 경신하면 그 가속은 일시적인 게 아니다.
          </span>
          <span className="mt-1 block">
            <strong className="text-violet-400">보라 점선(주가)</strong>은 그 분기 마지막
            거래일의 종가다. 실적 선보다 주가 선이 <em>늦게</em> 올라오는 구간이 이 시스템이
            노리는 자리다.
          </span>
          <span className="mt-1 block text-slate-600">
            측정된 분기 — 영업이익 YoY {opYoyMeasured}/{chartPoints.length} · 매출 YoY{" "}
            {revYoyMeasured}/{chartPoints.length} · 주가 {priceMeasured}/{chartPoints.length}.
            {opYoyMeasured < chartPoints.length &&
              " 빠진 구간은 흑자↔적자 전환이라 성장률(%)을 계산할 수 없는 분기다(0%가 아니다)."}
            {priceMeasured === 0 &&
              " 주가는 아직 수집되지 않아 라인이 그려지지 않았다."}
          </span>
        </Note>
      </Card>

      {/* 4. 분기 히스토리 표 */}
      <Card title="분기 히스토리">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-right text-sm">
            {/* 헤더 고정 — 12분기를 훑어 내려도 어느 열인지 잃지 않는다 */}
            <thead className="sticky top-0 z-10 bg-slate-900 text-xs uppercase text-slate-400">
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
                  <td className="py-1.5 text-left text-slate-300">
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
                  <td className="py-1.5 text-center text-xs text-slate-500">
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
        {consensus && (consensus.n_estimates ?? 0) >= 2 ? (
          <div className="grid gap-4 text-sm sm:grid-cols-3">
            <div>
              <div className="text-xs text-slate-500">추정기관 수</div>
              <div className="text-lg">{consensus.n_estimates}곳</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">매출 서프라이즈</div>
              <div className="text-lg">
                {consensus.revenue_est && evaluated?.revenue
                  ? pct(((evaluated.revenue - consensus.revenue_est) / consensus.revenue_est) * 100)
                  : DASH}
              </div>
              <div className="text-xs text-slate-500">컨센 {eok(consensus.revenue_est)}</div>
            </div>
            <div>
              <div className="text-xs text-slate-500">영업이익 서프라이즈</div>
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
              <div className="text-xs text-slate-500">컨센 {eok(consensus.op_est)}</div>
            </div>
          </div>
        ) : (
          <p className="text-sm text-slate-400">
            <strong className="text-slate-200">커버리지 없음.</strong> 추정기관이 2곳 미만이라
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
            <div className="text-xs font-semibold text-slate-400">
              ① <Term term="PER최근4분기">최근 4개 분기 순이익 기준 PER</Term>
            </div>
            <div className="mt-1 text-2xl font-semibold text-slate-100">
              {per4q != null ? `${per4q.toFixed(1)}배` : DASH}
            </div>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">
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
            <div className="text-xs font-semibold text-slate-400">
              ② <Term term="PER선행">향후 4개 분기 선행 PER</Term>
            </div>
            <div className="mt-1 text-2xl font-semibold text-slate-100">
              {fwd.per != null ? `${fwd.per.toFixed(1)}배` : DASH}
            </div>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">
              시가총액 ÷ 향후 4개 분기 <strong>추정</strong> 순이익.{" "}
              <strong className="text-slate-400">이익이 늘 것을 반영한 배수</strong>라 가속
              구간에서는 ①보다 낮게 나온다.
              {fwd.basis ? (
                <> 근거: {fwd.basis} — 연간 컨센서스에서 이미 발표된 분기를 뺀 값이고, 모자란
                  분기는 연간 추정의 분기 평균으로 이어 붙였다(추정 위의 추정).</>
              ) : (
                <> <strong className="text-slate-400">연간 컨센서스가 없어 계산하지 않았다.</strong>{" "}
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

        <Note>
          ※ 증권사 화면에 나오는 <strong>후행 PER</strong>(과거 12개월 EPS 기준)은 일부러
          싣지 않았다. 실적이 급가속하면 분모(EPS)가 뒤처져 크게 과대평가되는데, 이 시스템이
          겨냥하는 구간이 정확히 거기다. 나란히 두면 큰 쪽에 눈이 가서
          &ldquo;이미 비싸다&rdquo;는 정반대 결론이 나온다.
          {price?.pbr != null && (
            <span className="mt-1 block text-slate-600">
              참고 — PBR {price.pbr.toFixed(2)}배 (주가 ÷ 주당 순자산)
            </span>
          )}
        </Note>
      </Card>

      {/* 7. LLM 분석 */}
      <Card title="LLM 분석">
        {analysis.isEmpty ? (
          <p className="text-sm text-slate-500">
            아직 분석하지 않았다. 게이트 통과 상위 종목만 분석한다(비용 설계).
          </p>
        ) : (
          <div className="space-y-4 text-sm">
            {analysis.thesis && (
              <p className="text-base font-medium text-slate-100">💡 {analysis.thesis}</p>
            )}
            {analysis.whyNow && (
              <div>
                <div className="text-xs font-semibold uppercase text-slate-500">왜 지금인가</div>
                <p className="text-slate-300">{analysis.whyNow}</p>
              </div>
            )}
            {(analysis.structuralDrivers.length > 0 || analysis.temporaryDrivers.length > 0) && (
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <div className="text-xs font-semibold uppercase text-slate-500">구조적 동인</div>
                  <ul className="list-disc pl-4 text-slate-300">
                    {analysis.structuralDrivers.map((d) => <li key={d}>{d}</li>)}
                  </ul>
                </div>
                <div>
                  <div className="text-xs font-semibold uppercase text-slate-500">일시적 동인</div>
                  <ul className="list-disc pl-4 text-slate-300">
                    {analysis.temporaryDrivers.map((d) => <li key={d}>{d}</li>)}
                  </ul>
                </div>
              </div>
            )}
            {analysis.sustainabilityQuarters != null && (
              <p className="text-slate-300">
                가속 지속 전망: <strong>{analysis.sustainabilityQuarters}개 분기</strong>
              </p>
            )}
            {analysis.scenarios.length > 0 && (
              <div>
                <div className="text-xs font-semibold uppercase text-slate-500">시나리오</div>
                <div className="mt-1 space-y-1">
                  {analysis.scenarios.map((s) => (
                    <div key={s.name} className="flex gap-2">
                      <span className="w-12 shrink-0 uppercase text-slate-400">{s.name}</span>
                      <span className="w-14 shrink-0 text-slate-300">
                        {s.probability != null ? `${(s.probability * 100).toFixed(0)}%` : DASH}
                      </span>
                      <span className="text-slate-400">{s.description ?? DASH}</span>
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
            {analysis.triggers3m.length > 0 && (
              <div>
                <div className="text-xs font-semibold uppercase text-slate-500">3개월 내 트리거</div>
                <ul className="list-disc pl-4 text-slate-300">
                  {analysis.triggers3m.map((t, i) => (
                    <li key={i}>
                      {t.event ?? DASH}
                      {t.metric && ` — ${t.metric}`}
                      {t.expectedDate && ` (${t.expectedDate})`}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {analysis.risks.length > 0 && (
              <div>
                <div className="text-xs font-semibold uppercase text-slate-500">리스크</div>
                <table className="mt-1 w-full text-left text-xs">
                  <thead className="text-slate-500">
                    <tr>
                      <th className="py-1">리스크</th>
                      <th className="py-1">발생</th>
                      <th className="py-1">영향</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analysis.risks.map((r, i) => (
                      <tr key={i} className="border-t border-slate-800/60">
                        <td className="py-1 text-slate-300">{r.risk ?? DASH}</td>
                        <td className="py-1 text-slate-400">{r.likelihood ?? DASH}</td>
                        <td className="py-1 text-slate-400">{r.impact ?? DASH}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {analysis.whyIMightBeWrong && (
              <div>
                <div className="text-xs font-semibold uppercase text-slate-500">
                  내가 틀릴 수 있는 이유
                </div>
                <p className="text-slate-300">{analysis.whyIMightBeWrong}</p>
              </div>
            )}
          </div>
        )}
      </Card>

      {/* 8. 용어 — 이 화면의 모든 숫자가 무슨 뜻인지 */}
      <Card title="이 화면의 용어" note="숫자마다 무엇을 재는지">
        <Glossary
          sections={[
            { title: "무엇을 찾는가", terms: ["실적가속", "가속", "YoY", "게이트", "판정불가"] },
            { title: "재무", terms: ["매출액", "영업이익", "OPM", "TTM매출", "잠정", "확정", "기저효과"] },
            { title: "스코어", terms: ["스코어", "A축", "B축", "C축", "D축"] },
            { title: "반영도·등급", terms: ["반영도", "p1", "p2", "p3", "p4", "등급"] },
            { title: "밸류에이션", terms: ["PER최근4분기", "PER선행", "컨센서스", "서프라이즈"] },
          ]}
        />
        <Note>
          전체 용어는 <Link href="/settings" className="text-sky-500 hover:underline">설정</Link>{" "}
          화면에 모아 두었다. 표 머리글과 밑줄 친 낱말에 마우스를 올리면 같은 설명이 뜬다.
        </Note>
      </Card>

      {/* 9. 바깥 링크 */}
      <div className="flex flex-wrap items-center gap-4 text-sm">
        <Link href="/" className="text-sky-400 hover:underline">← 발굴 목록</Link>
        <a
          href={naverStockUrl(code)}
          target="_blank"
          rel="noreferrer"
          className="text-sky-400 hover:underline"
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
            className="text-sky-400 hover:underline"
            title={latestDisclosure.report_nm ?? undefined}
          >
            DART 공시 원문 ↗
          </a>
        ) : (
          <a
            href={naverDisclosureUrl(code)}
            target="_blank"
            rel="noreferrer"
            className="text-slate-400 hover:underline"
            title="이 종목의 DART 접수번호를 아직 수집하지 못했다 — 네이버 공시 목록으로 연결한다"
          >
            공시 목록(네이버) ↗
          </a>
        )}
      </div>

      {disclosures.length > 0 && (
        <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
          <h2 className="mb-2 text-sm font-semibold text-slate-300">최근 공시</h2>
          <ul className="space-y-1 text-sm">
            {disclosures.map((d) => (
              <li key={d.rcept_no} className="flex flex-wrap gap-2">
                <span className="w-24 shrink-0 text-xs text-slate-500">
                  {d.disclosed_at?.slice(0, 10) ?? DASH}
                </span>
                <a
                  href={dartReportUrl(d.rcept_no)}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sky-400 hover:underline"
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
