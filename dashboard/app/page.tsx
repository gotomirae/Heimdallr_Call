// PRD Ref: §9 — 발굴 목록 (스크리너 통합)
//
// ★ 스크리너를 별도 탭으로 두지 않는다. 보던 것이 같고 다른 건 "게이트 통과분만
//   보나, 탈락까지 보나"뿐인데 그건 필터 하나다. 탭이 둘이면 열 구성이 갈라져
//   어느 쪽이 최신인지 모르게 된다.
import Link from "next/link";
import DiscoveryTable, { type DiscoveryRow } from "@/components/DiscoveryTable";
import { HORIZONS, excessField, type OutcomeRow, getOutcomes } from "@/lib/outcome";
import {
  getAllLatestPrices,
  getFundamentalsForQuarters,
  getLatestScreens,
  getUniverse,
} from "@/lib/queries";
import { quarterLabel, qIndex } from "@/lib/format";
import { sectorOf } from "@/lib/sector";
import type { FundamentalRow, Grade, ScreenRow } from "@/lib/types";

export const dynamic = "force-dynamic";

const GRADE_ORDER: Grade[] = ["★", "○", "△", "·", "✕"];

/**
 * 게이트 탈락 사유를 사람 말로.
 *
 * ★ `gate_detail`은 부분적으로 채워질 수 있다. 상위 객체만 확인하고 하위를 읽으면
 *   페이지가 500이 난다 — 필드 단위로 본다(§9.2).
 * ★ `g4`는 2026-08-22에 생겼다. **그 전에 저장된 행에는 없다** — `=== false`로만
 *   보므로 없는 행은 사유가 안 붙을 뿐 화면이 깨지지 않는다.
 */
function failReasons(detail: Record<string, unknown> | null): string[] {
  if (!detail) return [];
  const out: string[] = [];
  if (detail.g1 === false) out.push("매출 가속 없음");
  if (detail.g2 === false) out.push("이익 가속 없음");
  if (detail.g4 === false) out.push("OPM 하락");
  if (detail.g3 === false) out.push("업종·상장기간");
  if (detail.g0 === false) out.push("데이터 부족");
  return out;
}

export default async function HomePage() {
  // ★ 전수를 읽는다(accelerating:false). 통과분만 읽으면 필터로 탈락을 볼 수 없다.
  const [{ rows: screens, dropped }, universe, priceResult, outcomeResult] =
    await Promise.all([
      getLatestScreens({ accelerating: false }),
      getUniverse(),
      getAllLatestPrices(),
      getOutcomes(),
    ]);

  // ── 성장률 열의 재료 ────────────────────────────────────────────
  // ★ `screen_results`에는 YoY 원자료가 없다(점수만 있다). 표에 매출·영업이익 YoY를
  //   실으려면 그 **평가 분기의** 재무를 따로 읽어야 한다.
  // ★ 종목마다 평가 분기가 다르다(T36) — 최신 한 분기만 읽으면 먼저 발표한 종목과
  //   늦은 종목이 섞여 **일부 행만 조용히 빈다.** 실제로 존재하는 분기를 전부 읽는다.
  const quarterKeys = [
    ...new Set(screens.map((s) => qIndex(s.fiscal_year, s.fiscal_quarter))),
  ];
  const funds = await getFundamentalsForQuarters(
    quarterKeys.map((k) => ({ year: Math.floor(k / 4), quarter: (k % 4) + 1 }))
  );
  const fundByKey = new Map<string, FundamentalRow>(
    funds.map((f) => [`${f.code}|${f.fiscal_year}|${f.fiscal_quarter}`, f])
  );

  // 발표일 기준 추적은 종목별 **최신 분기 1건**만 — 빈티지가 섞이면 안 된다(T40).
  const outcomes = new Map<string, OutcomeRow>();
  for (const o of outcomeResult.rows) {
    const prev = outcomes.get(o.code);
    const idx = o.fiscal_year * 4 + o.fiscal_quarter;
    if (!prev || idx > prev.fiscal_year * 4 + prev.fiscal_quarter) outcomes.set(o.code, o);
  }

  const rows: DiscoveryRow[] = screens.map((s: ScreenRow) => {
    const u = universe.get(s.code);
    const o = outcomes.get(s.code);
    const f = fundByKey.get(`${s.code}|${s.fiscal_year}|${s.fiscal_quarter}`);
    const excess: DiscoveryRow["excess"] = {};
    for (const d of HORIZONS) {
      excess[d] = o ? ((o[excessField(d)] as number | null) ?? null) : null;
    }
    return {
      code: s.code,
      name: u?.name ?? s.code,
      board: u?.board ?? null,
      // ★ DB 컬럼이 없어도 industry·products로 즉시 분류한다(DDL 불필요).
      sector: sectorOf(u),
      industry: u?.industry ?? null,
      marketCap: u?.market_cap_krw ?? null,
      quarter: quarterLabel(s.fiscal_year, s.fiscal_quarter),
      quarterIndex: qIndex(s.fiscal_year, s.fiscal_quarter),
      gatePassed: s.gate_passed,
      grade: s.grade as Grade | null,
      score: s.score_flash,
      pri: s.pri,
      hasConsensus: s.has_consensus,
      baseEffect: s.base_effect_warning,
      failReasons: failReasons((s.gate_detail as Record<string, unknown> | null) ?? null),
      // ★ 재무 행을 못 찾으면 null이다. 0으로 채우지 않는다 — 미수집과 '0% 성장'은 다르다.
      revenueYoy: f?.revenue_yoy ?? null,
      opYoy: f?.op_yoy ?? null,
      opStatusLabel: f?.op_status_label ?? null,
      opmYoyDelta: f?.opm_yoy_delta ?? null,
      ret5d: priceResult.prices.get(s.code)?.ret_5d ?? null,
      excess,
    };
  });

  const passed = rows.filter((r) => r.gatePassed === true);
  const counts = new Map<Grade, number>();
  for (const r of passed) {
    if (r.grade) counts.set(r.grade, (counts.get(r.grade) ?? 0) + 1);
  }
  const notifyCount = (counts.get("★") ?? 0) + (counts.get("○") ?? 0);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold text-white">실적 가속 종목</h1>
        <p className="mt-1 text-sm text-slate-100">
          게이트 통과{" "}
          <strong className="text-white">{passed.length.toLocaleString("ko-KR")}종목</strong>
          {" / 전체 "}{rows.length.toLocaleString("ko-KR")}
          {" · 발송 대상(★/○) "}
          <strong className="text-amber-300">{notifyCount}</strong>
        </p>

        {/* ★ 서술형을 쓰지 않는다(사용자 요청). 조건은 조건처럼, 정의는 한 줄로.
            ★★ 이 문구는 **게이트 코드와 같아야 한다.** G4(OPM)를 게이트에 넣지 않은 채
               여기에만 적으면 화면이 거짓말을 한다 — 틀린 안내는 사람을 틀린 행동으로
               이끈다(T83). `src/screener/gate.py`가 실제로 넷을 본다. */}
        <div className="mt-2 rounded border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm">
          <div className="text-slate-100">
            <strong className="text-white">게이트 통과</strong> ={" "}
            <strong className="text-amber-300">매출 YoY 가속</strong>
            {" + "}
            <strong className="text-amber-300">영업이익 YoY 가속</strong>
            {" + "}
            <strong className="text-amber-300">OPM YoY 상승</strong>
          </div>
          <div className="mt-1 text-slate-100">
            <strong className="text-white">성장 가속</strong> = 매출액과 영업이익 YoY 성장률이{" "}
            <strong className="text-amber-300">전분기보다 상승</strong>
            <span className="text-slate-300"> (성장률이 높은 것이 아니라, 더 높아진 것)</span>
          </div>
          <table className="mt-1.5 text-xs">
            <tbody className="text-slate-100">
              <tr>
                <td className="pr-3 font-mono text-slate-300">G1</td>
                <td className="pr-2">매출 YoY</td>
                <td className="text-amber-300">가속 · 양(+)</td>
              </tr>
              <tr>
                <td className="pr-3 font-mono text-slate-300">G2</td>
                <td className="pr-2">영업이익 YoY</td>
                <td className="text-amber-300">가속 · 양(+)</td>
                <td className="pl-2 text-slate-300">흑자전환 통과</td>
              </tr>
              <tr>
                <td className="pr-3 font-mono text-slate-300">G4</td>
                <td className="pr-2">영업이익률(OPM)</td>
                <td className="text-amber-300">전년 동기보다 상승</td>
                <td className="pl-2 text-slate-300">방향만 본다(크기는 스코어 B1)</td>
              </tr>
              <tr>
                <td className="pr-3 font-mono text-slate-300">G3</td>
                <td className="pr-2">업종·이력</td>
                <td className="text-slate-200">제외업종 아님 · 5분기+</td>
              </tr>
            </tbody>
          </table>
          <div className="mt-1 text-xs text-slate-300">
            넷 모두 만족 = 통과 · 데이터 없으면 탈락이 아니라 <strong className="text-slate-100">판정 불가</strong>
          </div>
        </div>
      </div>

      {dropped.length > 0 && (
        <p className="rounded border border-amber-700 bg-amber-900/30 px-3 py-2 text-sm text-amber-200">
          ⚠ 아직 DB에 없는 컬럼을 제외하고 조회했다: {dropped.join(", ")}
        </p>
      )}
      {outcomeResult.dropped.length > 0 && (
        <p className="rounded border border-amber-700 bg-amber-900/30 px-3 py-2 text-sm text-amber-200">
          ⚠ 발표일 기준 추적 컬럼이 없다: {outcomeResult.dropped.join(", ")}.
          <strong className="ml-1">0%가 아니라 미수집이다.</strong>
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        {GRADE_ORDER.map((g) => (
          <div key={g}
               className="rounded border border-slate-700 bg-slate-900/60 px-3 py-1.5 text-sm text-slate-100"
               title={{
                 "★": "고스코어 · 미반영 — 가장 찾던 구간",
                 "○": "고스코어 · 부분반영",
                 "△": "고스코어 · 선반영 (조정 시 담을 구간)",
                 "·": "중간",
                 "✕": "저스코어 · 선반영",
               }[g]}>
            <span className="mr-2 text-base font-bold text-white">{g}</span>
            <span className="text-slate-200">{counts.get(g) ?? 0}</span>
          </div>
        ))}
      </div>

      <DiscoveryTable rows={rows} />

      <div className="rounded border border-slate-700 bg-slate-900/40 px-3 py-2 text-sm">
        <table className="text-xs">
          <tbody>
            <tr>
              <td className="whitespace-nowrap pr-3 font-semibold text-white">스코어</td>
              <td className="text-slate-100">가속 강도 (100점 · 높을수록 좋다)</td>
            </tr>
            <tr>
              <td className="whitespace-nowrap pr-3 font-semibold text-white">매출·영업익 YoY</td>
              <td className="text-slate-100">
                평가 분기의 전년 동기 대비 성장률 ·{" "}
                <strong className="text-slate-200">흑전·적전</strong>은 %를 만들지 않고 라벨로 쓴다
              </td>
            </tr>
            <tr>
              <td className="whitespace-nowrap pr-3 font-semibold text-white">OPM YoY</td>
              <td className="text-slate-100">
                영업이익률의 전년 동기 대비 변화(%p) ·{" "}
                <strong className="text-amber-300">양(+)이어야 게이트를 통과한다(G4)</strong>
              </td>
            </tr>
            <tr>
              <td className="whitespace-nowrap pr-3 font-semibold text-white">반영도</td>
              <td className="text-slate-100">
                주가가 아는 정도 ·{" "}
                <strong className="text-amber-300">낮을수록 아직 안 올랐다</strong>
              </td>
            </tr>
            <tr>
              <td className="whitespace-nowrap pr-3 font-semibold text-amber-300">★</td>
              <td className="text-slate-100">스코어 높음 + 반영도 낮음 = 찾던 구간</td>
            </tr>
            <tr>
              <td className="whitespace-nowrap pr-3 font-semibold text-indigo-200">전·당일·후</td>
              <td className="text-slate-100">
                발표일 기준 지수 대비 초과수익 (영업일) ·{" "}
                <Link href="/outcome" className="text-sky-300 underline">시기별 전략</Link>
              </td>
            </tr>
            <tr>
              <td className="whitespace-nowrap pr-3 font-semibold text-white">—</td>
              <td className="text-slate-100">측정하지 못함 (0이 아니다)</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
