// PRD Ref: §9.3 · ADR 28 — 연 8회 추천과 검증
import Link from "next/link";
import ledger from "@/lib/season-strategies.json";
import constants from "@/lib/constants.json";
import { ReadableText } from "@/components/Emphasized";
import { stripTagLeakage } from "@/lib/analysis";

type Point = {date?: string; return?: number | null; excess?: number | null};
type Signals = {acceleration: boolean | null; revenue_yoy: number | null; op_yoy: number | null;
  op_label: string | null; quote_date: string | null; upward_revision: boolean | null;
  revision_pct: number | null; revision_label: string | null; revision_from: string | null;
  priority: string; catalysts: {event: string; date: string; check: string; status: string}[];
  flow: {foreign: boolean | null; institution: boolean | null; dates: string[]}};
type Candidate = {code: string; name: string; sector: string; grade: string; pri: number | null;
  source_quarter: string; revenue_yoy: number | null; opm: number | null;
  thesis: string | null; analysis_date: string | null; feedback_caution: boolean;
  expected_revenue: number | null; expected_op: number | null; signals?: Signals;
  investment_idea?: {business: string | null; why_now: string | null; drivers: string[]; invalidation: string};
  news: {title: string; date: string; url: string}[]};
type ReviewStock = {code: string; sector: string; base_date: string | null; horizons: Record<string, Point>;
  current: Point; trend: {return: number | null; through: string | null};
  earnings: {revenue: number | null; op: number | null; revenue_gap_pct: number | null; op_gap: number | null}};
type Plan = {id: string; created_at: string; target_year: number; target_quarter: number;
  rule_version: string; eligible: number; candidates: Candidate[]; actions: string[];
  feedback: {sector: string; n: number; seasons: number; median: number | null; action: string; applied: boolean}[];
  macro: {checkedAt: string; summary?: {current: string; forward: string};
    recentIssues?: {title: string; url: string; publishedAt: string; fact: string; marketImpact: string}[]};
  review: {stocks: ReviewStock[]; lessons: {sector: string; n: number; total: number; message: string; earnings_measured: number}[];
    summary: Record<string, {n: number; total: number; median: number | null; status: string}>}};
const pct = (v: number | null | undefined, unit = "%") => v == null ? "확인 필요" : `${v > 0 ? "+" : ""}${v.toFixed(2)}${unit}`;
const eok = (v: number | null | undefined) => v == null ? "미확인" : `${(v/1e8).toLocaleString("ko-KR", {maximumFractionDigits: 1})}억`;
function Flag({value, yes = "확인", no = "미충족"}: {value: boolean | null | undefined; yes?: string; no?: string}) {
  return <span className={`font-bold ${value === true ? "text-emerald-200" : value === false ? "text-rose-300" : "text-yellow-200"}`}>{value === true ? `✅ ${yes}` : value === false ? `🔻 ${no}` : "🔎 확인 필요"}</span>;
}
export default function SeasonStrategy() {
  const plans = [...ledger.plans].reverse() as unknown as Plan[];
  return <section className="rounded-xl border-2 border-amber-500/60 bg-slate-900/50 p-4 text-white sm:p-5">
    <h2 className="text-xl font-bold text-amber-200">🎯 다가오는 실적 시즌 투자 전략</h2>
    <div className="mt-3 grid gap-2 sm:grid-cols-3">
      <p className="rounded-lg bg-slate-950 p-3">📅 <strong className="text-yellow-200">연 8회 · 첫째 주</strong><br/>발표 전 추천을 수립합니다.</p>
      <p className="rounded-lg bg-slate-950 p-3">🔎 <strong className="text-sky-300">네 가지 상승 근거</strong><br/>실적 전망 · 상향 추세 · 촉매 · 수급</p>
      <p className="rounded-lg bg-slate-950 p-3">🔁 <strong className="text-emerald-200">검증 → 다음 전략</strong><br/>실제 실적과 D+20·40·60을 비교합니다.</p>
    </div>
    <details className="mt-3 rounded border border-slate-700 p-3"><summary className="cursor-pointer text-yellow-200">📅 분기별 시행 일정</summary><table className="mt-2 w-full text-sm"><thead><tr><th className="p-2 text-left">다가오는 발표</th><th className="p-2 text-left">추천 수립 시기</th></tr></thead><tbody>{[1,2,3,4].map(q => <tr key={q}><td className="p-2">{q}분기 실적</td><td className="p-2">{constants.strategy.months.filter(m => Math.floor((m-1)/3) === (q === 4 ? 0 : q)).map(m => `${m}월 첫째 주`).join(" · ")}</td></tr>)}</tbody></table></details>
    <p className="mt-3 text-sm">🕒 최근 검증 <strong className="text-sky-300">{ledger.checked_at ?? "대기"}</strong> · 원 전략은 보존합니다.</p>
    {ledger.errors.length > 0 && <p className="mt-2 text-rose-300">⚠️ 자료 수집 한계: {ledger.errors.join(" · ")}</p>}
    {plans.map((p, pi) => <details key={p.id} open={pi === 0} className="mt-4 rounded-xl border border-slate-700 bg-slate-950/60 p-4">
      <summary className="cursor-pointer text-lg font-bold text-amber-200">📌 {p.created_at} 추천 · {p.target_year}년 {p.target_quarter}분기 발표 대비 · {p.candidates.length}종목</summary>
      <p className="mt-3 text-sm">📊 검토 대상 {p.eligible}종목 · 🛡️ {p.rule_version}{p.rule_version === "season-v1" && " · 이전 규칙 보존본"}<br/>🕒 추천 시점 조회와 저장 전망은 아래 기준일로 구분합니다.</p>
      <p className="mt-2 text-sm">✅ 네 가지 신호 모두 확인 → <strong className="text-emerald-200">발표 전 우선 검토</strong><br/>🔎 일부 근거 미충족·미확인 → <strong className="text-yellow-200">조건부 추천</strong></p>
      <div className="mt-4 overflow-x-auto rounded-lg border border-slate-700"><table className="w-full min-w-[1040px] text-sm"><thead><tr>{["추천 종목 · 섹터", "📈 가속화 예상", "⬆️ 실적 상향", "🚀 6개월 촉매", "💰 외국인 · 기관", "추천 판단"].map(h => <th key={h} className="p-3 text-left">{h}</th>)}</tr></thead><tbody>{p.candidates.map(c => <tr key={c.code} className="align-top">
        <td className="p-3"><a href={`#idea-${p.id}-${c.code}`} className="font-bold text-sky-300 underline">{c.name} {c.grade}</a><p className="mt-1 text-yellow-200">{c.sector}</p><p>PRI {pct(c.pri, "")}</p></td>
        <td className="p-3"><Flag value={c.signals?.acceleration} yes="가속 예상" no="가속 미확인"/><p>매출 YoY {pct(c.signals?.revenue_yoy)}</p><p>영익 YoY {c.signals?.op_label ?? pct(c.signals?.op_yoy)}</p></td>
        <td className="p-3"><Flag value={c.signals?.upward_revision} yes="상향" no="동결·하향"/><p>{c.signals?.revision_label ?? pct(c.signals?.revision_pct)}</p><p className="text-xs">{c.signals?.revision_from ?? "—"} → {c.signals?.quote_date ?? "—"}</p></td>
        <td className="p-3"><p className="text-amber-200">{c.signals?.catalysts.length ? `${c.signals.catalysts.length}건의 전망` : "날짜 있는 촉매 확인 필요"}</p><p>저장 분석의 조건부 전망</p></td>
        <td className="p-3"><p>외국인 <Flag value={c.signals?.flow.foreign} yes={`${constants.strategy.flow_sessions}일 연속 매수`}/></p><p>기관 <Flag value={c.signals?.flow.institution} yes={`${constants.strategy.flow_sessions}일 연속 매수`}/></p><p className="text-xs">{c.signals?.flow.dates.join(" · ") ?? "미측정"}</p></td>
        <td className="p-3 font-bold text-yellow-200">{c.signals?.priority ?? "이전 조건의 후보"}{c.feedback_caution && <p className="mt-2 text-rose-300">⚠️ 이전 성과 부진</p>}</td>
      </tr>)}</tbody></table></div>
      <h3 className="mt-6 text-lg font-bold text-amber-200">💡 추천 종목별 섹터 · 투자 아이디어</h3>
      <div className="mt-3 grid gap-4 lg:grid-cols-2">{p.candidates.map(c => <article key={c.code} id={`idea-${p.id}-${c.code}`} className="scroll-mt-24 rounded-xl border border-slate-700 p-4">
        <h4 className="text-lg font-bold"><Link href={`/stock/${c.code}`} className="text-sky-300">{c.name} ↗</Link></h4><p className="mt-1 font-bold text-yellow-200">🏭 {c.sector}</p>
        <p className="mt-2 text-sm"><ReadableText text={stripTagLeakage(c.thesis ?? "해당 분기 투자 아이디어는 원문 확인이 필요합니다.")}/></p>
        <details className="mt-3"><summary className="cursor-pointer font-semibold text-emerald-200">🔎 상승 근거 · 확인 조건 자세히</summary>
          {c.investment_idea?.business && <p className="mt-3 text-sm">🏭 <strong className="text-sky-300">본업·제품</strong><br/>{c.investment_idea.business}</p>}
          {c.investment_idea?.drivers.length ? <p className="mt-2 text-sm">📈 <strong className="text-emerald-200">성장 동력</strong><br/>{c.investment_idea.drivers.join(" · ")}</p> : null}
          {c.investment_idea?.why_now && <div className="mt-2 text-sm"><strong className="text-amber-200">💡 왜 지금인가</strong><ReadableText text={stripTagLeakage(c.investment_idea.why_now)}/></div>}
          <p className="mt-2 text-sm">📊 <strong className="text-sky-300">실적 기대</strong><br/>매출 {eok(c.expected_revenue)} · 영익 {eok(c.expected_op)}<br/>직전 {c.source_quarter}: 매출 YoY {pct(c.revenue_yoy)} · OPM {pct(c.opm)}</p>
          <a className="mt-2 block text-sm text-sky-300 underline" href={`https://navercomp.wisereport.co.kr/v2/company/cF1002.aspx?cmp_cd=${c.code}&finGubun=MAIN&frq=1`} target="_blank" rel="noreferrer">🔗 네이버 분기 전망 원자료 · 저장 기준 {c.signals?.quote_date ?? "미확인"}</a>
          {(c.signals?.catalysts ?? []).map((t,i) => <div key={i} className="mt-3 rounded border border-sky-700 p-3 text-sm"><p className="font-bold text-amber-200">🚀 {t.date} · {t.event}</p><p>🔎 확인 지표: {t.check}</p><p className="text-yellow-200">{t.status} · 확정된 사건과 구분합니다.</p></div>)}
          <p className="mt-3 text-sm text-rose-300">🛑 {c.investment_idea?.invalidation ?? "전망 하향·실적 둔화·마진 훼손 시 재검토"}</p>
          <p className="mt-2 text-sm">📚 분석일 {c.analysis_date?.slice(0,10) ?? "미확인"}</p>{c.news.map(n => <p key={n.url} className="mt-2 text-sm">📄 <a className="text-sky-300 underline" href={n.url} target="_blank" rel="noreferrer">{n.title}</a><br/>{n.date}</p>)}
        </details>
      </article>)}</div>
      <details className="mt-5 rounded border border-slate-700 p-3"><summary className="cursor-pointer font-bold text-sky-300">🌏 수립 당시 매크로 · 실전 대응</summary><p className="mt-2">🕒 {p.macro.checkedAt}</p><ReadableText text={p.macro.summary?.current ?? "매크로 요약 확인 필요"}/><ReadableText text={p.macro.summary?.forward ?? ""}/><div className="mt-3 grid gap-2 sm:grid-cols-2">{p.actions.map(a => <div className="rounded bg-slate-900 p-3 text-sm" key={a}><ReadableText text={a}/></div>)}</div>{(p.macro.recentIssues ?? []).slice(0,4).map(n => <div key={n.url} className="mt-3"><a className="font-semibold text-sky-300 underline" href={n.url} target="_blank" rel="noreferrer">📰 {n.title}</a><p>{n.publishedAt}</p><ReadableText text={n.fact}/><ReadableText text={n.marketImpact}/></div>)}</details>
      <h3 className="mt-6 text-lg font-bold text-emerald-200">🔁 실제 결과 검증 · 다음 전략 피드백</h3>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">{Object.entries(p.review.summary).map(([h,s]) => <div key={h} className="rounded-lg border border-slate-700 p-3"><h4 className="font-bold text-sky-300">📅 수립 후 {h}거래일</h4><p className="text-xl font-bold text-amber-200">{pct(s.median,"%p")}</p><p className="text-sm">지수 대비 중앙값<br/>측정 {s.n}/{s.total}종목 · {s.status}</p></div>)}</div>
      <details className="mt-3"><summary className="cursor-pointer text-sky-300">📊 종목별 주가 추이 · 실제 실적 대조</summary><div className="mt-2 overflow-x-auto"><table className="w-full min-w-[850px] text-sm"><thead><tr>{["종목", "수립 전 60거래일", "수립 후 수익 · 초과", "실제 매출 · 영익", "사전 기대차"].map(h => <th key={h} className="p-3 text-left">{h}</th>)}</tr></thead><tbody>{p.candidates.map(c => {const r=p.review.stocks.find(s=>s.code===c.code);return <tr key={c.code}><td className="p-3 text-sky-300">{c.name}</td><td className="p-3">{pct(r?.trend.return)}<p>{r?.trend.through ?? "—"}</p></td><td className="p-3">{pct(r?.current.return)} · {pct(r?.current.excess,"%p")}<p>기준 종가일 {r?.base_date ?? "대기"}</p></td><td className="p-3">{eok(r?.earnings.revenue)} · {eok(r?.earnings.op)}</td><td className="p-3">매출 {pct(r?.earnings.revenue_gap_pct)}<p>영익 {eok(r?.earnings.op_gap)}</p></td></tr>})}</tbody></table></div></details>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">{p.review.lessons.map(l => <p key={l.sector} className="rounded border border-slate-700 p-3 text-sm"><strong className="text-yellow-200">🏭 {l.sector}</strong><br/>{l.message}<br/>D+60 {l.n}/{l.total}종목 · 실제 실적 {l.earnings_measured}/{l.total}종목</p>)}</div>
      {p.feedback.map(f=><p key={f.sector} className="mt-2 text-sm">🔁 <strong className="text-emerald-200">{f.sector}: {f.action}</strong><br/>D+60 {pct(f.median,"%p")} · {f.n}종목 / {f.seasons}실적 시즌 · {f.applied ? "이번 추천에 반영" : "표본 축적 중"}</p>)}
      <p className="mt-3 text-sm">🛡️ 원 후보를 사후 교체하지 않습니다.<br/>📊 실제 매매가 아닌 고정 후보의 종가 관찰 성과입니다.<br/>🔎 아직 발생하지 않은 성과는 미측정으로 유지합니다.</p>
    </details>)}
  </section>;
}
