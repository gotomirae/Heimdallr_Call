// PRD Ref: §9 — 발굴 목록 (스크리너 통합)
//
// ★ 스크리너를 별도 탭으로 두지 않는다. 보던 것이 같고 다른 건 "게이트 통과분만
//   보나, 탈락까지 보나"뿐인데 그건 필터 하나다. 탭이 둘이면 열 구성이 갈라져
//   어느 쪽이 최신인지 모르게 된다.
import Link from "next/link";
import DiscoveryTable, { type DiscoveryRow } from "@/components/DiscoveryTable";
import { HORIZONS, excessField, type OutcomeRow, getOutcomes } from "@/lib/outcome";
import { getAllLatestPrices, getLatestScreens, getUniverse } from "@/lib/queries";
import { quarterLabel } from "@/lib/format";
import type { Grade, ScreenRow } from "@/lib/types";

export const dynamic = "force-dynamic";

const GRADE_ORDER: Grade[] = ["★", "○", "△", "·", "✕"];

/**
 * 게이트 탈락 사유를 사람 말로.
 *
 * ★ `gate_detail`은 부분적으로 채워질 수 있다. 상위 객체만 확인하고 하위를 읽으면
 *   페이지가 500이 난다 — 필드 단위로 본다(§9.2).
 */
function failReasons(detail: Record<string, unknown> | null): string[] {
  if (!detail) return [];
  const out: string[] = [];
  if (detail.g1 === false) out.push("매출 가속 없음");
  if (detail.g2 === false) out.push("이익 가속 없음");
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
    const excess: DiscoveryRow["excess"] = {};
    for (const d of HORIZONS) {
      excess[d] = o ? ((o[excessField(d)] as number | null) ?? null) : null;
    }
    return {
      code: s.code,
      name: u?.name ?? s.code,
      board: u?.board ?? null,
      sector: u?.sector ?? null,
      industry: u?.industry ?? null,
      marketCap: u?.market_cap_krw ?? null,
      quarter: quarterLabel(s.fiscal_year, s.fiscal_quarter),
      gatePassed: s.gate_passed,
      grade: s.grade as Grade | null,
      score: s.score_flash,
      pri: s.pri,
      hasConsensus: s.has_consensus,
      baseEffect: s.base_effect_warning,
      failReasons: failReasons((s.gate_detail as Record<string, unknown> | null) ?? null),
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
  const sectorMissing = !universe.values().next().value?.sector;

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

        {/* ★ 게이트 기준 — 핵심만. 길게 쓰면 정작 안 읽힌다(사용자 요청). */}
        <div className="mt-2 rounded border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm text-slate-100">
          <strong className="text-white">게이트</strong> — 아래를 <strong>모두</strong> 만족하면 통과:
          <div className="mt-1 font-mono text-xs leading-relaxed text-slate-200">
            ① 매출 성장률(YoY)이 <span className="text-amber-300">전분기보다 높아지고</span> 양(+)
            <br />
            ② 영업이익 성장률(YoY)이 <span className="text-amber-300">전분기보다 높아지고</span> 양(+)
            <span className="text-slate-300"> — 흑자 전환은 통과 인정</span>
            <br />
            ③ 제외 업종·관리종목·스팩이 아니고 상장 이력 5분기 이상
          </div>
          <p className="mt-1 text-xs text-slate-200">
            성장률이 <em>높은</em> 게 아니라 <em>더 높아진</em> 것을 본다. 데이터가 없으면
            탈락이 아니라 <strong className="text-slate-100">판정 불가</strong>다.
          </p>
        </div>
      </div>

      {dropped.length > 0 && (
        <p className="rounded border border-amber-700 bg-amber-900/30 px-3 py-2 text-sm text-amber-200">
          ⚠ 아직 DB에 없는 컬럼을 제외하고 조회했다: {dropped.join(", ")}
        </p>
      )}
      {sectorMissing && (
        <p className="rounded border border-amber-700 bg-amber-900/30 px-3 py-2 text-sm text-amber-200">
          ⚠ <code>krx_universe.sector</code> 컬럼이 없어 KRX 업종명으로 대체 표시한다.
          마이그레이션 후 <code>python -m src.universe.sector_map --save</code>를 돌리면 채워진다.
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

      <p className="text-sm text-slate-200">
        <strong className="text-white">반영도</strong>는{" "}
        <strong className="text-amber-300">낮을수록 아직 안 올랐다</strong>는 뜻이고,{" "}
        <span className="text-amber-300">★</span>는 스코어 높고 반영도 낮은 구간이다.{" "}
        <strong className="text-indigo-200">전/당일/후 열</strong>은 그 종목 발표일 기준{" "}
        <strong className="text-white">지수 대비 초과수익</strong> —{" "}
        <Link href="/outcome" className="text-sky-300 underline">결과 추적</Link>에 시기별 전략이 있다.
        결측은 <span className="text-white">—</span>다(0이 아니다).
      </p>
    </div>
  );
}
