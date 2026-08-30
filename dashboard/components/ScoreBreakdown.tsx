// PRD Ref: §9.1-2 (스코어 A/B/C/D 스택 바) · ADR 2 · traps.md T26, T38
import { AXES, AXIS_ITEMS, AXIS_MISSING_REASON, PRI_PARTS } from "@/lib/types";
import type { PriDetail, ScreenRow } from "@/lib/types";
import { DASH, num } from "@/lib/format";

const AXIS_COLOR: Record<string, string> = {
  a: "#38bdf8",
  b: "#34d399",
  c: "#fbbf24",
  d: "#a78bfa",
};

/**
 * 스코어 분해.
 *
 * ★ 총점만 보여주면 **왜 뽑혔는지 모른다**(PRD §9.1).
 * ★ 미측정 축은 **0점이 아니라 분모 제외**다(ADR 2). 그 사실을 문장으로 밝힌다.
 * ★ 축 **안의** 결측은 분모에서 빠지지 않아 조용히 감점된다(T26) — 따로 표시한다.
 * ★ 측정해서 0점인 항목도 숨기지 않는다(T38). 안 보이면 미측정과 구분되지 않는다.
 */
export function ScoreBreakdown({ screen }: { screen: ScreenRow }) {
  const measured = AXES.filter(
    (axis) => (screen[`score_${axis.key}` as keyof ScreenRow] as number | null) != null
  );
  const denominator = measured.reduce((sum, a) => sum + a.max, 0);
  const rawSum = measured.reduce(
    (sum, a) => sum + ((screen[`score_${a.key}` as keyof ScreenRow] as number) ?? 0),
    0
  );

  return (
    <div className="space-y-3">
      <div className="flex items-baseline gap-3">
        <span className="text-3xl font-bold">
          {num(screen.score_final ?? screen.score_flash, 1)}
        </span>
        <span className="text-sm text-slate-200">
          raw {num(rawSum, 1)} / {denominator} 정규화
        </span>
      </div>

      {/* 스택 바 — 측정된 축만 폭을 갖는다 */}
      <div className="flex h-3 overflow-hidden rounded bg-slate-800">
        {measured.map((axis) => {
          const value = (screen[`score_${axis.key}` as keyof ScreenRow] as number) ?? 0;
          return (
            <div
              key={axis.key}
              style={{
                width: `${(value / denominator) * 100}%`,
                backgroundColor: AXIS_COLOR[axis.key],
              }}
              title={`${axis.label} ${value.toFixed(1)}/${axis.max}`}
            />
          );
        })}
      </div>

      <div className="space-y-2">
        {AXES.map((axis) => {
          const value = screen[`score_${axis.key}` as keyof ScreenRow] as number | null;
          const items = AXIS_ITEMS[axis.key] ?? [];

          if (value == null) {
            return (
              <div key={axis.key} className="text-sm">
                <span className="font-medium text-slate-100">
                  {axis.key.toUpperCase()} {axis.label}
                </span>
                <span className="ml-2 text-slate-300">
                  {DASH} {AXIS_MISSING_REASON[axis.key] ?? "미측정"}
                </span>
              </div>
            );
          }

          const scored = items.filter(
            (it) => (screen[it.key as keyof ScreenRow] as number | null) != null
          );
          const missing = items.filter(
            (it) => (screen[it.key as keyof ScreenRow] as number | null) == null
          );

          return (
            <div key={axis.key} className="text-sm">
              <div className="flex items-baseline gap-2">
                <span
                  className="inline-block h-2 w-2 rounded-full"
                  style={{ backgroundColor: AXIS_COLOR[axis.key] }}
                />
                <span className="font-medium text-slate-100">
                  {axis.key.toUpperCase()} {axis.label}
                </span>
                <span className="text-slate-200">
                  {value.toFixed(0)}/{axis.max}
                </span>
              </div>
              <div className="ml-4 text-xs text-slate-200">
                {scored.length
                  ? scored
                      .map((it) => {
                        const v = screen[it.key as keyof ScreenRow] as number;
                        return `${it.label} ${v.toFixed(0)}/${it.max}`;
                      })
                      .join(" · ")
                  : "전 항목 미측정"}
              </div>
              {missing.length > 0 && (
                <div
                  className="ml-4 text-xs text-amber-400/80"
                  title="축 안의 결측은 분모에서 빠지지 않는다 — 조용히 감점된다(T26)"
                >
                  ↳ {missing.map((it) => `${it.label} 미측정(-${it.max})`).join(" · ")}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * PRI 분해.
 *
 * ★ PRI는 P1(40점)이 지배적이라 분모가 얇으면 판정 자체를 하지 않는다(T35).
 *   `pri`가 null인데 측정 항목이 있으면 **왜 보류했는지** 밝힌다 —
 *   숨기면 "반영도 0"과 구분되지 않는다.
 */
export function PriBreakdown({
  pri,
  detail,
}: {
  pri: number | null;
  detail: PriDetail | null;
}) {
  const parts = detail?.parts ?? {};
  const denominator = detail?.denominator ?? 0;

  const label =
    pri == null
      ? "판정 불가"
      : pri < 40
        ? "미반영"
        : pri <= 65
          ? "부분반영"
          : "선반영";

  return (
    <div className="space-y-3">
      <div className="flex items-baseline gap-3">
        <span className="text-3xl font-bold">{num(pri, 1)}</span>
        <span className="text-sm text-slate-200">/ 100 · {label}</span>
      </div>

      {pri == null && denominator > 0 && (
        <p className="rounded border border-amber-800/60 bg-amber-900/20 px-2 py-1 text-xs text-amber-300">
          분모 {denominator}점으로 부족해 판정을 보류했다. 0점이 아니다 —
          3개월 상대수익률(40점)이 없으면 &lsquo;미반영&rsquo;을 선언할 수 없다.
        </p>
      )}

      <div className="space-y-1.5">
        {PRI_PARTS.map((part) => {
          const value = parts[part.key];
          return (
            <div key={part.key} className="flex items-center gap-2 text-sm">
              <span className="w-32 shrink-0 text-slate-100">{part.label}</span>
              <div className="h-2 flex-1 overflow-hidden rounded bg-slate-800">
                {value != null && (
                  <div
                    className="h-full bg-sky-500"
                    style={{ width: `${(value / part.max) * 100}%` }}
                  />
                )}
              </div>
              <span className="w-20 shrink-0 text-right text-xs text-slate-200">
                {value == null ? `${DASH} 미측정` : `${value.toFixed(0)}/${part.max}`}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
