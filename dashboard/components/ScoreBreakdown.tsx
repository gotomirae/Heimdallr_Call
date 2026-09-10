// PRD Ref: §9.1-2 (스코어 A/B/C/D 스택 바) · ADR 2 · traps.md T26, T38
import { AXES, AXIS_ITEMS, AXIS_MISSING_REASON, PRI_PARTS } from "@/lib/types";
import type { PriDetail, ScreenRow } from "@/lib/types";
import { DASH, num } from "@/lib/format";
import constants from "@/lib/constants.json";

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
 * ★ PRI는 독립 축의 측정 가능 배점이 얇으면 판정 자체를 하지 않는다(T35).
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
  const inputs = detail?.inputs ?? {};
  const denominator = detail?.denominator ?? 0;
  const isV3 = detail?.mode === "v3" || Object.prototype.hasOwnProperty.call(parts, "driver");
  const isV2 = !isV3 && (detail?.mode === "v2" || Object.prototype.hasOwnProperty.call(parts, "event"));
  const isModern = isV3 || isV2;
  const confidence = detail?.confidence ?? (isModern ? denominator : null);
  const minConfidence = Number(constants.pri.min_confidence ?? 80);
  const displayParts = isV3
    ? PRI_PARTS
    : isV2
      ? [
          { key: "event", label: "실적 발표 초과반응", max: 30 },
          { key: "revision", label: "전망·주가 괴리", max: 30 },
          { key: "valuation", label: "TTM PER·F.PER 반영", max: 20 },
          { key: "relative", label: "중기 상대 주가", max: 20 },
        ]
      : [
          { key: "p1", label: "52주 신고가 대비", max: 25 },
          { key: "p2", label: "발표일 대비", max: 25 },
          { key: "p3", label: "9분기 PER", max: 20 },
          { key: "p4", label: "외국인 5일", max: 10 },
          { key: "p5", label: "RSI", max: 20 },
        ];
  const priceReturn = inputs.price_return_12m_pct;
  const multipleShare = inputs.multiple_expansion_share_pct;
  const driverLabel = priceReturn == null
    ? "상승 원인 미측정"
    : priceReturn <= 0
      ? "최근 12개월 주가 상승 없음"
      : multipleShare == null
        ? "상승 원인 미측정"
        : multipleShare >= 60
          ? "멀티플 팽창 주도"
          : multipleShare <= 40
            ? "이익 성장 주도"
            : "이익·멀티플 혼합";

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

      {isModern && (
        <div className="rounded border border-sky-800/60 bg-sky-950/30 px-2 py-2 text-xs text-sky-200">
          <div className="flex items-center justify-between">
            <span className="font-medium">PRI 신뢰도</span>
            <span>{confidence == null ? `${DASH}` : `${confidence.toFixed(0)}/100`}</span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded bg-slate-800">
            <div className="h-full bg-sky-400" style={{ width: `${Math.min(confidence ?? 0, 100)}%` }} />
          </div>
          <div className="mt-1 text-slate-300">
            가격·성장·밸류·과열 항목의 측정 가능 비중이다. {minConfidence} 미만이면 참고용으로만 본다.
          </div>
        </div>
      )}

      {pri == null && denominator > 0 && (
        <p className="rounded border border-amber-800/60 bg-amber-900/20 px-2 py-1 text-xs text-amber-300">
          분모 {denominator}점으로 부족해 판정을 보류했다. 0점이 아니다 —
          공개 원자료가 충분하지 않아 &lsquo;미반영&rsquo;을 선언할 수 없다.
        </p>
      )}

      <div className="space-y-1.5">
        {displayParts.map((part) => {
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
      <div className="rounded border border-slate-800 bg-slate-950/40 p-2 text-xs leading-relaxed text-slate-200">
        {isV3 ? (
          <>
            <div><strong>실적 발표 초과반응</strong> {num(inputs.announcement_excess_return_pct, 1)}%p → {num(parts.event, 1)}/15</div>
            <div><strong>전망·주가 괴리</strong> {num(inputs.earnings_revision_price_gap_pct, 1)}%p → {num(parts.revision, 1)}/10</div>
            <div className="mt-2 rounded border border-slate-700/70 p-2">
              <strong>주가 상승 이유 · {driverLabel}</strong>
              <div>12개월 주가 {num(priceReturn, 1)}% · TTM 이익 {num(inputs.earnings_growth_12m_pct, 1)}% · PER 변화 {num(inputs.multiple_expansion_pct, 1)}%</div>
              <div>상승분 중 멀티플 몫 {num(multipleShare, 1)}% → {num(parts.driver, 1)}/15</div>
            </div>
            <div className="mt-2 rounded border border-slate-700/70 p-2">
              <strong>내재 성장률 갭</strong>
              <div>현재 PER을 3년 뒤 역사 평균으로 정당화할 필요 성장 {num(inputs.implied_growth_required_pct, 1)}%/년</div>
              <div>컨센서스 이익 성장 {num(inputs.forecast_earnings_growth_pct, 1)}% · 갭 {num(inputs.implied_growth_gap_pct, 1)}%p → {num(parts.implied_growth, 1)}/20</div>
            </div>
            <div className="mt-2 rounded border border-slate-700/70 p-2">
              <strong>성장 1단위당 가격</strong>
              <div>자기 역사 PER 대비 {num(inputs.valuation_reflection_pct, 1)}% → {num(parts.valuation_history, 1)}/10</div>
              <div>성장조정 PER {num(inputs.growth_adjusted_pe, 2)} · 피어 중앙 {num(inputs.peer_median_growth_adjusted_pe, 2)} · 피어 대비 {num(inputs.peer_peg_premium_pct, 1)}% → {num(parts.valuation_peer, 1)}/10</div>
            </div>
            <div className="mt-2 rounded border border-slate-700/70 p-2">
              <strong>과열 여부</strong>
              <div>합성 과열 {num(inputs.overheat_score_pct, 1)}/100 · RSI {num(inputs.rsi_14, 1)} · 5일 {num(inputs.ret_5d_pct, 1)}%</div>
              <div>52주 고점 대비 {num(inputs.high_52w_drawdown_pct, 1)}% → {num(parts.overheat, 1)}/10</div>
              <div className="text-slate-300">미래 매수자를 예측하지 않고 현재 가격의 단기 쏠림만 측정한다.</div>
            </div>
            <div className="mt-2"><strong>중기 상대 주가</strong> {num(inputs.relative_return_pct, 1)}%p → {num(parts.relative, 1)}/10</div>
            <div className="mt-1 text-slate-100">PRI = 측정 점수 합 ÷ 측정 가능 배점 {denominator} × 100 · 신뢰도는 점수에 합산하지 않는다.</div>
          </>
        ) : isV2 ? (
          <>
            <div><strong>실적 발표 초과반응</strong> {num(inputs.announcement_excess_return_pct, 1)}%p → {num(parts.event, 1)}/30 · 발표 후 1·5·20일 시장·섹터보다 더 오른 정도</div>
            <div><strong>전망·주가 괴리</strong> {num(inputs.earnings_revision_price_gap_pct, 1)}%p → {num(parts.revision, 1)}/30 · 주가가 이익 전망보다 앞선 정도</div>
            <div><strong>TTM PER·F.PER 반영</strong> {num(inputs.valuation_reflection_pct, 1)}% → {num(parts.valuation, 1)}/20 · 과거 PER 대비 현재 배수</div>
            <div><strong>중기 상대 주가</strong> {num(inputs.relative_return_pct, 1)}%p → {num(parts.relative, 1)}/20 · 3·6·12개월 섹터 대비 평균</div>
            <div className="mt-1 text-slate-100">PRI = 측정 점수 합 ÷ 측정 가능 배점 {denominator} × 100 · 신뢰도는 점수에 합산하지 않는다.</div>
          </>
        ) : (
          <>
            <div>P1 52주 신고가 대비 {num(inputs.high_52w_drawdown_pct, 1)}% → {num(parts.p1, 1)}/25</div>
            <div>P2 최초 발표일 종가 대비 {num(inputs.announcement_return_pct, 1)}% → {num(parts.p2, 1)}/25</div>
            <div>P3 현재 TTM PER의 과거 9분기 평균 대비 {num(inputs.per_vs_9q_avg_pct, 1)}% → {num(parts.p3, 1)}/20</div>
            <div>P4 발표일부터 5거래일 외국인 순매수/거래량 {num(inputs.foreign_net_ratio_5d_pct, 2)}% → {num(parts.p4, 1)}/10</div>
            <div>P5 RSI(14) {num(inputs.rsi_14, 1)} (45가 중립) → {num(parts.p5, 1)}/20</div>
            <div className="mt-1 text-slate-100">기존 PRI = 측정 점수 합 ÷ 측정 가능 배점 {denominator} × 100</div>
          </>
        )}
      </div>
    </div>
  );
}
