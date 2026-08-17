// PRD Ref: §9.1-2 (경고 배지 필수) · ADR 2
import { GRADE_COLOR, GRADE_MEANING, type Grade } from "@/lib/types";

export function GradeBadge({ grade }: { grade: Grade | null }) {
  if (!grade) {
    // ★ 등급 없음은 "낮다"가 아니라 "판정하지 못했다"이다(T35).
    return (
      <span
        className="inline-flex items-center gap-1 rounded border border-slate-700 px-2 py-0.5 text-sm text-slate-300"
        title="게이트 미통과 또는 PRI 판정 불가"
      >
        판정 불가
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-2 rounded px-2 py-0.5 text-sm font-semibold"
      style={{ backgroundColor: `${GRADE_COLOR[grade]}22`, color: GRADE_COLOR[grade] }}
      title={GRADE_MEANING[grade]}
    >
      <span className="text-base">{grade}</span>
      <span className="text-xs font-normal">{GRADE_MEANING[grade]}</span>
    </span>
  );
}

/**
 * 경고 배지. **미측정과 이상 없음을 구분해서** 보여준다.
 * "경고 없음"으로만 쓰면 검증된 것처럼 읽히는데, 실제로는 판정 불가인 경우가 많다.
 */
export function WarningBadges({
  baseEffectWarning,
  baseEffectMeasurable,
  sectorCaveat,
  hasConsensus,
  isEstimate,
}: {
  baseEffectWarning: boolean | null;
  baseEffectMeasurable: boolean;
  sectorCaveat: string | null;
  hasConsensus: boolean | null;
  isEstimate: boolean | null;
}) {
  const badges: { text: string; tone: string; title: string }[] = [];

  if (baseEffectWarning) {
    badges.push({
      text: "기저효과 경고",
      tone: "amber",
      title: "전년 동기가 비정상적으로 낮아 성장률이 부풀려졌을 수 있다",
    });
  }
  if (!baseEffectMeasurable) {
    badges.push({
      text: "기저효과 판정 불가",
      tone: "slate",
      title: "3개 조건을 모두 잴 수 없었다 — '경고 없음'과 다르다",
    });
  }
  if (sectorCaveat) {
    badges.push({ text: "업종 주의", tone: "amber", title: sectorCaveat });
  }
  if (!hasConsensus) {
    badges.push({
      text: "컨센서스 없음 (정규화)",
      tone: "sky",
      title: "C축을 분모에서 제외하고 정규화했다. 0점 처리가 아니다(ADR 2)",
    });
  }
  if (isEstimate) {
    badges.push({
      text: "잠정치",
      tone: "violet",
      title: "잠정실적 공시 기준. 확정치에서 바뀔 수 있다",
    });
  }

  if (badges.length === 0) {
    return <span className="text-xs text-slate-400">경고 없음</span>;
  }

  const tones: Record<string, string> = {
    amber: "border-amber-700/60 bg-amber-900/30 text-amber-300",
    slate: "border-slate-700 bg-slate-800/60 text-slate-200",
    sky: "border-sky-700/60 bg-sky-900/30 text-sky-300",
    violet: "border-violet-700/60 bg-violet-900/30 text-violet-300",
  };

  return (
    <div className="flex flex-wrap gap-1.5">
      {badges.map((b) => (
        <span
          key={b.text}
          title={b.title}
          className={`rounded border px-2 py-0.5 text-xs ${tones[b.tone]}`}
        >
          {b.text}
        </span>
      ))}
    </div>
  );
}
