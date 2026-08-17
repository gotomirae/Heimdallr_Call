// PRD Ref: §9 /season, §10.2 — 시즌 진행률 · 발표 캘린더 · 미발표 종목
import Link from "next/link";
import { selectAll } from "@/lib/supabase";
import { getUniverse } from "@/lib/queries";
import { disclosedQuarter, quarterIndex } from "@/lib/disclosureQuarter";
import { sectorOf } from "@/lib/sector";
import { marketCap } from "@/lib/format";

export const dynamic = "force-dynamic";

interface FundRow {
  code: string;
  fiscal_year: number;
  fiscal_quarter: number;
  revenue: number | null;
  is_estimate: boolean | null;
}

interface DisclosureRow {
  report_nm?: string | null;
  code: string | null;
  disclosed_at: string | null;
  doc_type: string | null;
}

/** 실적 시즌 마감 (PRD §10.2). 정기보고서 법정 기한이다. */
const DEADLINE: Record<number, string> = {
  1: "5월 15일",
  2: "8월 14일",
  3: "11월 14일",
  4: "3월 31일 (사업보고서)",
};

function Card({ title, note, children }: {
  title: string; note?: string; children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <h2 className="mb-1 text-sm font-semibold text-slate-100">{title}</h2>
      {note && <p className="mb-3 text-xs text-slate-300">{note}</p>}
      {children}
    </section>
  );
}

export default async function SeasonPage() {
  const [funds, disclosures, universe] = await Promise.all([
    selectAll<FundRow>(
      "quarterly_fundamentals",
      "code,fiscal_year,fiscal_quarter,revenue,is_estimate"
    ),
    selectAll<DisclosureRow>(
      "earnings_disclosures",
      // ★ report_nm이 있어야 분기를 정확히 뽑는다 — 없으면 공시일 추정으로 떨어져
      //   분기 경계에서 틀린다(7월 초 1Q 정정 공시를 2Q로 읽는다).
      "code,disclosed_at,doc_type,report_nm"
    ),
    getUniverse(),
  ]);

  const qIndex = (r: FundRow) => r.fiscal_year * 4 + (r.fiscal_quarter - 1);

  // ★★ **끝나지 않은 분기는 시즌이 될 수 없다.**
  //   비12월 결산 기업 탓에 미래 분기 행이 섞여 들어온다(T36) —
  //   그냥 `max()`를 쓰면 그 한 행 때문에 "2026.3Q 시즌 · 진행률 0.1%"가 나온다.
  //   에러는 없고 화면만 조용히 무의미해진다.
  //   `src/screener/run.py::last_reportable_index()`와 **같은 규칙**이어야 한다.
  const today = new Date();
  const ceiling =
    today.getFullYear() * 4 + Math.floor(today.getMonth() / 3) - 1;

  const usable = funds.filter((f) => qIndex(f) <= ceiling);
  const latest = usable.length ? Math.max(...usable.map(qIndex)) : null;

  if (latest == null) {
    return (
      <div className="space-y-3">
        <h1 className="text-2xl font-bold">시즌 현황</h1>
        <p className="text-sm text-slate-200">분기 재무가 없다.</p>
      </div>
    );
  }

  const year = Math.floor(latest / 4);
  const quarter = (latest % 4) + 1;

  // 대상: 업종 제외가 아닌 종목 전부
  const targets = [...universe.values()].filter((u) => !u.is_excluded);

  // ① 재무가 들어온 종목 = 판정 가능
  const collected = new Set(
    usable
      .filter((f) => qIndex(f) === latest && f.revenue != null)
      .map((f) => f.code)
  );
  const preliminary = new Set(
    usable
      .filter((f) => qIndex(f) === latest && f.revenue != null && f.is_estimate)
      .map((f) => f.code)
  );

  // ② ★★ **공시가 났는가**를 따로 본다 (T74).
  //   예전에는 재무 수집만 보고 발표 여부를 판정해서, **공시를 이미 낸 610종목이
  //   '미발표'로 표시**됐다(대한항공·리노공업·삼양식품 등 — 최근 공시 목록에는
  //   그 링크가 멀쩡히 걸려 있었다). 공시가 난 것과 재무가 수집된 것은 다른 상태다.
  //   `earnings_disclosures.fiscal_quarter`는 전 행이 null이라(실측 1,558/1,558)
  //   보고서명·공시일에서 분기를 뽑는다.
  const announcedAt = new Map<string, string>();
  for (const d of disclosures) {
    if (!d.code) continue;
    const q = disclosedQuarter(d);
    if (!q || quarterIndex(q) !== latest) continue;
    const day = (d.disclosed_at ?? "").slice(0, 10);
    const prev = announcedAt.get(d.code);
    // 같은 분기에 여러 건이면 **가장 이른 것**이 발표일이다.
    if (!prev || (day && day < prev)) announcedAt.set(d.code, day);
  }

  const done = targets.filter((u) => collected.has(u.code));
  // 공시는 났는데 재무가 없다 = **발표됐다.** 수집이 늦은 것이지 미발표가 아니다.
  const awaitingCollection = targets
    .filter((u) => !collected.has(u.code) && announcedAt.has(u.code))
    .sort((a, b) => (b.market_cap_krw ?? 0) - (a.market_cap_krw ?? 0));
  // 진짜 미발표 = 재무도 없고 공시도 없다.
  const pending = targets
    .filter((u) => !collected.has(u.code) && !announcedAt.has(u.code))
    .sort((a, b) => (b.market_cap_krw ?? 0) - (a.market_cap_krw ?? 0));

  const announcedCount = done.length + awaitingCollection.length;
  // ★ 진행률은 **공시 기준**이다. 재무 수집은 우리 쪽 사정이고,
  //   "시즌이 얼마나 진행됐나"는 시장이 얼마나 발표했나로 재야 한다.
  const pct = targets.length ? (announcedCount / targets.length) * 100 : 0;
  const collectedPct = targets.length ? (done.length / targets.length) * 100 : 0;

  // 발표 캘린더 — 일자별 건수
  const byDay = new Map<string, number>();
  for (const d of disclosures) {
    if (!d.disclosed_at) continue;
    const day = d.disclosed_at.slice(0, 10);
    byDay.set(day, (byDay.get(day) ?? 0) + 1);
  }
  const days = [...byDay.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  const peak = Math.max(1, ...days.map(([, n]) => n));

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold">
          {year}.{quarter}Q 시즌 현황
        </h1>
        <p className="mt-1 text-sm text-slate-200">
          정기보고서 마감 {DEADLINE[quarter]} · 대상 {targets.length.toLocaleString("ko-KR")}종목
          (업종 제외 뺀 수)
        </p>
      </div>

      <Card
        title="발표 진행률"
        note="공시가 난 종목 기준. 재무 수집은 우리 쪽 사정이라 따로 표시한다."
      >
        <div className="space-y-3">
          <div className="flex items-baseline gap-3">
            <span className="text-3xl font-bold tabular-nums text-white">{pct.toFixed(1)}%</span>
            <span className="text-sm text-slate-100">
              {announcedCount.toLocaleString("ko-KR")} / {targets.length.toLocaleString("ko-KR")}종목 공시
            </span>
          </div>
          {/* 두 겹 막대 — 진한 쪽이 재무까지 들어온 종목, 연한 쪽이 공시만 난 종목 */}
          <div className="relative h-3 overflow-hidden rounded bg-slate-800">
            <div className="absolute inset-y-0 left-0 bg-sky-800"
                 style={{ width: `${Math.min(pct, 100)}%` }} />
            <div className="absolute inset-y-0 left-0 bg-emerald-600"
                 style={{ width: `${Math.min(collectedPct, 100)}%` }} />
          </div>
          <table className="text-xs">
            <tbody>
              <tr>
                <td className="pr-3 font-semibold text-emerald-300">재무 수집 완료</td>
                <td className="pr-2 tabular-nums text-white">{done.length.toLocaleString("ko-KR")}</td>
                <td className="text-slate-200">
                  확정 {(done.length - preliminary.size).toLocaleString("ko-KR")} ·
                  잠정 {preliminary.size.toLocaleString("ko-KR")} — 판정 가능
                </td>
              </tr>
              <tr>
                <td className="pr-3 font-semibold text-sky-300">공시만 (수집 대기)</td>
                <td className="pr-2 tabular-nums text-white">
                  {awaitingCollection.length.toLocaleString("ko-KR")}
                </td>
                <td className="text-slate-200">발표는 됐다 — 재무 수집이 늦은 것이다</td>
              </tr>
              <tr>
                <td className="pr-3 font-semibold text-slate-200">미발표</td>
                <td className="pr-2 tabular-nums text-white">{pending.length.toLocaleString("ko-KR")}</td>
                <td className="text-slate-200">공시도 재무도 없다</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card
        title="발표 캘린더"
        note={`공시 감지 ${disclosures.length.toLocaleString("ko-KR")}건 · 막대 높이는 그날 감지한 실적 공시 수`}
      >
        {days.length === 0 ? (
          <p className="text-sm text-slate-300">감지된 공시가 없다.</p>
        ) : (
          <div className="overflow-x-auto">
            <div className="flex min-w-max items-end gap-1" style={{ height: "7rem" }}>
              {days.map(([day, n]) => (
                <div key={day} className="flex w-7 flex-col items-center gap-1">
                  <span className="text-[10px] tabular-nums text-slate-300">{n}</span>
                  <div
                    className="w-full rounded-t bg-sky-700"
                    style={{ height: `${(n / peak) * 68}px` }}
                    title={`${day} · ${n}건`}
                  />
                  <span className="text-[10px] text-slate-300">{day.slice(5)}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </Card>

      {/* ★ 공시만 난 종목 — **미발표가 아니다.** 수집이 늦은 것이라 따로 보여준다.
          이걸 미발표와 섞으면 "발표를 안 했다"로 오독하고, 실제 원인(수집 지연)을
          놓친다(T74). */}
      {awaitingCollection.length > 0 && (
        <Card
          title={`공시는 났고 재무 수집 대기 (${awaitingCollection.length.toLocaleString("ko-KR")}종목)`}
          note="발표는 이미 됐다. 재무가 들어오면 자동으로 판정 대상이 된다 — 며칠 지나도 남아 있으면 수집기를 확인하라."
        >
          <div className="max-h-[40vh] overflow-auto rounded border border-slate-700">
            <table className="w-full min-w-[520px] text-sm">
              <thead className="sticky top-0 z-10 bg-slate-800 text-xs uppercase text-slate-100">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left font-medium">종목</th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">섹터</th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">공시일</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">시총</th>
                </tr>
              </thead>
              <tbody>
                {awaitingCollection.slice(0, 40).map((u) => (
                  <tr key={u.code} className="border-t border-slate-800">
                    <td className="whitespace-nowrap px-3 py-1.5">
                      <Link href={`/stock/${u.code}`} className="text-sky-300 hover:underline">
                        {u.name}
                      </Link>
                    </td>
                    <td className="whitespace-nowrap px-3 py-1.5 text-slate-200">{sectorOf(u)}</td>
                    <td className="whitespace-nowrap px-3 py-1.5 tabular-nums text-sky-200">
                      {announcedAt.get(u.code) ?? "—"}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-slate-200">
                      {marketCap(u.market_cap_krw)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {awaitingCollection.length > 40 && (
            <p className="mt-2 text-xs text-slate-200">
              … 외 {(awaitingCollection.length - 40).toLocaleString("ko-KR")}종목
            </p>
          )}
        </Card>
      )}

      <Card
        title={`미발표 종목 (${pending.length.toLocaleString("ko-KR")}종목 · 시총 순)`}
        note="공시도 재무도 없는 종목. 마감일이 지났는데 남아 있으면 공시 수집을 의심하라."
      >
        {pending.length === 0 ? (
          <p className="text-sm text-emerald-300">전 종목 공시 완료.</p>
        ) : (
          <div className="max-h-[40vh] overflow-auto rounded border border-slate-700">
            <table className="w-full min-w-[460px] text-sm">
              <thead className="sticky top-0 z-10 bg-slate-800 text-xs uppercase text-slate-100">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left font-medium">종목</th>
                  <th scope="col" className="px-3 py-2 text-left font-medium">섹터</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">시총</th>
                </tr>
              </thead>
              <tbody>
                {pending.slice(0, 40).map((u) => (
                  <tr key={u.code} className="border-t border-slate-800">
                    <td className="whitespace-nowrap px-3 py-1.5">
                      <Link href={`/stock/${u.code}`} className="text-sky-300 hover:underline">
                        {u.name}
                      </Link>
                    </td>
                    {/* ★ KRX 업종명이 아니라 투자 섹터를 쓴다 — 발굴 목록과 같은 기준(사용자 지정). */}
                    <td className="whitespace-nowrap px-3 py-1.5 text-slate-200">{sectorOf(u)}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-slate-200">
                      {marketCap(u.market_cap_krw)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {pending.length > 40 && (
          <p className="mt-2 text-xs text-slate-200">
            … 외 {(pending.length - 40).toLocaleString("ko-KR")}종목
          </p>
        )}
      </Card>
    </div>
  );
}
