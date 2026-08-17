// PRD Ref: §2 검토⑥, §9 /outcome — 결과 추적
//
// ★★ **이 화면이 답해야 하는 질문(사용자 지정):**
//   "과거 실적 시즌으로 돌아간다면 어떤 특징의 섹터·종목을 언제 샀어야 최고였나?"
//   "그래서 이번 시즌엔 무엇을 해야 하나?"
//
// ★ 표본이 없으면 **결론을 내지 않는다.** 2건으로 "반도체가 최고"라고 쓰면
//   그럴듯하게 읽히지만 완전히 틀린 조언이 된다.
import Link from "next/link";
import { HORIZONS, HORIZON_MEANING, horizonLabel, type Horizon, getOutcomes } from "@/lib/outcome";
import {
  FEATURE_GROUPS,
  MIN_SAMPLE,
  buildInsights,
  crosstab,
  enrich,
  seasonPlaybook,
  timingProfile,
  topGroups,
  type Cell,
  type Insight,
  type Row,
} from "@/lib/retrospect";
import { getAllScreens, getFundamentalsForQuarters, getUniverse } from "@/lib/queries";
import {
  MIN_SECTOR_SAMPLE,
  aggregateSectors,
  outlook,
  risingSectors,
  usableSectors,
} from "@/lib/sectorEarnings";
import { playFor, projectSector } from "@/lib/sectorPlaybook";
import { DASH } from "@/lib/format";
import type { ScreenRow } from "@/lib/types";

export const dynamic = "force-dynamic";

function Card({ title, note, children }: {
  title: string; note?: string; children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
      <h2 className="text-base font-semibold text-white">{title}</h2>
      {note && <p className="mb-3 mt-0.5 text-sm text-slate-200">{note}</p>}
      {children}
    </section>
  );
}

function pp(value: number | null): string {
  if (value == null) return DASH;
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}`;
}

function toneOf(value: number | null): string {
  if (value == null) return "text-slate-300";
  if (value > 0) return "text-rose-300";
  if (value < 0) return "text-sky-300";
  return "text-slate-100";
}

/** `**강조**`를 실제 강조로 바꾼다. 인사이트 문장이 평평하면 안 읽힌다. */
function Emphasized({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\*\*[^*]+\*\*)/).map((part, i) =>
        part.startsWith("**") && part.endsWith("**") ? (
          <strong key={i} className="text-white">{part.slice(2, -2)}</strong>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  );
}

const CONFIDENCE_STYLE: Record<Insight["confidence"], string> = {
  확실: "border-emerald-500/60 bg-emerald-500/10 text-emerald-200",
  참고: "border-amber-500/60 bg-amber-500/10 text-amber-200",
  불충분: "border-slate-600 bg-slate-700/30 text-slate-200",
};

function CellText({ cell }: { cell: Cell }) {
  if (cell.n === 0) {
    return <span className="text-slate-300" title={`표본 ${cell.total}건 중 측정 0건`}>—</span>;
  }
  const thin = cell.n < MIN_SAMPLE;
  return (
    <span
      className={thin ? "text-slate-300" : toneOf(cell.median)}
      title={
        `측정 ${cell.n}건 / 전체 ${cell.total}건 · 평균 ${pp(cell.mean)}%p · ` +
        `플러스 비율 ${((cell.winRate ?? 0) * 100).toFixed(0)}%` +
        (thin ? `\n\n표본 ${MIN_SAMPLE}건 미만 — 참고만 하라` : "")
      }
    >
      {pp(cell.median)}
      <span className="ml-1 text-xs text-slate-300">({cell.n})</span>
    </span>
  );
}

function FeatureTable({ title, note, table }: { title: string; note: string; table: Row[] }) {
  if (table.length === 0) return null;
  return (
    <div className="mb-6 last:mb-0">
      <h3 className="text-sm font-semibold text-white">{title}</h3>
      <p className="mb-2 text-xs text-slate-200">{note}</p>
      <div className="overflow-x-auto rounded border border-slate-700">
        <table className="w-full min-w-[720px] text-sm">
          <thead className="bg-slate-800 text-xs uppercase text-slate-100">
            <tr>
              <th scope="col" className="px-3 py-2 text-left font-medium">{title}</th>
              {HORIZONS.map((d) => (
                <th key={d} scope="col" className="px-3 py-2 text-right font-medium"
                    title={HORIZON_MEANING[d]}>
                  {horizonLabel(d)}
                </th>
              ))}
              <th scope="col" className="px-3 py-2 text-right font-medium">종목수</th>
            </tr>
          </thead>
          <tbody>
            {table.map((r) => (
              <tr key={r.key} className="border-t border-slate-800">
                <td className="whitespace-nowrap px-3 py-1.5 text-slate-100">{r.key}</td>
                {HORIZONS.map((d) => (
                  <td key={d} className="px-3 py-1.5 text-right tabular-nums">
                    <CellText cell={r.cells.get(d) ?? { n: 0, total: 0, median: null, mean: null, winRate: null }} />
                  </td>
                ))}
                <td className="px-3 py-1.5 text-right tabular-nums text-slate-100">{r.total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default async function OutcomePage() {
  const [outcomeResult, screensResult, universe] = await Promise.all([
    getOutcomes(),
    getAllScreens(),
    getUniverse(),
  ]);

  // ── 섹터별 실적: 최신 분기와 그 직전 분기를 비교한다 ──────────────
  // ★ 분기를 **데이터에서** 고른다. 상수로 박으면 다음 시즌에 조용히 낡는다(T36).
  const quarterIndexes = [
    ...new Set(screensResult.rows.map((s) => s.fiscal_year * 4 + (s.fiscal_quarter - 1))),
  ].sort((a, b) => b - a);
  const toYQ = (i: number) => ({ year: Math.floor(i / 4), quarter: (i % 4) + 1 });
  const curQ = quarterIndexes.length > 0 ? toYQ(quarterIndexes[0]) : null;
  const prevQ = curQ ? toYQ(quarterIndexes[0] - 1) : null;

  const funds = curQ && prevQ
    ? await getFundamentalsForQuarters([curQ, prevQ])
    : [];

  // ★ 분기까지 맞춘 색인을 함께 넘긴다 — 최신 행만 쓰면 분기가 쌓인 뒤
  //   2026.2Q 결과에 다른 분기 판정이 붙는다(T40).
  // 최신 행(폴백용) — 그 분기 행이 없을 때만 쓴다.
  const screens = new Map<string, ScreenRow>();
  for (const s of screensResult.rows) {
    const prev = screens.get(s.code);
    const idx = s.fiscal_year * 4 + s.fiscal_quarter;
    if (!prev || idx > prev.fiscal_year * 4 + prev.fiscal_quarter) screens.set(s.code, s);
  }
  const screensByQuarter = new Map(
    screensResult.rows.map((s) => [`${s.code}|${s.fiscal_year}|${s.fiscal_quarter}`, s])
  );
  const rows = enrich(outcomeResult.rows, universe, screens, screensByQuarter);

  const tables = new Map<string, Row[]>(
    FEATURE_GROUPS.map((g) => [g.title, crosstab(rows, g.keyOf)])
  );
  const sectorRows = curQ && prevQ
    ? aggregateSectors(universe, funds, screensByQuarter, curQ, prevQ)
    : [];
  const sectorUsable = usableSectors(sectorRows);
  const rising = risingSectors(sectorRows);
  const outlookRows = outlook(sectorRows);

  const { insights, bestTiming, caveats } = buildInsights(rows, tables);
  const playbook = seasonPlaybook(insights);
  const profile = timingProfile(rows);

  const quarters = [...new Set(rows.map((r) => `${r.fiscal_year}.${r.fiscal_quarter}Q`))].sort();
  const dates = rows.map((r) => r.announce_date).filter(Boolean).sort();

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-white">결과 추적</h1>
        <p className="mt-1 text-sm text-slate-100">
          발굴한 종목이 <strong className="text-white">실제로 올랐는가</strong>, 그리고{" "}
          <strong className="text-amber-300">언제 샀어야 했는가</strong>.
        </p>
        <p className="mt-1 text-sm text-slate-200">
          대상 <strong className="text-slate-100">{rows.length.toLocaleString("ko-KR")}건</strong>
          {quarters.length > 0 && <> · {quarters.join(", ")}</>}
          {dates.length > 0 && <> · 발표일 {dates[0]} ~ {dates[dates.length - 1]}</>}
          {" · 모든 수치는 "}
          <strong className="text-slate-100">지수 대비 초과수익(%p) 중앙값</strong>
          {"이고 괄호는 측정 표본 수다."}
        </p>
      </div>

      {outcomeResult.dropped.length > 0 && (
        <p className="rounded border border-amber-700 bg-amber-900/30 px-3 py-2 text-sm text-amber-200">
          ⚠ 아직 DB에 없는 컬럼을 제외하고 조회했다: {outcomeResult.dropped.join(", ")}.
          마이그레이션 적용 후 <code>python -m src.analysis.outcome_run --save</code>를 돌리면 채워진다.
        </p>
      )}

      {/* ═══ ① 이번 시즌 전략 — 이 화면에서 가장 위에 와야 한다 ═══ */}
      <section className="rounded-lg border-2 border-amber-600/70 bg-amber-950/20 p-4">
        <h2 className="text-lg font-bold text-amber-200">이번 실적 시즌 투자 전략</h2>
        <p className="mt-0.5 text-sm text-slate-100">
          표본이 충분한 결론만 (아래 회고 분석 근거)
        </p>
        {playbook.length > 0 ? (
          <ol className="mt-3 space-y-2">
            {playbook.map((line, i) => (
              <li key={i} className="flex gap-3 text-sm">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-amber-500/25 text-xs font-bold text-amber-200">
                  {i + 1}
                </span>
                {/* ★ Emphasized를 거쳐야 한다 — 그냥 넣으면 `**강조**`의 별표가
                    화면에 그대로 보인다(실측). */}
                <span className="text-slate-100"><Emphasized text={line} /></span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="mt-3 rounded border border-slate-600 bg-slate-900/60 px-3 py-2 text-sm text-slate-100">
            <strong className="text-white">아직 전략을 제시할 수 없다.</strong>{" "}
            결론을 내려면 시점별로 최소 {MIN_SAMPLE}건의 측정 표본이 필요한데 아직 모자란다.
            거래일이 쌓이면 자동으로 채워진다 —{" "}
            <strong className="text-amber-300">없는 근거로 조언을 만들지 않는다.</strong>
          </p>
        )}
      </section>

      {/* ═══ ② 언제 샀어야 했나 ═══ */}
      <Card
        title="언제 샀어야 했나"
        note="발표 전이 크면 정보 선반영 · 발표 후가 크면 확인 후 진입도 유효"
      >
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {profile.map(({ days, cell }) => {
            const isBest = bestTiming === days;
            return (
              <div
                key={days}
                className={`rounded-lg border p-3 ${
                  isBest ? "border-amber-500 bg-amber-500/10" : "border-slate-700 bg-slate-950/40"
                }`}
              >
                <div className="text-xs font-semibold text-slate-100">{horizonLabel(days)}</div>
                <div className={`mt-1 text-2xl font-bold tabular-nums ${toneOf(cell.median)}`}>
                  {cell.n > 0 ? `${pp(cell.median)}%p` : DASH}
                </div>
                <div className="mt-0.5 text-xs text-slate-200">
                  {cell.n > 0 ? (
                    <>
                      측정 {cell.n}건 · 플러스{" "}
                      <strong className="text-slate-100">
                        {((cell.winRate ?? 0) * 100).toFixed(0)}%
                      </strong>
                    </>
                  ) : (
                    <span className="text-slate-300">거래일 부족 — 아직 측정 전</span>
                  )}
                </div>
                <div className="mt-1 text-xs text-slate-300">{HORIZON_MEANING[days as Horizon]}</div>
                {isBest && (
                  <div className="mt-1 text-xs font-bold text-amber-200">← 가장 좋았던 구간</div>
                )}
              </div>
            );
          })}
        </div>
      </Card>

      {/* ═══ ③ 회고 분석 — 무엇을 샀어야 했나 ═══ */}
      <Card
        title="과거 시즌으로 돌아간다면 — 무엇을 샀어야 했나"
        note="숫자에서 직접 뽑은 결론 (LLM 미사용)"
      >
        {insights.length > 0 ? (
          <div className="space-y-3">
            {insights.map((ins, i) => (
              <div key={i} className="rounded border border-slate-700 bg-slate-950/40 p-3">
                <div className="flex flex-wrap items-start gap-2">
                  <span
                    className={`shrink-0 rounded border px-1.5 py-0.5 text-xs font-semibold ${CONFIDENCE_STYLE[ins.confidence]}`}
                    title={
                      ins.confidence === "확실"
                        ? `표본 ${MIN_SAMPLE * 3}건 이상`
                        : ins.confidence === "참고"
                          ? `표본 ${MIN_SAMPLE}~${MIN_SAMPLE * 3}건 — 방향만 참고`
                          : `표본 ${MIN_SAMPLE}건 미만 — 결론으로 쓰지 마라`
                    }
                  >
                    {ins.confidence}
                  </span>
                  <p className="flex-1 text-sm text-slate-100">
                    <Emphasized text={ins.headline} />
                  </p>
                </div>
                <p className="mt-1.5 pl-1 font-mono text-xs text-slate-200">{ins.evidence}</p>
                {ins.action && (
                  <p className="mt-1.5 border-l-2 border-amber-500/60 pl-2 text-sm text-amber-100">
                    → {ins.action}
                  </p>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="rounded border border-slate-600 bg-slate-950/40 px-3 py-3 text-sm text-slate-100">
            <strong className="text-white">아직 결론을 낼 표본이 없다.</strong>{" "}
            발표 후 20·60일은 거래일이 더 지나야 채워진다. 이 화면은 표본이 모이는 대로
            자동으로 결론을 만들어 낸다 —{" "}
            <strong className="text-amber-300">지금 없는 것을 지어내지 않는다.</strong>
          </p>
        )}

        {caveats.length > 0 && (
          <div className="mt-3 rounded border border-slate-600 bg-slate-900/60 px-3 py-2 text-xs text-slate-100">
            {caveats.map((c, i) => <p key={i}>⚠ {c}</p>)}
          </div>
        )}
      </Card>

      {/* ═══ ④ 섹터별 실적 — 어디가 잘 나왔나 (사용자 요청) ═══ */}
      <Card
        title={`섹터별 실적 — ${curQ ? `${curQ.year}.${curQ.quarter}Q` : "—"}`}
        note={`성장률 중앙값 + 가속 종목 비율(= 이 시스템의 서프라이즈) · 종목 ${MIN_SECTOR_SAMPLE}개 미만 섹터 제외`}
      >
        {sectorUsable.length > 0 ? (
          <div className="max-h-[60vh] overflow-auto rounded border border-slate-700">
            <table className="w-full min-w-[760px] text-sm">
              <thead className="sticky top-0 z-20 bg-slate-800 text-xs uppercase text-slate-100">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left font-medium">섹터</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">종목</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">매출 YoY</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">영업익 YoY</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium"
                      title="매출·이익 성장률이 둘 다 가속한 종목 비율">
                    가속 비율
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-medium"
                      title="지난 분기 대비 가속 종목 비율의 변화 — 서프라이즈가 늘었나">
                    전분기 대비
                  </th>
                </tr>
              </thead>
              <tbody>
                {sectorUsable.map((r, i) => (
                  <tr key={r.sector} className="border-t border-slate-800">
                    <td className="whitespace-nowrap px-3 py-1.5">
                      <span className={i < 3 ? "font-bold text-amber-200" : "text-slate-100"}>
                        {i < 3 && <span className="mr-1">{["①", "②", "③"][i]}</span>}
                        {r.sector}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-slate-200">{r.n}</td>
                    <td className={`px-3 py-1.5 text-right font-semibold tabular-nums ${toneOf(r.revenueYoy)}`}>
                      {r.revenueYoy == null ? DASH : `${r.revenueYoy >= 0 ? "+" : ""}${r.revenueYoy.toFixed(1)}%`}
                    </td>
                    <td className={`px-3 py-1.5 text-right tabular-nums ${toneOf(r.opYoy)}`}>
                      {r.opYoy == null ? DASH : `${r.opYoy >= 0 ? "+" : ""}${r.opYoy.toFixed(1)}%`}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-slate-100">
                      {r.accelRate == null ? DASH : `${(r.accelRate * 100).toFixed(0)}%`}
                      <span className="ml-1 text-xs text-slate-300">({r.accelerated})</span>
                    </td>
                    <td className={`px-3 py-1.5 text-right tabular-nums ${toneOf(r.accelRateDelta)}`}>
                      {r.accelRateDelta == null
                        ? DASH
                        : `${r.accelRateDelta >= 0 ? "+" : ""}${r.accelRateDelta.toFixed(0)}%p`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="rounded border border-slate-600 bg-slate-950/40 px-3 py-3 text-sm text-slate-100">
            섹터 집계를 만들 데이터가 아직 없다. <code>krx_universe.sector</code> 마이그레이션과{" "}
            <code>python -m src.universe.sector_map --save</code>가 필요하다.
          </p>
        )}

        {rising.length > 0 && (
          <div className="mt-4 rounded-lg border border-emerald-700/60 bg-emerald-950/20 p-3">
            <div className="text-sm font-bold text-emerald-200">
              지난 분기보다 가속 종목이 늘어난 섹터
            </div>
            <p className="mt-0.5 text-xs text-slate-200">
              개별 종목이 아니라 섹터 전체가 좋아지는 신호
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              {rising.map((r, i) => (
                <span key={r.sector}
                      className={`rounded px-2 py-1 text-sm ${
                        i === 0
                          ? "bg-emerald-500/25 font-bold text-emerald-100"
                          : "bg-slate-800 text-slate-100"
                      }`}>
                  {r.sector}{" "}
                  <span className="tabular-nums">
                    {(r.prevAccelRate! * 100).toFixed(0)}% → {(r.accelRate! * 100).toFixed(0)}%
                  </span>
                  <span className="ml-1 text-xs text-emerald-200">
                    ({r.accelRateDelta! >= 0 ? "+" : ""}{r.accelRateDelta!.toFixed(0)}%p)
                  </span>
                </span>
              ))}
            </div>
          </div>
        )}
      </Card>

      {/* ═══ ⑤ 다음 분기 전망 — 섹터별 이벤트·지표·전망값 (사용자 지정) ═══ */}
      {outlookRows.length > 0 && (
        <Card
          title="다음 분기 전망 — 섹터별"
          note="성장률 범위는 이번 분기 실측에서 계산했다(예측 모델이 아니다). 이벤트·지표는 그 섹터에서 주가를 움직이는 것들이다."
        >
          <div className="space-y-3">
            {outlookRows.slice(0, 14).map((o) => {
              const row = sectorRows.find((s) => s.sector === o.sector);
              if (!row) return null;
              const proj = projectSector(row);
              const play = playFor(o.sector);
              const band = (r: [number, number] | null) =>
                r == null
                  ? DASH
                  : `${r[0] >= 0 ? "+" : ""}${r[0].toFixed(1)} ~ ${r[1] >= 0 ? "+" : ""}${r[1].toFixed(1)}%`;
              return (
                <div key={o.sector} className="rounded-lg border border-slate-700 bg-slate-950/40 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded px-2 py-0.5 text-xs font-bold ${
                      { 가속: "bg-rose-500/20 text-rose-200",
                        유지: "bg-amber-500/20 text-amber-200",
                        둔화: "bg-sky-500/20 text-sky-200",
                        판정불가: "bg-slate-700/40 text-slate-100" }[o.momentum]
                    }`}>
                      {o.momentum}
                    </span>
                    <span className="text-base font-bold text-white">{o.sector}</span>
                    <span className="text-xs text-slate-200">{row.n}종목</span>
                  </div>

                  {/* 성장률: 이번 분기 실측 → 다음 분기 예상 범위 */}
                  <table className="mt-2 text-xs">
                    <thead>
                      <tr className="text-slate-200">
                        <th className="pr-3 text-left font-medium"></th>
                        <th className="pr-3 text-right font-medium">이번 분기</th>
                        <th className="pr-3 text-right font-medium">섹터 내 범위</th>
                        <th className="pr-3 text-right font-medium">전분기 대비</th>
                        <th className="text-right font-medium text-amber-200">다음 분기 예상</th>
                      </tr>
                    </thead>
                    <tbody className="tabular-nums">
                      <tr>
                        <td className="pr-3 font-semibold text-slate-100">매출</td>
                        <td className={`pr-3 text-right font-semibold ${toneOf(row.revenueYoy)}`}>
                          {row.revenueYoy == null ? DASH : `${row.revenueYoy >= 0 ? "+" : ""}${row.revenueYoy.toFixed(1)}%`}
                        </td>
                        <td className="pr-3 text-right text-slate-200">
                          {row.revenueRange == null
                            ? DASH
                            : `${row.revenueRange[0].toFixed(0)} ~ ${row.revenueRange[1].toFixed(0)}%`}
                        </td>
                        <td className={`pr-3 text-right ${toneOf(row.revenueYoyDelta)}`}>
                          {row.revenueYoyDelta == null ? DASH : `${row.revenueYoyDelta >= 0 ? "+" : ""}${row.revenueYoyDelta.toFixed(1)}%p`}
                        </td>
                        <td className="text-right font-bold text-amber-200">{band(proj.revenue)}</td>
                      </tr>
                      <tr>
                        <td className="pr-3 font-semibold text-slate-100">영업이익</td>
                        <td className={`pr-3 text-right font-semibold ${toneOf(row.opYoy)}`}>
                          {row.opYoy == null ? DASH : `${row.opYoy >= 0 ? "+" : ""}${row.opYoy.toFixed(1)}%`}
                        </td>
                        <td className="pr-3 text-right text-slate-200">
                          {row.opRange == null
                            ? DASH
                            : `${row.opRange[0].toFixed(0)} ~ ${row.opRange[1].toFixed(0)}%`}
                        </td>
                        <td className={`pr-3 text-right ${toneOf(row.opYoyDelta)}`}>
                          {row.opYoyDelta == null ? DASH : `${row.opYoyDelta >= 0 ? "+" : ""}${row.opYoyDelta.toFixed(1)}%p`}
                        </td>
                        <td className="text-right font-bold text-amber-200">{band(proj.op)}</td>
                      </tr>
                    </tbody>
                  </table>

                  {/* 섹터별 이벤트·지표 — 일괄 문구를 대체한다 */}
                  <div className="mt-2 grid gap-2 text-xs sm:grid-cols-2">
                    <div>
                      <div className="font-semibold text-sky-200">주가를 움직일 이벤트</div>
                      <div className="mt-0.5 flex flex-wrap gap-1">
                        {play.events.map((e) => (
                          <span key={e} className="rounded bg-sky-500/15 px-1.5 py-0.5 text-sky-100">
                            {e}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div>
                      <div className="font-semibold text-violet-200">확인할 지표</div>
                      <div className="mt-0.5 flex flex-wrap gap-1">
                        {play.indicators.map((m) => (
                          <span key={m} className="rounded bg-violet-500/15 px-1.5 py-0.5 text-violet-100">
                            {m}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>

                  <p className="mt-2 text-xs text-slate-200">
                    <span className="font-semibold text-slate-100">주의 · </span>{play.risk}
                  </p>
                  <p className="mt-0.5 text-xs text-slate-200">
                    <span className="text-slate-300">근거 · </span>{o.basis}
                  </p>
                </div>
              );
            })}
          </div>
          <p className="mt-3 text-xs text-slate-200">
            <strong className="text-slate-100">다음 분기 예상</strong>은 이번 분기 중앙값을 하단,
            전분기 대비 변화의 절반을 더한 값을 상단으로 잡았다 — 성장률 변화는 평균회귀가
            강해 모멘텀을 온전히 연장하지 않는다.{" "}
            <strong className="text-amber-200">예측 모델이 아니라 &ldquo;이 추세가 이어지면
            이 범위&rdquo;라는 조건부 서술이다.</strong>{" "}
            이벤트·지표는 산업 지식으로 정리한 것이며 전망값은 여기서 오지 않는다.
          </p>
        </Card>
      )}

      {/* ═══ ⑥ 특징별 × 시점별 표 ═══ */}
      <Card
        title="특징별 · 시점별 초과수익"
        note={`칸 = 초과수익 중앙값(%p) · 괄호 = 측정 표본 · 흐린 값은 표본 ${MIN_SAMPLE}건 미만(결론 금지)`}
      >
        {FEATURE_GROUPS.map((g) => (
          <FeatureTable key={g.title} title={g.title} note={g.note} table={tables.get(g.title) ?? []} />
        ))}
      </Card>

      {/* ═══ ⑤ 시점별 최고 섹터 요약 ═══ */}
      <Card
        title="시점별 최고 섹터"
        note={`각 시점에서 초과수익 중앙값이 가장 높았던 섹터 상위 3. 표본 ${MIN_SAMPLE}건 미만 섹터는 제외했다.`}
      >
        <div className="space-y-2">
          {HORIZONS.map((d) => {
            const top = topGroups(tables.get("섹터") ?? [], d, 3);
            return (
              <div key={d} className="flex flex-wrap items-baseline gap-2 border-b border-slate-800 pb-2 last:border-b-0">
                <span className="w-24 shrink-0 text-sm font-semibold text-slate-100">
                  {horizonLabel(d)}
                </span>
                {top.length > 0 ? (
                  top.map((t, i) => (
                    <span
                      key={t.key}
                      className={`rounded px-2 py-0.5 text-sm ${
                        i === 0
                          ? "bg-amber-500/20 font-semibold text-amber-100"
                          : "bg-slate-800 text-slate-100"
                      }`}
                    >
                      {t.key} <span className="tabular-nums">{pp(t.cell.median)}%p</span>
                      <span className="ml-1 text-xs text-slate-300">({t.cell.n})</span>
                    </span>
                  ))
                ) : (
                  <span className="text-sm text-slate-300">
                    표본 {MIN_SAMPLE}건 이상인 섹터가 아직 없다
                  </span>
                )}
              </div>
            );
          })}
        </div>
      </Card>

      <p className="text-sm text-slate-200">
        발굴 목록·스크리너는 <Link href="/" className="text-sky-300 underline">한 화면</Link>에 있다
        (게이트 필터로 탈락까지 볼 수 있다).
        모든 수치는 <strong className="text-slate-100">영업일 기준</strong>이며 발표일이 휴장이면
        다음 거래일을 기준으로 잡는다.
      </p>
    </div>
  );
}
