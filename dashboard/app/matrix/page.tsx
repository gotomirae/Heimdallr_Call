// PRD Ref: §9 /matrix · ADR 5 (PRI를 스코어에 합산하지 않는 이유가 이 화면이다)
import MatrixScatter, { type MatrixPoint } from "@/components/MatrixScatter";
import { getLatestScreens, getUniverse } from "@/lib/queries";
import type { Grade } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function MatrixPage() {
  const [{ rows }, universe] = await Promise.all([getLatestScreens(), getUniverse()]);

  // 두 축이 **모두** 있어야 점을 찍는다. 하나라도 없으면 위치가 거짓이 된다.
  const points: MatrixPoint[] = rows
    .filter((r) => r.score_flash != null && r.pri != null)
    .map((r) => ({
      code: r.code,
      name: universe.get(r.code)?.name ?? r.code,
      score: r.score_flash as number,
      pri: r.pri as number,
      grade: r.grade as Grade | null,
    }));

  // 게이트 통과분 중에서도 시세가 없어 PRI를 못 잰 종목은 점을 찍지 않는다.
  const undecided = rows.length - points.length;

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold">2축 매트릭스</h1>
        <p className="mt-1 text-sm text-slate-300">
          실적이 가속 중인 {rows.length.toLocaleString("ko-KR")}종목 ·
          X = 스코어(펀더멘털 강도) · Y = 주가반영도(낮을수록 미반영). 점을 클릭하면 상세로 간다.
        </p>
        <p className="mt-1 text-xs text-slate-400">
          두 축을 한 숫자로 합치지 않는다(ADR 5). 같은 스코어라도 이미 오른 종목과
          안 오른 종목은 전혀 다른 투자다 — <strong>좋은 기업과 좋은 투자는 다르다.</strong>
        </p>
      </div>

      {/* 사분면 범례 — SVG 안 라벨은 렌더되지 않아 여기로 뺐다. */}
      <div className="flex flex-wrap gap-3 text-xs">
        {[
          { color: "#f59e0b", title: "★ 고스코어 · 미반영", note: "우하단 — 목표 구간" },
          { color: "#10b981", title: "○ 고스코어 · 부분반영", note: "발송 대상" },
          { color: "#6366f1", title: "△ 고스코어 · 선반영", note: "우상단 — 조정 시 담을 구간" },
          { color: "#ef4444", title: "✕ 저스코어 · 선반영", note: "좌상단 — 제외" },
          { color: "#94a3b8", title: "판정 불가", note: "게이트 미통과 또는 PRI 없음" },
        ].map((q) => (
          <span
            key={q.title}
            className="inline-flex items-center gap-2 rounded border border-slate-800 bg-slate-900/40 px-2 py-1"
          >
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: q.color }}
            />
            <span className="text-slate-200">{q.title}</span>
            <span className="text-slate-400">{q.note}</span>
          </span>
        ))}
      </div>

      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-3">
        <MatrixScatter points={points} />
      </div>

      <p className="text-xs text-slate-400">
        점 {points.length.toLocaleString("ko-KR")}개 · 주가반영도를 판정하지 못해 표시하지 않은
        종목 {undecided.toLocaleString("ko-KR")}개(시세 결측). 0으로 채워 찍으면 원점 근처에
        가짜 군집이 생긴다. <strong>게이트 탈락 종목은 애초에 이 화면에 없다.</strong>
      </p>
    </div>
  );
}
