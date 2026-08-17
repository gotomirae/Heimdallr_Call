// PRD Ref: §2 검토⑥, §9 /outcome — 결과 추적
import { GRADE_COLOR, type Grade } from "@/lib/types";
import { DASH, num, pct } from "@/lib/format";
import {
  HORIZONS,
  bestHorizon,
  excessField,
  getOutcomes,
  groupStats,
  spearman,
  type Horizon,
  type OutcomeRow,
} from "@/lib/outcome";
import { getLatestScreens } from "@/lib/queries";
import type { ScreenRow } from "@/lib/types";

export const dynamic = "force-dynamic";

const GRADE_ORDER: Grade[] = ["★", "○", "△", "·", "✕"];

function Card({ title, note, children }: {
  title: string; note?: string; children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <h2 className="mb-1 text-sm font-semibold text-slate-200">{title}</h2>
      {note && <p className="mb-3 text-xs text-slate-400">{note}</p>}
      {children}
    </section>
  );
}

/** 초과수익 분포 막대 — p25~p75 상자와 중앙값 선. */
function DistBar({ stat }: { stat: { p25: number | null; p75: number | null; median: number | null } }) {
  if (stat.median == null || stat.p25 == null || stat.p75 == null) {
    return <span className="text-xs text-slate-400">{DASH}</span>;
  }
  const SPAN = 30; // ±30%p를 폭 전체로 본다
  const clamp = (v: number) => Math.max(-SPAN, Math.min(SPAN, v));
  const toPct = (v: number) => ((clamp(v) + SPAN) / (SPAN * 2)) * 100;
  const left = toPct(stat.p25);
  const right = toPct(stat.p75);
  const mid = toPct(stat.median);

  return (
    <div className="relative h-4 w-full min-w-[140px] rounded bg-slate-800">
      {/* 0선 */}
      <div className="absolute inset-y-0 left-1/2 w-px bg-slate-600" />
      <div
        className="absolute inset-y-1 rounded-sm bg-sky-700/70"
        style={{ left: `${left}%`, width: `${Math.max(right - left, 1)}%` }}
      />
      <div
        className="absolute inset-y-0 w-0.5 bg-sky-300"
        style={{ left: `${mid}%` }}
        title={`중앙값 ${stat.median.toFixed(2)}%p`}
      />
    </div>
  );
}

export default async function OutcomePage() {
  const [all, screensResult] = await Promise.all([getOutcomes(), getLatestScreens()]);

  // ★ 발표 시점에 등급이 없었다는 건 **그때 게이트를 통과하지 못했다**는 뜻이다
  //   (`classify()`는 게이트 미통과 시 등급을 주지 않는다).
  //   이 화면은 "가속 판정을 받았던 종목이 실제로 어떻게 됐나"를 보는 곳이므로
  //   탈락분은 뺀다 — 섞으면 등급별 비교의 분모가 오염된다.
  const rows = all.filter((r) => r.grade_at_announce != null);
  const excluded = all.length - rows.length;

  if (rows.length === 0) {
    return (
      <div className="space-y-3">
        <h1 className="text-2xl font-bold">결과 추적</h1>
        <p className="text-sm text-slate-300">
          아직 기록이 없다. <code className="text-slate-200">python -m src.analysis.outcome_run --save</code>
          로 채운다.
        </p>
      </div>
    );
  }

  const screens = new Map<string, ScreenRow>(
    screensResult.rows.map((s) => [`${s.code}|${s.fiscal_year}|${s.fiscal_quarter}`, s])
  );
  const best = bestHorizon(rows);

  const measured = (days: Horizon) =>
    rows.filter((r) => typeof r[excessField(days)] === "number").length;

  const byGrade = groupStats(rows, (r) => r.grade_at_announce as string, best);
  const gradeOrder = (key: string) => GRADE_ORDER.indexOf(key as Grade);

  // 축별 IC — screen_results의 raw 값과 초과수익의 순위상관
  const AXES: { label: string; keys: (keyof ScreenRow)[] }[] = [
    { label: "A 성장가속", keys: ["raw_a1", "raw_a2", "raw_a3", "raw_a4"] },
    { label: "B 수익성", keys: ["raw_b1", "raw_b2", "raw_b3", "raw_b4"] },
    { label: "C 서프라이즈", keys: ["raw_c1", "raw_c2"] },
  ];

  const icRows = HORIZONS.map((days) => {
    const excess = rows.map((r) => r[excessField(days)] as number | null);
    const n = excess.filter((v) => typeof v === "number").length;
    const axisIc = AXES.map(({ label, keys }) => {
      const values = rows.map((r) => {
        const s = screens.get(`${r.code}|${r.fiscal_year}|${r.fiscal_quarter}`);
        if (!s) return null;
        const parts = keys.map((k) => s[k] as number | null);
        return parts.some((v) => typeof v === "number")
          ? parts.reduce<number>((acc, v) => acc + (typeof v === "number" ? v : 0), 0)
          : null;
      });
      return { label, ic: spearman(values, excess) };
    });
    return {
      days,
      n,
      axisIc,
      scoreIc: spearman(rows.map((r) => r.score_at_announce), excess),
      priIc: spearman(rows.map((r) => r.pri_at_announce), excess),
    };
  });

  const flagStats = (getter: (s: ScreenRow | undefined) => boolean | null | undefined) =>
    groupStats(
      rows,
      (r) => {
        const v = getter(screens.get(`${r.code}|${r.fiscal_year}|${r.fiscal_quarter}`));
        return v === true ? "있음" : v === false ? "없음" : "미상";
      },
      best
    );

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold">결과 추적</h1>
        <p className="mt-1 text-sm text-slate-300">
          가속 판정을 받았던 {rows.length.toLocaleString("ko-KR")}건 ·
          비교 시점 <strong>D+{best}</strong>
          {excluded > 0 && (
            <span className="text-slate-400">
              {" "}· 게이트 탈락 {excluded.toLocaleString("ko-KR")}건 제외
            </span>
          )}
        </p>
        <p className="mt-1 text-xs text-slate-400">
          스코어 배점에는 아직 이론적 근거가 없다. 이 화면은 <strong>배점을 데이터로
          조정하기 위한 것</strong>이고, 그때까지는 방향만 본다.
          발표 시점에 <strong>게이트를 통과했던 종목</strong>만 추적한다.
        </p>
      </div>

      {/* 1. 시점별 측정 가능 건수 — 여기가 먼저다 */}
      <Card
        title="시점별 측정 가능 건수"
        note="'측정 불가'는 0%가 아니다 — 아직 그만큼의 거래일이 안 지났다는 뜻이다. 0으로 채우면 평균이 0 쪽으로 끌려간다."
      >
        <div className="flex flex-wrap gap-3 text-sm">
          {HORIZONS.map((days) => {
            const n = measured(days);
            return (
              <div
                key={days}
                className={`rounded border px-3 py-2 ${
                  n === 0
                    ? "border-slate-800 bg-slate-900/40 text-slate-400"
                    : "border-slate-700 bg-slate-900/60"
                }`}
              >
                <div className="text-xs text-slate-400">D+{days}</div>
                <div className="text-lg">
                  {n.toLocaleString("ko-KR")}
                  <span className="text-sm text-slate-400"> / {rows.length}</span>
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      {/* 2. 등급별 분포 */}
      <Card
        title={`등급별 초과수익 분포 (D+${best})`}
        note="상자는 p25~p75, 세로선은 중앙값. 가운데 선이 0%p다. 표본 수(n)를 반드시 함께 본다."
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead className="text-xs uppercase text-slate-400">
              <tr className="border-b border-slate-800">
                <th className="py-2 text-left">등급</th>
                <th className="py-2 text-right">대상</th>
                <th className="py-2 text-right">측정</th>
                <th className="py-2 text-right">중앙값</th>
                <th className="py-2 pl-4 text-left">분포</th>
              </tr>
            </thead>
            <tbody>
              {[...byGrade]
                .sort((a, b) => gradeOrder(a.key) - gradeOrder(b.key))
                .map((stat) => (
                  <tr key={stat.key} className="border-b border-slate-800/60">
                    <td className="py-2">
                      <span
                        className="font-semibold"
                        style={{ color: GRADE_COLOR[stat.key as Grade] }}
                      >
                        {stat.key}
                      </span>
                    </td>
                    <td className="py-2 text-right text-slate-300">{stat.total}</td>
                    <td className="py-2 text-right">
                      <span className={stat.n === 0 ? "text-slate-400" : ""}>{stat.n}</span>
                    </td>
                    <td className="py-2 text-right">{pct(stat.median, 2, "%p")}</td>
                    <td className="py-2 pl-4">
                      <DistBar stat={stat} />
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* 3. 축별 IC */}
      <Card
        title="스코어 축별 정보계수 (IC)"
        note="raw 값과 초과수익의 순위상관. 양수면 그 축이 실제로 작동한다는 뜻이다. PRI는 음수여야 정상 — 미반영일수록 초과수익이 커야 한다."
      >
        <div className="space-y-4">
          {icRows.map((row) => (
            <div key={row.days}>
              <div className="mb-1 text-xs font-semibold text-slate-300">
                D+{row.days}
                <span className="ml-2 font-normal text-slate-400">측정 {row.n}건</span>
                {row.n < 3 && (
                  <span className="ml-2 font-normal text-amber-400">
                    — 3건 미만이라 계산하지 않는다
                  </span>
                )}
              </div>
              {row.n >= 3 && (
                <div className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
                  {row.axisIc.map((a) => (
                    <div key={a.label} className="flex justify-between">
                      <span className="text-slate-200">{a.label}</span>
                      <span className={a.ic != null && a.ic > 0 ? "text-emerald-400" : "text-slate-300"}>
                        {a.ic != null ? a.ic.toFixed(3) : DASH}
                      </span>
                    </div>
                  ))}
                  <div className="flex justify-between border-t border-slate-800 pt-1">
                    <span className="text-slate-200">스코어 총점</span>
                    <span className={row.scoreIc != null && row.scoreIc > 0 ? "text-emerald-400" : "text-slate-300"}>
                      {row.scoreIc != null ? row.scoreIc.toFixed(3) : DASH}
                    </span>
                  </div>
                  <div className="flex justify-between border-t border-slate-800 pt-1">
                    <span className="text-slate-200">PRI (음수가 정상)</span>
                    <span className={row.priIc != null && row.priIc < 0 ? "text-emerald-400" : "text-amber-400"}>
                      {row.priIc != null ? row.priIc.toFixed(3) : DASH}
                    </span>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </Card>

      {/* 4. SC6 · SC8 */}
      <Card
        title={`SC6 · SC8 검증 (D+${best})`}
        note="SC6: 컨센서스 없는 종목이 구조적으로 불리하지 않아야 한다(ADR 2). SC8: 기저효과 경고가 실제로 나쁜 성과를 예측하는가."
      >
        <div className="grid gap-6 sm:grid-cols-2">
          {[
            { label: "컨센서스", stats: flagStats((s) => s?.has_consensus) },
            { label: "기저효과 경고", stats: flagStats((s) => s?.base_effect_warning) },
          ].map(({ label, stats }) => (
            <div key={label}>
              <div className="mb-1 text-xs font-semibold text-slate-300">{label}</div>
              <table className="w-full text-sm">
                <tbody>
                  {stats.map((s) => (
                    <tr key={s.key} className="border-b border-slate-800/60">
                      <td className="py-1 text-slate-200">{s.key}</td>
                      <td className="py-1 text-right text-slate-400">n={s.n}</td>
                      <td className="py-1 text-right">{pct(s.median, 2, "%p")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
        </div>
      </Card>

      <p className="text-xs text-slate-400">
        표본이 작으면 통계적 유의성은 없다. 시즌 2회(약 6개월)가 쌓여야 배점 조정을
        시작할 수 있다 — 그때까지는 <strong>구조를 유지하는 것</strong>이 목적이다.
      </p>
    </div>
  );
}
