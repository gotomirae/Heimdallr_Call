// PRD Ref: §9 /season, §10.2 — 시즌 진행률 · 발표 캘린더 · 미발표 종목
import Link from "next/link";
import { selectAll } from "@/lib/supabase";
import { getUniverse } from "@/lib/queries";
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
    selectAll<DisclosureRow>("earnings_disclosures", "code,disclosed_at,doc_type"),
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
  const reported = new Set(
    usable
      .filter((f) => qIndex(f) === latest && f.revenue != null)
      .map((f) => f.code)
  );
  const preliminary = new Set(
    usable
      .filter((f) => qIndex(f) === latest && f.revenue != null && f.is_estimate)
      .map((f) => f.code)
  );

  const done = targets.filter((u) => reported.has(u.code));
  const pending = targets
    .filter((u) => !reported.has(u.code))
    .sort((a, b) => (b.market_cap_krw ?? 0) - (a.market_cap_krw ?? 0));

  const pct = targets.length ? (done.length / targets.length) * 100 : 0;

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
        note="잠정실적이든 확정이든 '매출이 들어온 종목'을 발표로 센다 — 잠정만 나온 종목도 판정은 가능하다."
      >
        <div className="space-y-3">
          <div className="flex items-baseline gap-3">
            <span className="text-3xl font-bold tabular-nums">{pct.toFixed(1)}%</span>
            <span className="text-sm text-slate-200">
              {done.length.toLocaleString("ko-KR")} / {targets.length.toLocaleString("ko-KR")}종목
            </span>
          </div>
          <div className="h-3 overflow-hidden rounded bg-slate-800">
            <div
              className="h-full bg-emerald-600"
              style={{ width: `${Math.min(pct, 100)}%` }}
            />
          </div>
          <div className="flex flex-wrap gap-3 text-xs text-slate-200">
            <span>확정 {(done.length - preliminary.size).toLocaleString("ko-KR")}</span>
            <span>잠정만 {preliminary.size.toLocaleString("ko-KR")}</span>
            <span className="text-slate-300">
              미발표 {pending.length.toLocaleString("ko-KR")}
            </span>
          </div>
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

      <Card
        title="미발표 종목 (시총 순)"
        note="아직 이번 분기 매출이 들어오지 않은 종목. 발표가 늦은 것일 수도, 수집이 안 된 것일 수도 있다 — 마감일이 지났는데 남아 있으면 수집을 의심하라."
      >
        {pending.length === 0 ? (
          <p className="text-sm text-emerald-400">전 종목 발표 완료.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[420px] text-sm">
              <thead className="text-xs uppercase text-slate-300">
                <tr className="border-b border-slate-800">
                  <th className="py-2 text-left">종목</th>
                  <th className="py-2 text-left">업종</th>
                  <th className="py-2 text-right">시총</th>
                </tr>
              </thead>
              <tbody>
                {pending.slice(0, 30).map((u) => (
                  <tr key={u.code} className="border-b border-slate-800/60">
                    <td className="py-1.5">
                      <Link href={`/stock/${u.code}`} className="text-sky-300 hover:underline">
                        {u.name}
                      </Link>
                      <span className="ml-2 text-xs text-slate-300">{u.code}</span>
                    </td>
                    <td className="max-w-[14rem] truncate py-1.5 text-xs text-slate-300">
                      {u.industry ?? "—"}
                    </td>
                    <td className="py-1.5 text-right tabular-nums text-slate-200">
                      {marketCap(u.market_cap_krw)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {pending.length > 30 && (
              <p className="mt-2 text-xs text-slate-300">
                … 외 {(pending.length - 30).toLocaleString("ko-KR")}종목
              </p>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
