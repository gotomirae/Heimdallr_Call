// PRD Ref: §9 /screener — 전 종목 스크리너
import ScreenerTable, { type ScreenerRow } from "@/components/ScreenerTable";
import { getLatestScreens, getUniverse } from "@/lib/queries";
import { quarterLabel } from "@/lib/format";
import type { Grade, ScreenRow } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * 게이트 탈락 사유를 사람 말로.
 *
 * ★ `gate_detail`은 부분적으로 채워질 수 있다(스크리너 버전이 바뀌면 키가 는다).
 *   상위 객체만 확인하고 하위를 읽으면 페이지가 500이 난다 — 필드 단위로 본다.
 */
function failReasons(detail: Record<string, unknown> | null): string[] {
  if (!detail) return [];
  const out: string[] = [];
  if (detail.g1 === false) out.push("매출 가속 없음");
  if (detail.g2 === false) out.push("이익 성장 없음");
  if (detail.g3 === false) out.push("업종·상장기간");
  if (detail.g0 === false) out.push("데이터 부족");
  return out;
}

export default async function ScreenerPage() {
  // ★ 이 화면만 전수를 본다. "왜 안 걸렸나"를 확인하는 곳이라
  //   가속 종목만 담으면 존재 이유가 사라진다.
  const [{ rows: screens, dropped }, universe] = await Promise.all([
    getLatestScreens({ accelerating: false }),
    getUniverse(),
  ]);

  const rows: ScreenerRow[] = screens.map((s: ScreenRow) => {
    const u = universe.get(s.code);
    return {
      code: s.code,
      name: u?.name ?? s.code,
      board: u?.board ?? null,
      industry: u?.industry ?? null,
      marketCap: u?.market_cap_krw ?? null,
      quarter: quarterLabel(s.fiscal_year, s.fiscal_quarter),
      gatePassed: s.gate_passed,
      grade: s.grade as Grade | null,
      score: s.score_flash,
      pri: s.pri,
      hasConsensus: s.has_consensus,
      baseEffect: s.base_effect_warning,
      failReasons: failReasons(
        (s.gate_detail as Record<string, unknown> | null) ?? null
      ),
    };
  });

  const passed = rows.filter((r) => r.gatePassed === true).length;
  const failed = rows.filter((r) => r.gatePassed === false).length;
  const undecided = rows.length - passed - failed;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold">전 종목 스크리너</h1>
        <p className="mt-1 text-sm text-slate-200">
          {rows.length.toLocaleString("ko-KR")}종목 · 가속 {passed} · 탈락 {failed} ·
          판정 불가 {undecided}
        </p>
        <p className="mt-1 text-xs text-slate-300">
          다른 화면과 달리 <strong>탈락 종목까지 전부</strong> 담는다 —
          여기는 &ldquo;왜 안 걸렸나&rdquo;를 확인하는 곳이다.
          종목별 <strong>최신 발표 분기</strong> 기준.
        </p>
      </div>

      {dropped.length > 0 && (
        <p className="rounded border border-amber-800/60 bg-amber-900/20 px-3 py-2 text-xs text-amber-300">
          ⚠ 아직 DB에 없는 컬럼을 제외하고 조회했다: {dropped.join(", ")}
        </p>
      )}

      <ScreenerTable rows={rows} />
    </div>
  );
}
