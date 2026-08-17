// PRD Ref: §9.1 — 종목 상세. **시스템의 핵심 화면.**
import Link from "next/link";
import { notFound } from "next/navigation";
import QuarterlyChart from "@/components/QuarterlyChart";
import { toChartPoints } from "@/lib/chart";
import { GradeBadge, WarningBadges } from "@/components/Badges";
import { PriBreakdown, ScoreBreakdown } from "@/components/ScoreBreakdown";
import { readAnalysis } from "@/lib/analysis";
import { DASH, eok, growthOrLabel, marketCap, num, pct, quarterLabel } from "@/lib/format";
import {
  getAnalysis,
  getConsensus,
  getFundamentals,
  getLatestPrice,
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

/** 최근 4분기 순이익으로 PER을 다시 계산한다. KIS `per`은 후행이라 급가속 구간에서 과대평가된다. */
function trailingTtmPer(
  marketCapKrw: number | null | undefined,
  npSeries: (number | null)[]
): number | null {
  const last4 = npSeries.slice(-4);
  if (last4.length < 4 || last4.some((v) => v == null)) return null;
  const ttmNp = last4.reduce((a, b) => (a as number) + (b as number), 0) as number;
  if (!marketCapKrw || ttmNp <= 0) return null;
  return marketCapKrw / ttmNp;
}

export default async function StockPage({ params }: { params: { code: string } }) {
  const code = params.code;

  const [universe, funds, price, screenResult] = await Promise.all([
    getUniverse(),
    getFundamentals(code),
    getLatestPrice(code),
    getScreenForCode(code),
  ]);

  const stock = universe.get(code);
  if (!stock) notFound();

  const screen = screenResult.row;
  const latestFund = funds[funds.length - 1] ?? null;
  const year = screen?.fiscal_year ?? latestFund?.fiscal_year ?? null;
  const quarter = screen?.fiscal_quarter ?? latestFund?.fiscal_quarter ?? null;

  const [consensus, analysisPayload] = await Promise.all([
    year && quarter ? getConsensus(code, year, quarter) : Promise.resolve(null),
    year && quarter ? getAnalysis(code, year, quarter) : Promise.resolve(null),
  ]);
  const analysis = readAnalysis(analysisPayload);

  // 스크리너가 평가한 바로 그 분기의 재무를 쓴다 — 최신 행과 다를 수 있다.
  const evaluated =
    year && quarter
      ? funds.find((f) => f.fiscal_year === year && f.fiscal_quarter === quarter) ?? latestFund
      : latestFund;

  const perTtm = trailingTtmPer(
    price?.market_cap_krw ?? stock.market_cap_krw,
    funds.map((f) => f.np)
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

      {/* 3. 8분기 이중축 차트 */}
      <Card title="분기 실적 추이 (8분기)" note="주인공은 매출 YoY 성장률 라인이다">
        <QuarterlyChart points={toChartPoints(funds)} />
      </Card>

      {/* 4. 분기 히스토리 표 */}
      <Card title="분기 히스토리">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-right text-sm">
            <thead className="text-xs uppercase text-slate-500">
              <tr className="border-b border-slate-800">
                <th className="py-2 text-left">분기</th>
                <th className="py-2">매출</th>
                <th className="py-2">YoY</th>
                <th className="py-2">QoQ</th>
                <th className="py-2">영업이익</th>
                <th className="py-2">YoY</th>
                <th className="py-2">OPM</th>
                <th className="py-2">OPM YoY</th>
                <th className="py-2">TTM 매출</th>
                <th className="py-2 text-center">구분</th>
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

      {/* 6. 밸류에이션 */}
      <Card title="밸류에이션">
        <div className="grid gap-4 text-sm sm:grid-cols-3">
          <div>
            <div className="text-xs text-slate-500">후행 PER (과거 12개월 EPS)</div>
            <div className="text-lg">{price?.per != null ? `${price.per.toFixed(1)}배` : DASH}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500">PBR</div>
            <div className="text-lg">{price?.pbr != null ? `${price.pbr.toFixed(2)}배` : DASH}</div>
          </div>
          <div>
            <div className="text-xs text-slate-500">최근 4분기 순이익 기준 PER</div>
            <div className="text-lg">{perTtm != null ? `${perTtm.toFixed(1)}배` : DASH}</div>
          </div>
        </div>
        {price?.per != null && perTtm != null && price.per / perTtm >= 1.5 && (
          <p className="mt-3 rounded border border-amber-800/60 bg-amber-900/20 px-3 py-2 text-xs text-amber-300">
            ⚠ 후행 PER이 {(price.per / perTtm).toFixed(1)}배 과대 — 실적이 급가속해 분모(EPS)가
            뒤처져 있다. 후행 PER만 보면 &ldquo;이미 비싸다&rdquo;는 정반대 결론이 나온다.
          </p>
        )}
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

      <div className="flex gap-3 text-sm">
        <Link href="/" className="text-sky-400 hover:underline">← 발굴 목록</Link>
        <a
          href={`https://dart.fss.or.kr/dsab007/main.do?textCrpNm=${encodeURIComponent(stock.name ?? code)}`}
          target="_blank"
          rel="noreferrer"
          className="text-sky-400 hover:underline"
        >
          DART 공시 원문 ↗
        </a>
      </div>
    </div>
  );
}
