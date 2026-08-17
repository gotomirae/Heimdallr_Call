// PRD Ref: §9 — 발굴 목록 (등급·스코어·반영도)
import Link from "next/link";
import { GradeBadge } from "@/components/Badges";
import { DASH, marketCap, num, pct, quarterLabel } from "@/lib/format";
import { getLatestScreens, getUniverse } from "@/lib/queries";
import type { Grade } from "@/lib/types";

export const dynamic = "force-dynamic";

const GRADE_ORDER: Grade[] = ["★", "○", "△", "·", "✕"];

export default async function HomePage() {
  const [{ rows, dropped }, universe] = await Promise.all([
    getLatestScreens(),
    getUniverse(),
  ]);

  const graded = rows.filter((r) => r.grade != null);
  const counts = new Map<Grade, number>();
  for (const r of graded) {
    counts.set(r.grade as Grade, (counts.get(r.grade as Grade) ?? 0) + 1);
  }

  // ★ 게이트를 통과한 종목 전부를 스코어 순으로 보여준다.
  //   ★/○만 보여주면 80종목뿐이라 "그 아래는 뭐가 있나"를 볼 수 없다.
  //   탈락 종목은 애초에 조회에서 빠진다(`getLatestScreens`).
  const listed = [...rows].sort(
    (a, b) => (b.score_flash ?? 0) - (a.score_flash ?? 0)
  );
  const notifyCount = graded.filter(
    (r) => r.grade === "★" || r.grade === "○"
  ).length;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold">실적 가속 종목</h1>
        <p className="mt-1 text-sm text-slate-400">
          {rows.length.toLocaleString("ko-KR")}종목 · 발송 대상(★/○) {notifyCount}
        </p>
        <p className="mt-1 text-xs text-slate-500">
          매출 성장률이 <strong>전분기보다 높아진</strong> 종목만 담는다 —
          게이트에서 탈락한 종목은 이 목록에 없다.
          종목별 <strong>최신 발표 분기</strong> 기준이다.
        </p>
      </div>

      {dropped.length > 0 && (
        <p className="rounded border border-amber-800/60 bg-amber-900/20 px-3 py-2 text-xs text-amber-300">
          ⚠ 아직 DB에 없는 컬럼을 제외하고 조회했다: {dropped.join(", ")}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        {GRADE_ORDER.map((g) => (
          <div
            key={g}
            className="rounded border border-slate-800 bg-slate-900/40 px-3 py-2 text-sm"
          >
            <span className="mr-2 font-semibold">{g}</span>
            <span className="text-slate-400">{counts.get(g) ?? 0}</span>
          </div>
        ))}
        {rows.length - graded.length > 0 && (
          <div
            className="rounded border border-slate-800 bg-slate-900/40 px-3 py-2 text-sm text-slate-400"
            title="게이트는 통과했으나 시세가 없어 주가반영도를 판정하지 못한 종목"
          >
            반영도 미측정 {rows.length - graded.length}
          </div>
        )}
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-800">
        <table className="w-full min-w-[860px] text-sm">
          <thead className="bg-slate-900/60 text-xs uppercase text-slate-500">
            <tr>
              <th className="px-3 py-2 text-left">등급</th>
              <th className="px-3 py-2 text-left">종목</th>
              <th className="px-3 py-2 text-left">분기</th>
              <th className="px-3 py-2 text-right">스코어</th>
              <th className="px-3 py-2 text-right">반영도</th>
              <th className="px-3 py-2 text-right">시총</th>
              <th className="px-3 py-2 text-left">경고</th>
            </tr>
          </thead>
          <tbody>
            {listed.map((r) => {
              const stock = universe.get(r.code);
              return (
                <tr key={r.code} className="border-t border-slate-800/60 hover:bg-slate-900/40">
                  <td className="px-3 py-2">
                    <GradeBadge grade={r.grade} />
                  </td>
                  <td className="px-3 py-2">
                    <Link href={`/stock/${r.code}`} className="text-sky-400 hover:underline">
                      {stock?.name ?? r.code}
                    </Link>
                    <span className="ml-2 text-xs text-slate-500">{r.code}</span>
                  </td>
                  <td className="px-3 py-2 text-slate-400">
                    {quarterLabel(r.fiscal_year, r.fiscal_quarter)}
                  </td>
                  <td className="px-3 py-2 text-right">{num(r.score_flash, 1)}</td>
                  <td className="px-3 py-2 text-right">{num(r.pri, 1)}</td>
                  <td className="px-3 py-2 text-right text-slate-400">
                    {marketCap(stock?.market_cap_krw)}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-500">
                    {[
                      r.base_effect_warning ? "기저효과" : null,
                      !r.has_consensus ? "컨센없음" : null,
                      stock?.sector_caveat ? "업종주의" : null,
                    ]
                      .filter(Boolean)
                      .join(" · ") || DASH}
                  </td>
                </tr>
              );
            })}
            {listed.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-8 text-center text-slate-500">
                  실적이 가속 중인 종목이 없다.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
