// PRD Ref: §9.3 · ADR 28
import Link from "next/link";
import ledger from "@/lib/season-strategies.json";

type Point = { date?: string; return?: number | null; excess?: number | null };
type Candidate = { code: string; name: string; sector: string; grade: string; pri: number | null;
  source_quarter: string; revenue_yoy: number | null; opm: number | null;
  thesis: string | null; analysis_date: string | null; feedback_caution: boolean;
  expected_revenue: number | null; expected_op: number | null;
  news: { title: string; date: string; url: string }[] };
type ReviewStock = { code: string; sector: string; base_date: string | null; horizons: Record<string, Point>;
  current: Point; trend: { return: number | null; from: string | null; through: string | null };
  earnings: { revenue: number | null; op: number | null; opm: number | null; revenue_gap_pct: number | null; op_gap: number | null } };
type Plan = { id: string; created_at: string; target_year: number; target_quarter: number; late_start: boolean;
  rule_version: string; eligible: number; candidates: Candidate[]; actions: string[]; limitations: string[];
  feedback: { sector: string; n: number; seasons: number; median: number | null; action: string; applied: boolean }[];
  history: { n: number; median: number | null };
  recent_sectors?: {sector: string; n: number; median: number | null}[];
  macro: { checkedAt: string; stale?: boolean; summary?: {current: string; forward: string};
    recentIssues?: { title: string; url: string; publishedAt: string; fact: string; marketImpact: string }[];
    nextEvents?: {date: string; event: string; url: string; response: string}[] };
  review: { checked_at: string; stocks: ReviewStock[]; lessons: {sector: string; n: number; total: number; message: string; earnings_measured: number}[]; summary: Record<string, {n: number; total: number;
    median: number | null; win_rate: number | null; status: string}> } };

const pct = (v: number | null | undefined, unit = "%") => v == null ? "미측정" : `${v > 0 ? "+" : ""}${v.toFixed(2)}${unit}`;
const eok = (v: number | null) => v == null ? "미확인" : `${(v / 1e8).toLocaleString("ko-KR", {maximumFractionDigits: 1})}억`;

export default function SeasonStrategy() {
  const plans = [...ledger.plans] as unknown as Plan[];
  plans.reverse();
  return <section className="rounded-lg border-2 border-amber-600/60 bg-amber-950/10 p-4">
    <h2 className="text-lg font-bold text-amber-100">다가오는 실적 시즌 투자 전략 · 사후 검증</h2>
    <p className="mt-1 text-sm text-slate-200">매년 1·4·7·10월에 전략을 수립하고 원본을 보존합니다. 실제 실적과 전략 수립 후 20·40·60거래일 성과를 매일 검증해 다음 시즌에 반영합니다.</p>
    <p className="mt-1 text-xs text-slate-300">최근 검증 {ledger.checked_at ?? "아직 실행 전"} · 예약 실행과 배포 지연 시 갱신이 늦어질 수 있습니다.</p>
    {ledger.errors.length > 0 && <p className="mt-2 text-xs text-amber-200">자료 수집 한계: {ledger.errors.join(" · ")}</p>}
    {plans.length === 0 && <p className="mt-3 text-sm text-slate-200">첫 전략 생성 대기 중입니다. 과거 시즌 전략은 소급해서 만들지 않습니다.</p>}
    {plans.map((p, i) => <details key={p.id} open={i === 0} className="mt-4 rounded border border-slate-700 bg-slate-950/40 p-3">
      <summary className="cursor-pointer font-semibold text-white">{p.id} 전략 — {p.target_year}년 {p.target_quarter}분기 실적 발표 대비 · 후보 {p.candidates.length}종목</summary>
      <p className="mt-2 text-xs text-slate-300">수립일 {p.created_at} · {p.rule_version} · 대상 조건 통과 {p.eligible}종목{p.late_start && " · 월초 이후 생성: 수립일 이전 성과는 전략 수익에 포함하지 않습니다."}</p>
      <div className="mt-3 text-sm text-slate-100 space-y-1">{p.actions.map(a => <p key={a}>{a}</p>)}</div>
      <div className="mt-3 rounded border border-slate-700 p-3 text-sm text-slate-200">
        <h3 className="font-semibold text-white">수립 당시 매크로·최근 이슈</h3>
        <p className="text-xs text-slate-300">자료 기준 {p.macro.checkedAt}{p.macro.stale && " · 갱신 지연: 최근 상황 재확인 필요"}</p>
        <p className="mt-1">{p.macro.summary?.current ?? "매크로 요약 미확인"}</p>
        <p>{p.macro.summary?.forward}</p>
        {(p.macro.recentIssues ?? []).slice(0, 4).map(n => <p key={n.url} className="mt-2"><a href={n.url} target="_blank" rel="noreferrer" className="text-sky-300 underline">{n.title}</a> ({n.publishedAt}) · {n.fact} {n.marketImpact}</p>)}
        {(p.macro.nextEvents ?? []).slice(0, 3).map(n => <p key={`${n.date}-${n.event}`} className="mt-1">{n.date} <a href={n.url} target="_blank" rel="noreferrer" className="text-sky-300 underline">{n.event}</a> · {n.response}</p>)}
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-3">{Object.entries(p.review.summary).map(([h, s]) => <div key={h} className="rounded border border-slate-700 p-3">
        <p className="text-sm text-white">전략 수립 후 {h}거래일</p><p className="mt-1 font-bold text-amber-100">{pct(s.median, "%p")}</p>
        <p className="text-xs text-slate-300">지수 대비 중앙값 · {s.n}/{s.total}종목 · 승률 {s.win_rate == null ? "미측정" : `${(s.win_rate * 100).toFixed(0)}%`} · {s.status}</p>
      </div>)}</div>
      <p className="mt-2 text-xs text-slate-300">직전 실적 시즌 전체 회고 D+60: {p.history.n}건 · 중앙값 {pct(p.history.median, "%p")}. 아래 고정 후보군 성과와 별도로 봅니다.</p>
      {(p.recent_sectors ?? []).length > 0 && <p className="mt-2 text-xs text-slate-200">직전 분기 실적 발표 후 D+20 섹터별 초과수익: {p.recent_sectors?.map(s => `${s.sector} ${pct(s.median, "%p")} (${s.n}건)`).join(" · ")}. 수립 당시 관측값이며 후보 선정 후 수익률과 구분합니다.</p>}
      <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[900px] text-sm text-slate-200">
        <thead><tr className="border-b border-slate-700 text-left"><th className="p-2">종목·섹터</th><th className="p-2">직전 실적·기대</th><th className="p-2">주가 추이·실제 결과</th><th className="p-2">분석·최근 공시</th></tr></thead>
        <tbody>{p.candidates.map(c => {const r = p.review.stocks.find(s => s.code === c.code); return <tr key={c.code} className="border-b border-slate-800 align-top">
          <td className="p-2"><Link href={`/stock/${c.code}`} className="font-semibold text-sky-300">{c.name} {c.grade}</Link><p className="text-xs">{c.sector} · PRI {c.pri ?? "미측정"}</p>{c.feedback_caution && <p className="text-xs text-amber-200">지난 전략 부진: 근거 재확인</p>}</td>
          <td className="p-2 text-xs">{c.source_quarter} 매출 YoY {pct(c.revenue_yoy)} · OPM {pct(c.opm)}<p>다가오는 매출 {eok(c.expected_revenue)} · 영익 {eok(c.expected_op)}</p><p>실제 매출 {eok(r?.earnings.revenue ?? null)} · 영익 {eok(r?.earnings.op ?? null)}</p><p>매출 기대차 {pct(r?.earnings.revenue_gap_pct)} · 영익 기대차 {eok(r?.earnings.op_gap ?? null)}</p></td>
          <td className="p-2 text-xs">수립 전 60거래일 {pct(r?.trend.return)}<p className="text-slate-400">{r?.trend.from ?? "—"} ~ {r?.trend.through ?? "—"}</p><p>기준 종가일 {r?.base_date ?? "대기"}</p><p>기준일→{r?.current.date ?? "대기"} {pct(r?.current.return)} · 초과 {pct(r?.current.excess, "%p")}</p><p>D+60 초과 {pct(r?.horizons["60"]?.excess, "%p")}</p></td>
          <td className="max-w-sm p-2 text-xs"><p>{c.thesis ?? "저장된 해당 분기 분석 없음"}</p>{c.analysis_date && <p className="text-slate-400">분석일 {c.analysis_date.slice(0, 10)}</p>}{c.news.map(n => <p className="mt-1" key={n.url}><a href={n.url} target="_blank" rel="noreferrer" className="text-sky-300 underline">{n.title}</a> · {n.date}</p>)}</td>
        </tr>})}</tbody></table></div>
      <h3 className="mt-4 font-semibold text-white">섹터별 후보 주가 추이</h3>
      <div className="mt-2 flex flex-wrap gap-2">{[...new Set(p.candidates.map(c => c.sector))].map(sector => {
        const rows = p.review.stocks.filter(r => r.sector === sector);
        const before = rows.flatMap(r => r.trend.return == null ? [] : [r.trend.return]);
        const after = rows.flatMap(r => r.current.excess == null ? [] : [r.current.excess]);
        const med = (vs: number[]) => { const sorted = [...vs].sort((a,b) => a-b); const mid = Math.floor(sorted.length/2); return sorted.length ? (sorted[mid] + sorted[Math.floor((sorted.length-1)/2)])/2 : null; };
        return <p key={sector} className="rounded border border-slate-700 px-3 py-2 text-xs text-slate-200">{sector} · 수립 전 {pct(med(before))} ({before.length}/{rows.length}) · 수립 후 초과 {pct(med(after), "%p")} ({after.length}/{rows.length})</p>;
      })}</div>
      <p className="mt-1 text-xs text-slate-400">전략 후보군의 중앙값입니다. 섹터 전체 지수 수익률로 해석하지 않습니다.</p>
      <h3 className="mt-4 font-semibold text-white">이번 전략의 실제 결과와 피드백</h3>
      {p.review.lessons.map(l => <p key={l.sector} className="mt-1 text-sm text-slate-200">{l.sector}: {l.message} · D+60 {l.n}/{l.total}종목 · 실제 실적 확인 {l.earnings_measured}/{l.total}종목</p>)}
      <h3 className="mt-4 font-semibold text-white">이전 검증에서 이번 전략에 반영한 피드백</h3>
      {p.feedback.length ? p.feedback.map(f => <p key={f.sector} className="mt-1 text-sm text-slate-200">{f.sector}: {f.action} · D+60 {pct(f.median, "%p")} · {f.n}종목/{f.seasons}시즌 · {f.applied ? "우선순위 반영" : "표본 축적 중"}</p>) : <p className="mt-1 text-sm text-slate-200">첫 전략입니다. 실제 사후 검증이 쌓이기 전에는 검증된 개선으로 표시하지 않습니다.</p>}
      <p className="mt-2 text-xs text-slate-300">현재 전략의 D+60 결과는 다음 전략 수립 때 반영합니다. 원본 후보와 판단은 검증 후에도 유지합니다.</p>
      <div className="mt-3 text-xs text-slate-400">{p.limitations.map(l => <p key={l}>{l}</p>)}</div>
    </details>)}
  </section>;
}
