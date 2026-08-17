// PRD Ref: §9 — 발굴 목록 (섹터·종목명·등급·분기·스코어·반영도·시총·최근 5일 상승률)
import Link from "next/link";
import { GradeBadge } from "@/components/Badges";
import { Term, TermTh } from "@/components/Term";
import { DASH, marketCap, num, pct, quarterLabel } from "@/lib/format";
import { getAllLatestPrices, getLatestScreens, getUniverse } from "@/lib/queries";
import type { Grade } from "@/lib/types";

export const dynamic = "force-dynamic";

const GRADE_ORDER: Grade[] = ["★", "○", "△", "·", "✕"];

/** 정렬용 순위. 등급이 없는 행(반영도 미측정)은 **맨 뒤**로 보낸다. */
const GRADE_RANK = new Map<Grade, number>(GRADE_ORDER.map((g, i) => [g, i]));
function gradeRank(grade: Grade | null): number {
  return grade == null ? GRADE_ORDER.length : (GRADE_RANK.get(grade) ?? GRADE_ORDER.length);
}

/** 최근 5일 상승률은 부호에 따라 색을 바꾼다 — 표에서 눈이 먼저 가야 하는 열이다. */
function returnClass(value: number | null | undefined): string {
  if (value == null) return "text-slate-400";
  if (value > 0) return "text-rose-400";
  if (value < 0) return "text-sky-400";
  return "text-slate-300";
}

export default async function HomePage() {
  const [{ rows, dropped }, universe, priceResult] = await Promise.all([
    getLatestScreens(),
    getUniverse(),
    getAllLatestPrices(),
  ]);
  const prices = priceResult.prices;

  const graded = rows.filter((r) => r.grade != null);
  const counts = new Map<Grade, number>();
  for (const r of graded) {
    counts.set(r.grade as Grade, (counts.get(r.grade as Grade) ?? 0) + 1);
  }

  // ★ 게이트를 통과한 종목 전부를 **등급 높은 순**으로 보여준다(사용자 지정).
  //   같은 등급 안에서는 스코어가 높은 순이다 — 등급만으로는 ★ 27종목의
  //   순서가 정해지지 않아 매번 다른 차례로 보이면 읽는 사람이 기준을 잃는다.
  //   탈락 종목은 애초에 조회에서 빠진다(`getLatestScreens`).
  const listed = [...rows].sort((a, b) => {
    const byGrade = gradeRank(a.grade) - gradeRank(b.grade);
    if (byGrade !== 0) return byGrade;
    return (b.score_flash ?? -1) - (a.score_flash ?? -1);
  });
  const notifyCount = graded.filter((r) => r.grade === "★" || r.grade === "○").length;

  const ret5dMissing = priceResult.dropped.includes("ret_5d");
  const ret5dMeasured = listed.filter((r) => prices.get(r.code)?.ret_5d != null).length;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold">실적 가속 종목</h1>
        <p className="mt-1 text-sm text-slate-300">
          {rows.length.toLocaleString("ko-KR")}종목 · 발송 대상(★/○) {notifyCount}
        </p>
        {/* ★ 정의를 목록 맨 위에 박아 둔다. "왜 이 종목들이 여기 있나"의 답이다. */}
        <div className="mt-2 rounded border border-slate-800 bg-slate-900/40 px-3 py-2 text-xs text-slate-300">
          <strong className="text-slate-200">실적 가속</strong>이란{" "}
          <Term term="매출액">매출액 성장률</Term>과{" "}
          <Term term="영업이익">영업이익 성장률</Term>이{" "}
          <strong className="text-slate-200">둘 다 전년 동기 대비(YoY)로 전분기보다 높아진</strong>{" "}
          것이다. 성장률이 <em>높은</em> 게 아니라 성장률이 <em>더 높아진</em> 것을 본다 —
          매출 +30%도 전분기가 +50%였다면 가속이 아니다.
          <span className="mt-1 block text-slate-400">
            이 목록에는 <Term term="게이트">게이트</Term>를 통과한 종목만 있다. 탈락·판정 불가
            종목은 <Link href="/screener" className="text-sky-500 hover:underline">스크리너</Link>에서
            탈락 사유와 함께 볼 수 있고, 용어 설명은{" "}
            <Link href="/settings" className="text-sky-500 hover:underline">설정</Link> 화면에 모아 두었다.
            종목별 <strong>최신 발표 분기</strong> 기준이다.
          </span>
        </div>
      </div>

      {dropped.length > 0 && (
        <p className="rounded border border-amber-800/60 bg-amber-900/20 px-3 py-2 text-xs text-amber-300">
          ⚠ 아직 DB에 없는 컬럼을 제외하고 조회했다: {dropped.join(", ")}
        </p>
      )}
      {ret5dMissing && (
        <p className="rounded border border-amber-800/60 bg-amber-900/20 px-3 py-2 text-xs text-amber-300">
          ⚠ <code>price_snapshots.ret_5d</code> 컬럼이 아직 없다 — 최근 5일 상승률 열이 전부
          비어 있다. 마이그레이션 적용 후 다음 시세 수집(매일 06:00 KST)에서 채워진다.
          <strong className="ml-1">0%가 아니라 미수집이다.</strong>
        </p>
      )}
      {!ret5dMissing && ret5dMeasured === 0 && listed.length > 0 && (
        <p className="rounded border border-slate-700 bg-slate-900/40 px-3 py-2 text-xs text-slate-300">
          최근 5일 상승률이 아직 한 종목도 수집되지 않았다 — 다음 시세 수집에서 채워진다.
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        {GRADE_ORDER.map((g) => (
          <div
            key={g}
            className="rounded border border-slate-800 bg-slate-900/40 px-3 py-2 text-sm"
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
            <span className="mr-2 font-semibold">{g}</span>
            <span className="text-slate-300">{counts.get(g) ?? 0}</span>
          </div>
        ))}
        {rows.length - graded.length > 0 && (
          <div
            className="rounded border border-slate-800 bg-slate-900/40 px-3 py-2 text-sm text-slate-300"
            title="게이트는 통과했으나 시세가 없어 주가반영도를 판정하지 못한 종목"
          >
            반영도 미측정 {rows.length - graded.length}
          </div>
        )}
      </div>

      {/* ★ 헤더 고정 — 아래로 스크롤해도 어느 열인지 잃지 않는다(사용자 지정).
          `overflow-x-auto`만 있는 컨테이너에서는 sticky가 먹지 않으므로
          세로 스크롤은 페이지에 맡기고 `sticky top-0`을 thead에 준다. */}
      <div className="overflow-x-auto rounded-lg border border-slate-800">
        <table className="w-full min-w-[900px] text-sm">
          <thead className="sticky top-0 z-10 bg-slate-900 text-xs uppercase text-slate-300 shadow-[0_1px_0_0_rgba(148,163,184,0.25)]">
            <tr>
              <TermTh term="섹터">섹터</TermTh>
              <TermTh term="">종목명</TermTh>
              <TermTh term="등급" align="center">등급</TermTh>
              <TermTh term="분기">분기</TermTh>
              <TermTh term="스코어" align="right">스코어</TermTh>
              <TermTh term="반영도" align="right">반영도</TermTh>
              <TermTh term="시총" align="right">시총</TermTh>
              <TermTh term="최근5일상승률" align="right">최근 5일</TermTh>
            </tr>
          </thead>
          <tbody>
            {listed.map((r) => {
              const stock = universe.get(r.code);
              const ret5d = prices.get(r.code)?.ret_5d ?? null;
              return (
                <tr key={r.code} className="border-t border-slate-800/60 hover:bg-slate-900/40">
                  <td
                    className="max-w-[13rem] truncate px-3 py-2 text-xs text-slate-400"
                    title={stock?.industry ?? undefined}
                  >
                    {stock?.industry ?? DASH}
                  </td>
                  <td className="px-3 py-2">
                    <Link href={`/stock/${r.code}`} className="text-sky-400 hover:underline">
                      {stock?.name ?? r.code}
                    </Link>
                    <span className="ml-2 text-xs text-slate-400">{r.code}</span>
                  </td>
                  <td className="px-3 py-2 text-center">
                    <GradeBadge grade={r.grade} />
                  </td>
                  <td className="px-3 py-2 text-slate-300">
                    {quarterLabel(r.fiscal_year, r.fiscal_quarter)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{num(r.score_flash, 1)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{num(r.pri, 1)}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-slate-300">
                    {marketCap(stock?.market_cap_krw)}
                  </td>
                  <td className={`px-3 py-2 text-right tabular-nums ${returnClass(ret5d)}`}>
                    {pct(ret5d, 1)}
                  </td>
                </tr>
              );
            })}
            {listed.length === 0 && (
              <tr>
                <td colSpan={8} className="px-3 py-8 text-center text-slate-400">
                  실적이 가속 중인 종목이 없다.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-slate-400">
        <strong className="text-slate-300">스코어</strong> 실적 가속의 강도(100점 만점, 높을수록 좋다) ·{" "}
        <strong className="text-slate-300">반영도</strong> 주가가 이 실적을 이미 아는 정도
        (<strong className="text-slate-300">낮을수록 아직 안 올랐다는 뜻</strong>) ·{" "}
        <strong className="text-slate-300">등급</strong> 두 축을 교차한 판정으로,{" "}
        <span className="text-amber-300">★는 스코어가 높은데 반영도가 낮은</span> 가장 찾던 구간이다 ·{" "}
        <strong className="text-slate-300">최근 5일</strong> 최근 5거래일 주가 상승률.
        <span className="mt-1 block">
          등급이 높은 순으로 정렬했고, 같은 등급 안에서는 스코어가 높은 순이다.
          결측은 <span className="text-slate-300">—</span>로 표시한다 — 0이 아니라 측정하지
          못했다는 뜻이다.
        </span>
      </p>
    </div>
  );
}
