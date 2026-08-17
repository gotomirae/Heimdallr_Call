// PRD Ref: §9.1 — 향후 주가 상승 트리거 타임라인
//
// ★ 목록으로 나열하면 "언제 무슨 일이 있는가"의 **순서**가 안 보인다.
//   트리거는 시점이 본질이다 — 다음 확인 지점이 2주 뒤인지 5개월 뒤인지에 따라
//   지금 들어갈지 기다릴지가 갈린다. 그래서 세로 타임라인으로 그린다.
//
// ★ 서버 컴포넌트다("use client" 없음). 순수 렌더라 상태가 필요 없고,
//   차트 라이브러리를 끌어오지 않아 번들이 늘지 않는다.
import type { Trigger } from "@/lib/analysis";
import { DASH } from "@/lib/format";

export interface TimelineItem extends Trigger {
  /** '3개월 내' · '6개월 내' — 어느 구간에서 왔는지. */
  window: string;
  /** 구간 색. 가까운 것을 밝게 둔다. */
  tone: "near" | "far";
}

/**
 * `expected_date`를 정렬 키로 바꾼다. 형식이 제각각이라(YYYY-MM · YYYY-MM-DD · '2026년 11월')
 * **읽히는 것만** 쓰고 못 읽으면 뒤로 보낸다.
 *
 * ★ 못 읽은 날짜를 오늘로 채우면 순서가 조용히 뒤집힌다 — 없는 건 없는 대로 둔다.
 */
export function sortKey(text: string | null): string {
  if (!text) return "9999";
  const iso = text.match(/(\d{4})[-./년\s]*(\d{1,2})?/);
  if (!iso) return "9999";
  const year = iso[1];
  const month = (iso[2] ?? "13").padStart(2, "0"); // 월이 없으면 그 해 끝으로
  return `${year}-${month}`;
}

const TONE = {
  near: {
    dot: "bg-amber-400 ring-amber-400/30",
    line: "bg-amber-400/40",
    chip: "border-amber-500/50 bg-amber-500/10 text-amber-200",
  },
  far: {
    dot: "bg-sky-400 ring-sky-400/30",
    line: "bg-sky-400/30",
    chip: "border-sky-500/50 bg-sky-500/10 text-sky-200",
  },
} as const;

export default function TriggerTimeline({ items }: { items: TimelineItem[] }) {
  if (items.length === 0) {
    return (
      <p className="text-sm text-slate-300">
        확인할 트리거가 없다 — 아직 분석하지 않았거나 모델이 짚어내지 못했다.
      </p>
    );
  }

  const sorted = [...items].sort(
    (a, b) => sortKey(a.expectedDate).localeCompare(sortKey(b.expectedDate))
  );

  return (
    <ol className="relative space-y-0">
      {sorted.map((t, i) => {
        const tone = TONE[t.tone];
        const last = i === sorted.length - 1;
        return (
          <li key={`${t.event}-${i}`} className="relative flex gap-4 pb-5 last:pb-0">
            {/* 점 + 세로선 */}
            <div className="relative flex w-3 shrink-0 justify-center">
              <span
                className={`z-10 mt-1.5 h-3 w-3 shrink-0 rounded-full ring-4 ${tone.dot}`}
                aria-hidden
              />
              {!last && (
                <span
                  className={`absolute top-4 h-full w-px ${tone.line}`}
                  aria-hidden
                />
              )}
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-sm font-semibold tabular-nums text-slate-100">
                  {t.expectedDate ?? "시점 미정"}
                </span>
                <span className={`rounded border px-1.5 py-0.5 text-[11px] ${tone.chip}`}>
                  {t.window}
                </span>
              </div>
              <p className="mt-0.5 text-sm text-slate-200">{t.event ?? DASH}</p>
              {t.metric && (
                // ★ '무엇을 보고 확인할 것인가'가 트리거의 핵심이다.
                //   이게 없으면 "좋아질 것이다" 수준의 말과 구분되지 않는다.
                <p className="mt-0.5 text-xs text-slate-300">
                  <span className="text-slate-400">확인 지표 · </span>
                  {t.metric}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
