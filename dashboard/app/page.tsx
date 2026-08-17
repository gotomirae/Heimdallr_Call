// PRD Ref: §9 — 발굴 목록
// 열: 섹터 · 종목명 · 등급 · 분기 · 스코어 · 반영도 · 시총 · 최근 5일
//     + 발표일 기준 추적(발표 전 5일 · 당일 · 후 5/20/60일)
import Link from "next/link";
import { GradeBadge } from "@/components/Badges";
import { Term, TermTh } from "@/components/Term";
import { DASH, marketCap, num, pct, quarterLabel } from "@/lib/format";
import { HORIZONS, excessField, horizonLabel, type OutcomeRow, getOutcomes } from "@/lib/outcome";
import { getAllLatestPrices, getLatestScreens, getUniverse } from "@/lib/queries";
import type { Grade } from "@/lib/types";

export const dynamic = "force-dynamic";

const GRADE_ORDER: Grade[] = ["★", "○", "△", "·", "✕"];

/** 정렬용 순위. 등급이 없는 행(반영도 미측정)은 **맨 뒤**로 보낸다. */
const GRADE_RANK = new Map<Grade, number>(GRADE_ORDER.map((g, i) => [g, i]));
function gradeRank(grade: Grade | null): number {
  return grade == null ? GRADE_ORDER.length : (GRADE_RANK.get(grade) ?? GRADE_ORDER.length);
}

/** 수익률은 부호에 따라 색을 바꾼다 — 표에서 눈이 먼저 가야 하는 열이다. */
function returnClass(value: number | null | undefined): string {
  if (value == null) return "text-slate-300";
  if (value > 0) return "text-rose-300 font-semibold";
  if (value < 0) return "text-sky-300";
  return "text-slate-100";
}

export default async function HomePage() {
  const [{ rows, dropped }, universe, priceResult, outcomeResult] = await Promise.all([
    getLatestScreens(),
    getUniverse(),
    getAllLatestPrices(),
    getOutcomes(),
  ]);
  const prices = priceResult.prices;

  // 발표일 기준 추적은 종목별 **최신 분기 1건**만 쓴다 — 분기 이력이 섞이면
  // 같은 종목이 여러 빈티지로 보인다(T40과 같은 함정).
  const outcomes = new Map<string, OutcomeRow>();
  for (const o of outcomeResult.rows) {
    const prev = outcomes.get(o.code);
    const idx = o.fiscal_year * 4 + o.fiscal_quarter;
    if (!prev || idx > prev.fiscal_year * 4 + prev.fiscal_quarter) outcomes.set(o.code, o);
  }

  const graded = rows.filter((r) => r.grade != null);
  const counts = new Map<Grade, number>();
  for (const r of graded) {
    counts.set(r.grade as Grade, (counts.get(r.grade as Grade) ?? 0) + 1);
  }

  // ★ 등급 높은 순, 같은 등급 안에서는 스코어 높은 순.
  const listed = [...rows].sort((a, b) => {
    const byGrade = gradeRank(a.grade) - gradeRank(b.grade);
    if (byGrade !== 0) return byGrade;
    return (b.score_flash ?? -1) - (a.score_flash ?? -1);
  });
  const notifyCount = graded.filter((r) => r.grade === "★" || r.grade === "○").length;

  const sectorMissing = !universe.values().next().value?.sector;
  const outcomeMissing = outcomeResult.dropped.length > 0;
  const trackedCount = listed.filter((r) => outcomes.has(r.code)).length;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold text-white">실적 가속 종목</h1>
        <p className="mt-1 text-sm text-slate-100">
          <strong className="text-white">{rows.length.toLocaleString("ko-KR")}종목</strong>
          {" · "}발송 대상(★/○){" "}
          <strong className="text-amber-300">{notifyCount}</strong>
        </p>
        <div className="mt-2 rounded border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm text-slate-100">
          <strong className="text-white">실적 가속</strong>이란{" "}
          <Term term="매출액">매출액 성장률</Term>과{" "}
          <Term term="영업이익">영업이익 성장률</Term>이{" "}
          <strong className="text-amber-300">둘 다 전년 동기 대비(YoY)로 전분기보다 높아진</strong>{" "}
          것이다. 성장률이 <em>높은</em> 게 아니라 성장률이 <em>더 높아진</em> 것을 본다 —
          매출 +30%도 전분기가 +50%였다면 가속이 아니다.
          <span className="mt-1 block text-slate-200">
            이 목록에는 <Term term="게이트">게이트</Term>를 통과한 종목만 있다. 탈락·판정 불가는{" "}
            <Link href="/screener" className="text-sky-300 underline">스크리너</Link>,
            용어 전체는{" "}
            <Link href="/settings" className="text-sky-300 underline">설정</Link>에 있다.
            종목별 <strong className="text-slate-100">최신 발표 분기</strong> 기준이다.
          </span>
        </div>
      </div>

      {dropped.length > 0 && (
        <p className="rounded border border-amber-700 bg-amber-900/30 px-3 py-2 text-sm text-amber-200">
          ⚠ 아직 DB에 없는 컬럼을 제외하고 조회했다: {dropped.join(", ")}
        </p>
      )}
      {sectorMissing && (
        <p className="rounded border border-amber-700 bg-amber-900/30 px-3 py-2 text-sm text-amber-200">
          ⚠ <code>krx_universe.sector</code> 컬럼이 아직 없다 — 섹터 열에 KRX 업종명이 대신
          나온다. 마이그레이션 적용 후{" "}
          <code>python -m src.universe.sector_map --save</code>를 한 번 돌리면 채워진다.
        </p>
      )}
      {outcomeMissing && (
        <p className="rounded border border-amber-700 bg-amber-900/30 px-3 py-2 text-sm text-amber-200">
          ⚠ 발표일 기준 추적 컬럼이 아직 없다: {outcomeResult.dropped.join(", ")}.
          <strong className="ml-1">0%가 아니라 미수집이다.</strong>
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        {GRADE_ORDER.map((g) => (
          <div
            key={g}
            className="rounded border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm text-slate-100"
            title={`${g} — ${
              {
                "★": "고스코어 · 미반영",
                "○": "고스코어 · 부분반영",
                "△": "고스코어 · 선반영",
                "·": "중간",
                "✕": "저스코어 · 선반영",
              }[g]
            }`}
          >
            <span className="mr-2 text-base font-bold text-white">{g}</span>
            <span className="text-slate-100">{counts.get(g) ?? 0}</span>
          </div>
        ))}
        {rows.length - graded.length > 0 && (
          <div
            className="rounded border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm text-slate-100"
            title="게이트는 통과했으나 시세가 없어 주가반영도를 판정하지 못한 종목"
          >
            반영도 미측정 {rows.length - graded.length}
          </div>
        )}
      </div>

      {/* ★ 머리글 고정 — 아래로 스크롤해도 어느 열인지 잃지 않는다.
          함정 (T64): `overflow-x-auto`만 주면 세로축도 스크롤 컨테이너가 되는데
          높이 제한이 없어 스크롤포트가 안 생긴다 → thead가 그냥 밀려 올라간다.
          높이를 제한해야 sticky가 먹는다. */}
      <div className="max-h-[70vh] overflow-auto rounded-lg border border-slate-700">
        <table className="w-full min-w-[1180px] text-sm">
          <thead className="sticky top-0 z-20 bg-slate-900 text-xs uppercase text-slate-100 shadow-[0_1px_0_0_rgba(148,163,184,0.45)]">
            <tr>
              <TermTh term="섹터">섹터</TermTh>
              <TermTh>종목명</TermTh>
              <TermTh term="등급" align="center">등급</TermTh>
              <TermTh term="분기">분기</TermTh>
              <TermTh term="스코어" align="right">스코어</TermTh>
              <TermTh term="반영도" align="right">반영도</TermTh>
              <TermTh term="시총" align="right">시총</TermTh>
              <TermTh term="최근5일상승률" align="right">최근 5일</TermTh>
              {/* 발표일 기준 추적 — 배경을 달리해 위 열들과 구분한다 */}
              {HORIZONS.map((d) => (
                <th
                  key={d}
                  scope="col"
                  className="bg-slate-800/80 px-3 py-2 text-right font-medium text-indigo-200"
                  title={`실적 발표일 기준 ${horizonLabel(d)} 주가 상승률(영업일 기준)`}
                >
                  {d < 0 ? `전 ${Math.abs(d)}일` : d === 0 ? "당일" : `후 ${d}일`}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {listed.map((r) => {
              const stock = universe.get(r.code);
              const ret5d = prices.get(r.code)?.ret_5d ?? null;
              const o = outcomes.get(r.code);
              return (
                <tr key={r.code} className="border-t border-slate-800 hover:bg-slate-900/60">
                  <td
                    className="whitespace-nowrap px-3 py-2 text-slate-100"
                    title={stock?.industry ?? undefined}
                  >
                    {stock?.sector ?? stock?.industry ?? DASH}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <Link href={`/stock/${r.code}`} className="font-medium text-sky-300 hover:underline">
                      {stock?.name ?? r.code}
                    </Link>
                    <span className="ml-2 text-xs text-slate-300">{r.code}</span>
                  </td>
                  <td className="px-3 py-2 text-center">
                    <GradeBadge grade={r.grade} />
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-slate-100">
                    {quarterLabel(r.fiscal_year, r.fiscal_quarter)}
                  </td>
                  <td className="px-3 py-2 text-right font-semibold tabular-nums text-white">
                    {num(r.score_flash, 1)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-100">
                    {num(r.pri, 1)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-100">
                    {marketCap(stock?.market_cap_krw)}
                  </td>
                  <td className={`px-3 py-2 text-right tabular-nums ${returnClass(ret5d)}`}>
                    {pct(ret5d, 1)}
                  </td>
                  {HORIZONS.map((d) => {
                    const v = o ? (o[excessField(d)] as number | null) : null;
                    return (
                      <td
                        key={d}
                        className={`bg-slate-900/50 px-3 py-2 text-right tabular-nums ${returnClass(v)}`}
                      >
                        {pct(v, 1)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
            {listed.length === 0 && (
              <tr>
                <td colSpan={8 + HORIZONS.length} className="px-3 py-8 text-center text-slate-100">
                  실적이 가속 중인 종목이 없다.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="space-y-1 text-sm text-slate-100">
        <p>
          <strong className="text-white">스코어</strong> 실적 가속의 강도(100점, 높을수록 좋다) ·{" "}
          <strong className="text-white">반영도</strong> 주가가 이 실적을 이미 아는 정도
          (<strong className="text-amber-300">낮을수록 아직 안 올랐다</strong>) ·{" "}
          <strong className="text-white">등급</strong>{" "}
          <span className="text-amber-300">★는 스코어가 높은데 반영도가 낮은</span> 가장 찾던 구간 ·{" "}
          <strong className="text-white">최근 5일</strong> 최근 5거래일 주가 상승률.
        </p>
        <p>
          <strong className="text-indigo-200">전 5일 / 당일 / 후 5·20·60일</strong>은{" "}
          <strong className="text-white">그 종목의 실적 발표일</strong>을 기준으로 한{" "}
          <strong className="text-white">지수 대비 초과수익(%p)</strong>이다 — 영업일로 센다.
          발표 <em>전</em>이 크면 정보가 미리 반영된 것이고, 발표 <em>후</em>가 크면 발표를 보고
          들어가도 늦지 않았다는 뜻이다.{" "}
          <Link href="/outcome" className="text-sky-300 underline">결과 추적</Link>에서
          시기별 전략 분석을 볼 수 있다.
        </p>
        <p className="text-slate-200">
          추적 데이터가 있는 종목 {trackedCount}/{listed.length} · 등급 높은 순, 같은 등급 안에서는
          스코어 높은 순 · 결측은 <span className="text-white">—</span>다(0이 아니라 측정하지 못했다는 뜻).
        </p>
      </div>
    </div>
  );
}
