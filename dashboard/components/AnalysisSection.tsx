// PRD Ref: §9.1 · §7.2 — LLM 분석 본문
//
// ★ 서버 컴포넌트다("use client" 없음). 순수 렌더라 상태가 필요 없다.
//
// ★★ **이 카드는 '분기 히스토리' 바로 아래에 온다**(사용자 지정 2026-08-22).
//   숫자를 본 직후에 해석을 읽어야 대조가 된다 — 밸류에이션·컨센서스를 지나
//   맨 아래에 있으면 스크롤을 내리는 동안 방금 본 숫자를 잊는다.
//
// ★★ **검증이 해석보다 먼저 온다.** 모델이 쓴 스토리를 읽기 전에
//   "그래서 그게 실적으로 확인됐나"를 먼저 보여준다. 순서를 바꾸면
//   그럴듯한 서술을 읽은 뒤에 검증을 보게 되어 이미 설득된 상태가 된다.
import TriggerTimeline, { type TimelineItem } from "@/components/TriggerTimeline";
import Emphasized, { Highlighted } from "@/components/Emphasized";
import type { AnalysisView } from "@/lib/analysis";
import type { NarrativeCheck, Verdict } from "@/lib/narrativeCheck";
import { DASH } from "@/lib/format";

/** 밸류에이션 두 배수. 화면이 계산해 넘긴다 — LLM 문장의 숫자를 믿지 않는다. */
export interface ValuationView {
  per4q: number | null;
  perForward: number | null;
  forwardBasis: string | null;
  pbr: number | null;
  ttmNp: number | null;
}

/**
 * LLM 산문 한 문단. **숫자와 방향어를 굵게** 집어 준다.
 *
 * ★ 모델은 `**`를 잘 쓰지 않는다. 그렇다고 문단을 통째로 굵게 하면 강조가 죽으므로
 *   `Highlighted`가 숫자·단위·방향어만 집는다(문장은 그대로 둔다).
 */
function Prose({ text }: { text: string }) {
  return (
    <p className="mt-1 text-sm leading-relaxed text-slate-100">
      <Highlighted text={text} />
    </p>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return <p className="mt-1 text-xs leading-relaxed text-slate-300">{children}</p>;
}

const VERDICT_STYLE: Record<Verdict, string> = {
  확인: "border-emerald-500/60 bg-emerald-500/10 text-emerald-200",
  미달: "border-rose-500/60 bg-rose-500/10 text-rose-200",
  판정불가: "border-slate-600 bg-slate-700/30 text-slate-200",
};

const SCENARIO_STYLE: Record<string, { border: string; chip: string }> = {
  bull: { border: "border-emerald-500/70", chip: "bg-emerald-500/15 text-emerald-200" },
  base: { border: "border-slate-500/70", chip: "bg-slate-500/20 text-slate-100" },
  bear: { border: "border-rose-500/70", chip: "bg-rose-500/15 text-rose-200" },
};

/**
 * 내러티브 검증 블록.
 *
 * ★ 검증할 게 없으면 **"검증 대기"라고 말한다.** 없는 검증을 "이상 없음"으로
 *   바꿔치기하면 가장 위험한 초록불이 된다.
 */
function NarrativeBlock({ check }: { check: NarrativeCheck }) {
  return (
    <div className="rounded-lg border border-indigo-700/60 bg-indigo-950/20 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold uppercase text-indigo-200">
          내러티브 검증 — 스토리대로 실적이 나오고 있나
        </span>
        <span className="rounded border border-slate-600 bg-slate-800/60 px-1.5 py-0.5 text-[11px] text-slate-200">
          분석 {check.analyzedQuarter ?? DASH}
          {check.quartersSince > 0 && ` → 이후 ${check.quartersSince}개 분기 발표`}
        </span>
      </div>

      <p className="mt-2 text-sm text-slate-100">
        <Emphasized text={check.headline} />
      </p>

      {check.checks.length > 0 && (
        <table className="mt-3 w-full text-left text-xs">
          <thead className="text-slate-300">
            <tr>
              <th className="py-1 font-medium">지표</th>
              <th className="py-1 font-medium">분석 시점 → 이후 실적</th>
              <th className="py-1 font-medium">판정</th>
            </tr>
          </thead>
          <tbody>
            {check.checks.map((c) => (
              <tr key={c.label} className="border-t border-slate-800/60 align-top">
                <td className="py-1.5 pr-2 text-slate-100">{c.label}</td>
                <td className="py-1.5 pr-2 tabular-nums text-slate-100">
                  {c.detail}
                  {c.note && <span className="ml-2 text-slate-300">{c.note}</span>}
                </td>
                <td className="py-1.5">
                  <span className={`rounded border px-1.5 py-0.5 ${VERDICT_STYLE[c.verdict]}`}>
                    {c.verdict}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {/* ★ 정합성 검사 — 스키마가 강제하지 못하는 것들이다. 통과해도 조용히 넘어가고
          어긋날 때만 드러낸다. 매번 초록 배지를 띄우면 아무도 안 읽게 된다. */}
      <div className="mt-3 space-y-1 text-xs">
        {check.probabilityOk === false && check.probabilitySum != null && (
          <p className="text-amber-300">
            ⚠ 시나리오 확률 합이 {check.probabilitySum.toFixed(2)}다 (1.00이어야 한다) —
            모델이 확률을 일관되게 잡지 못했다는 뜻이므로 시나리오 가중치를 그대로 믿지 마라.
          </p>
        )}
        {check.overdueTriggers > 0 && (
          <p className="text-amber-300">
            ⚠ 예상 시점이 이미 지난 트리거가 {check.overdueTriggers}건이다 — 아래 타임라인에서
            그 사건이 실제로 일어났는지 확인 지표로 대조하라.
          </p>
        )}
        {check.sustainabilityNote && (
          <p className="text-slate-300">{check.sustainabilityNote}</p>
        )}
      </div>

      <Note>
        문장 속 숫자를 긁어내 비교하지 않는다 — 그 숫자가 매출인지 목표주가인지 알 수 없어
        <strong className="text-slate-200"> 대부분 맞다가 가끔 조용히 틀린다.</strong>{" "}
        대신 분석 이후 <strong className="text-slate-200">실제로 발표된 분기</strong>와만 대조한다.
      </Note>
    </div>
  );
}

export default function AnalysisSection({
  analysis,
  narrative,
  timelineItems,
  valuation,
}: {
  analysis: AnalysisView;
  narrative: NarrativeCheck;
  timelineItems: TimelineItem[];
  /** ★ 화면이 직접 계산한 배수. LLM 문장에 적힌 PER은 믿지 않는다. */
  valuation: ValuationView;
}) {
  if (analysis.isEmpty) {
    return (
      <p className="text-sm text-slate-300">
        아직 분석하지 않았다. 성장 가속 종목은 순차적으로 전부 분석한다.
      </p>
    );
  }

  return (
    <div className="space-y-4 text-sm">
      {analysis.thesis && (
        <p className="text-base font-medium text-slate-100">💡 {analysis.thesis}</p>
      )}

      {/* ★ 검증을 해석보다 먼저 놓는다 — 설득되기 전에 대조부터 한다. */}
      <NarrativeBlock check={narrative} />

      {analysis.whyNow && (
        <div>
          <div className="text-xs font-semibold uppercase text-slate-300">왜 지금인가</div>
          <Prose text={analysis.whyNow} />
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
            {/* ★ 원인과 전망이 이 분석의 핵심이다(사용자 지정) — 테두리를 굵게 준다. */}
            {analysis.earningsChange.cause && (
              <div className="rounded border-l-4 border-sky-400 bg-sky-950/25 py-2 pl-3 pr-2">
                <div className="text-xs font-bold uppercase tracking-wide text-sky-200">
                  ① 이번 분기 숫자가 왜 그렇게 나왔나 (원인)
                </div>
                <Prose text={analysis.earningsChange.cause} />
              </div>
            )}
            {analysis.earningsChange.effect && (
              <div className="border-l-2 border-violet-500/70 pl-3">
                <div className="text-xs font-bold text-violet-200">무엇이 달라졌나 (결과)</div>
                <Prose text={analysis.earningsChange.effect} />
              </div>
            )}
            {analysis.earningsChange.outlook && (
              <div className="rounded border-l-4 border-amber-400 bg-amber-950/25 py-2 pl-3 pr-2">
                <div className="text-xs font-bold uppercase tracking-wide text-amber-200">
                  ② 다음 분기 실적 전망
                </div>
                <Prose text={analysis.earningsChange.outlook} />
              </div>
            )}
          </div>
        </div>
      )}

      {/* ★ 성장 엔진 — 예전에는 `acceleration_quality.structural_drivers`를 읽어
          **항상 비어 있었다.** 저장되는 곳은 `growth_engine`이다(2026-08-22 수정). */}
      {(analysis.growthEngine.drivers.length > 0 || analysis.growthEngine.evidence) && (
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold uppercase text-slate-200">성장 엔진</span>
            {analysis.growthEngine.nature && (
              <span
                className={`rounded border px-1.5 py-0.5 text-[11px] ${
                  analysis.growthEngine.nature === "structural"
                    ? "border-emerald-500/60 bg-emerald-500/10 text-emerald-200"
                    : "border-amber-500/60 bg-amber-500/10 text-amber-200"
                }`}
                title={
                  analysis.growthEngine.nature === "structural"
                    ? "계속 이어질 성격 — 가속이 길다"
                    : "이번만 통한 성격 — 곧 꺾일 수 있다"
                }
              >
                {analysis.growthEngine.nature === "structural" ? "구조적" : "일시적"}
              </span>
            )}
          </div>
          {analysis.growthEngine.drivers.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {analysis.growthEngine.drivers.map((d) => (
                <span key={d} className="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-100">
                  {d}
                </span>
              ))}
            </div>
          )}
          {analysis.growthEngine.evidence && (
            <Prose text={analysis.growthEngine.evidence} />
          )}
        </div>
      )}

      {analysis.baseEffectAssessment && (
        <div>
          <div className="text-xs font-semibold uppercase text-slate-300">
            기저효과 판단
            {analysis.isGenuine != null && (
              <span
                className={`ml-2 rounded border px-1.5 py-0.5 text-[11px] normal-case ${
                  analysis.isGenuine
                    ? "border-emerald-500/60 bg-emerald-500/10 text-emerald-200"
                    : "border-rose-500/60 bg-rose-500/10 text-rose-200"
                }`}
              >
                {analysis.isGenuine ? "진짜 가속으로 봄" : "가속으로 보기 어려움"}
              </span>
            )}
          </div>
          <Prose text={analysis.baseEffectAssessment} />
        </div>
      )}

      {/* ★★ 시나리오 — **`condition` + `implication`이다.**
          예전에는 있지도 않은 `description` 키를 읽어 본문이 항상 '—'였다.
          확률만 보이니 모델이 성의 없이 답한 것처럼 읽혔지만 내용은 멀쩡히 있었다. */}
      {analysis.scenarios.length > 0 && (
        <div>
          <div className="text-xs font-semibold uppercase text-slate-200">시나리오</div>
          <Note>
            <strong className="text-slate-200">조건</strong>은 “무엇이 관측되면 이 시나리오인가”다 —
            다음 분기 실적이 나오면 이 문장과 직접 대조하면 된다.
          </Note>
          <div className="mt-2 space-y-2">
            {[...analysis.scenarios]
              // 확률이 큰 것부터. 순서가 곧 "무엇을 기본으로 볼 것인가"다.
              .sort((a, b) => (b.probability ?? -1) - (a.probability ?? -1))
              .map((s) => {
                const style = SCENARIO_STYLE[s.name] ?? SCENARIO_STYLE.base;
                return (
                  <div
                    key={s.name}
                    className={`rounded border-l-4 ${style.border} border-y border-r border-slate-800 bg-slate-950/40 p-3`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={`rounded px-2 py-0.5 text-xs font-bold ${style.chip}`}>
                        {s.label}
                      </span>
                      <span className="text-sm font-semibold tabular-nums text-white">
                        {s.probability != null ? `${(s.probability * 100).toFixed(0)}%` : DASH}
                      </span>
                    </div>
                    <div className="mt-2 space-y-1.5 text-sm">
                      <p className="text-slate-100">
                        <span className="mr-1.5 text-xs font-bold text-slate-300">조건</span>
                        {s.condition ? <Highlighted text={s.condition} /> : DASH}
                      </p>
                      <p className="text-slate-200">
                        <span className="mr-1.5 text-xs font-bold text-slate-300">함의</span>
                        {s.implication ? <Highlighted text={s.implication} /> : DASH}
                      </p>
                    </div>
                  </div>
                );
              })}
          </div>
        </div>
      )}

      {/* ★ 트리거가 하나도 없을 때 **그냥 사라지면 안 된다** — 읽는 사람은
          "분석이 덜 됐나" 하고 만다. 왜 비었는지를 밝힌다(2026-08-23).
          실제 원인: LLM 입력에 공시 원문 발췌가 들어가지 않아 증설·신제품 같은
          사건을 알 방법이 없다. 숫자표만으로 사건을 쓰라고 하면 지어내게 된다. */}
      {timelineItems.length === 0 && (
        <div className="rounded-lg border border-slate-700 bg-slate-950/40 p-4">
          <div className="text-xs font-semibold uppercase text-slate-200">주가 상승 트리거</div>
          <p className="mt-1.5 text-sm text-slate-100">
            <strong className="text-amber-300">확인 가능한 상승 이벤트를 찾지 못했다.</strong>{" "}
            이 분석의 입력은 분기 실적 표가 중심이라 CAPA 증설·신제품 출시·고객사 협업 같은
            사건은 공시 원문을 읽어야 알 수 있다.
          </p>
          <Note>
            비어 있는 것은 <strong className="text-slate-200">이벤트가 없다는 뜻이 아니라
            이 입력으로는 알 수 없다는 뜻</strong>이다 — 없는 사건을 지어내지 않는다.
          </Note>
        </div>
      )}

      {/* ★ 주가 상승 트리거 — 이 분석에서 가장 실행에 가까운 부분이라
          목록이 아니라 **타임라인**으로 그린다. 시점 순서가 곧 판단이다. */}
      {timelineItems.length > 0 && (
        <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-4">
          <div className="text-xs font-semibold uppercase text-slate-200">
            주가 상승 트리거 ({timelineItems.length}건)
          </div>
          <Note>
            앞으로 주가를 올릴 수 있는 사건을 성격 구분 없이 모두 담는다 — 성장 스토리 ·
            CAPA 확장 · 지역 진출 · 신제품 · 신규 수주 · 인증/규제 · 전방 수요 · 수급까지.
            각 항목에 <strong className="text-slate-200">확인 지표</strong>가 붙어 있어 나중에
            일어났는지 대조할 수 있다.
          </Note>
          <div className="mt-3">
            <TriggerTimeline items={timelineItems} />
          </div>
        </div>
      )}

      {/* 주가가 이미 아는 것 / 아직 모르는 것 — PRI 숫자의 말풀이다. */}
      {(analysis.pricePosition.pricedIn.length > 0 ||
        analysis.pricePosition.notPricedIn.length > 0 ||
        analysis.pricePosition.reason) && (
        <div className="rounded-lg border border-slate-700 bg-slate-950/40 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold uppercase text-slate-200">주가 위치</span>
            {analysis.pricePosition.verdict && (
              <span className="rounded border border-slate-600 bg-slate-800/60 px-1.5 py-0.5 text-[11px] text-slate-100">
                {analysis.pricePosition.verdict}
              </span>
            )}
          </div>
          {/* ★★ PER은 **화면이 계산한 값**을 먼저 보여준다(사용자 지적 2026-08-23).
              `price_snapshots.per`는 직전 사업연도 EPS 기준이라 가속 구간에서 2~3배
              과대평가된다 — 실측: 고영 스냅샷 131.6 vs 실제 40.5.
              2026-08-23 이전에 저장된 분석 본문에는 그 틀린 숫자가 남아 있다. */}
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            <div className="rounded border border-slate-700 bg-slate-950/50 px-3 py-2">
              <div className="text-[11px] text-slate-300">① 최근 4개 분기 순이익 기준 PER</div>
              <div className="mt-0.5 text-xl font-bold text-white">
                {valuation.per4q != null ? `${valuation.per4q.toFixed(1)}배` : DASH}
              </div>
              <div className="text-[11px] text-slate-300">
                {valuation.per4q != null
                  ? "실제로 번 돈 기준 (추정 없음)"
                  : "4개 분기가 안 모였거나 누적 순이익 0 이하"}
              </div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/50 px-3 py-2">
              <div className="text-[11px] text-slate-300">② 향후 4개 분기 선행 PER</div>
              <div className="mt-0.5 text-xl font-bold text-amber-200">
                {valuation.perForward != null ? `${valuation.perForward.toFixed(1)}배` : DASH}
              </div>
              <div className="text-[11px] text-slate-300">
                {valuation.forwardBasis ?? "연간 컨센서스 없음"}
              </div>
            </div>
            <div className="rounded border border-slate-700 bg-slate-950/50 px-3 py-2">
              <div className="text-[11px] text-slate-300">PBR</div>
              <div className="mt-0.5 text-xl font-bold text-white">
                {valuation.pbr != null ? `${valuation.pbr.toFixed(2)}배` : DASH}
              </div>
              <div className="text-[11px] text-slate-300">주가 ÷ 주당 순자산</div>
            </div>
          </div>
          <p className="mt-1.5 text-[11px] text-slate-300">
            위 세 숫자는 <strong className="text-slate-200">화면이 직접 계산한 값</strong>이다.
            아래 해석 본문의 PER과 다르면{" "}
            <strong className="text-amber-300">위 숫자가 맞다</strong> — 증권사 화면의 후행 PER은
            직전 사업연도 이익 기준이라 실적이 급가속하면 2~3배 부풀려진다.
          </p>

          {analysis.pricePosition.reason && <Prose text={analysis.pricePosition.reason} />}

          {/* ★ 과거부터 지금까지 주가가 왜 이렇게 움직였나 — 2026-08-23 추가.
              그 전 분석에는 없는 필드라 있을 때만 그린다. */}
          {analysis.pricePosition.priceHistory && (
            <div className="mt-3 rounded border-l-4 border-indigo-400 bg-indigo-950/25 py-2 pl-3 pr-2">
              <div className="text-xs font-bold uppercase tracking-wide text-indigo-200">
                주가는 왜 지금 이 자리에 있나 — 구간별 원인
              </div>
              <Prose text={analysis.pricePosition.priceHistory} />
            </div>
          )}

          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <div>
              <div className="text-xs font-bold text-slate-300">이미 반영된 것</div>
              <ul className="mt-1 list-disc pl-4 text-slate-200">
                {analysis.pricePosition.pricedIn.length > 0
                  ? analysis.pricePosition.pricedIn.map((v) => (
                      <li key={v}><Highlighted text={v} /></li>
                    ))
                  : <li className="list-none text-slate-300">{DASH}</li>}
              </ul>
            </div>
            <div>
              <div className="text-xs font-bold text-amber-200">아직 반영되지 않은 것</div>
              <ul className="mt-1 list-disc pl-4 text-slate-100">
                {analysis.pricePosition.notPricedIn.length > 0
                  ? analysis.pricePosition.notPricedIn.map((v) => (
                      <li key={v}><Highlighted text={v} /></li>
                    ))
                  : <li className="list-none text-slate-300">{DASH}</li>}
              </ul>
            </div>
          </div>
        </div>
      )}

      {analysis.risks.length > 0 && (
        <div>
          <div className="text-xs font-semibold uppercase text-slate-300">리스크</div>
          <table className="mt-1 w-full text-left text-xs">
            <thead className="text-slate-300">
              <tr>
                <th className="py-1 font-medium">리스크</th>
                <th className="py-1 font-medium">발생</th>
                <th className="py-1 font-medium">영향</th>
                <th className="py-1 font-medium">확인 지표</th>
              </tr>
            </thead>
            <tbody>
              {analysis.risks.map((r, i) => (
                <tr key={i} className="border-t border-slate-800/60 align-top">
                  <td className="py-1 pr-2 text-slate-100">{r.risk ?? DASH}</td>
                  <td className="py-1 pr-2 text-slate-200">{r.likelihood ?? DASH}</td>
                  <td className="py-1 pr-2 text-slate-200">{r.impact ?? DASH}</td>
                  <td className="py-1 text-slate-200">{r.watchMetric ?? DASH}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {analysis.nextDataToWatch.length > 0 && (
        <div>
          <div className="text-xs font-semibold uppercase text-slate-300">
            다음 분기에 확인할 것
          </div>
          <ul className="mt-1 list-disc pl-4 text-slate-100">
            {analysis.nextDataToWatch.map((v) => <li key={v}>{v}</li>)}
          </ul>
        </div>
      )}

      {analysis.howICouldBeWrong && (
        <div>
          <div className="text-xs font-semibold uppercase text-slate-300">
            내가 틀릴 수 있는 이유
          </div>
          <Prose text={analysis.howICouldBeWrong} />
        </div>
      )}
    </div>
  );
}
