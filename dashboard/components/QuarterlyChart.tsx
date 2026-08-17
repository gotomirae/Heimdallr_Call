"use client";
// PRD Ref: §9.1-3 — 9분기 실적 추이.
//
// ★ 이 화면의 주인공은 **영업이익 YoY 성장률 라인**이다(사용자 지정).
//   매출 YoY가 그 다음이고, 막대(매출·영업이익 금액)는 규모감만 주는 배경이다.
// ★ 성장률은 **숫자를 라인 위에 직접 찍는다.** 오른쪽 축만 있으면 눈이 축과
//   점 사이를 왕복해야 해서 "몇 %에서 몇 %로 갔는지"가 안 읽힌다 — 가속을
//   보여주는 게 이 차트의 목적이므로 값이 보여야 한다.
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  LabelList,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartPoint } from "@/lib/chart";
import { DASH } from "@/lib/format";

const REVENUE_YOY = "매출 YoY";
const OP_YOY = "영업이익 YoY";
const CLOSE = "주가";

function fmt(value: unknown, unit: string): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return DASH;
  return `${value.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}${unit}`;
}

/** 성장률 라인에 붙는 값 라벨. 결측은 **찍지 않는다** — 0으로 보이면 안 된다.
 *
 *  ★ recharts의 LabelList content props는 타입이 매우 넓다(`RenderableText` 등).
 *    좁은 타입으로 받으면 tsc가 막으므로 unknown으로 받아 여기서 좁힌다.
 */
function growthLabel(props: Record<string, unknown> & { fill: string }) {
  const { x, y, value, fill } = props;
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return (
    <text
      x={Number(x)}
      y={Number(y) - 9}
      fill={fill}
      fontSize={11}
      fontWeight={600}
      textAnchor="middle"
    >
      {`${value >= 0 ? "+" : ""}${value.toFixed(0)}%`}
    </text>
  );
}

export default function QuarterlyChart({ points }: { points: ChartPoint[] }) {
  if (points.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-slate-500">
        분기 재무가 없다 — 수집되지 않았거나 상장 직후일 수 있다.
      </p>
    );
  }

  const hasPrice = points.some((p) => p.close != null);

  return (
    <div className="h-96 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={points} margin={{ top: 24, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#1e293b" vertical={false} />
          <XAxis dataKey="label" stroke="#64748b" fontSize={12} tickLine={false} />
          <YAxis
            yAxisId="amount"
            stroke="#475569"
            fontSize={11}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => `${Math.round(Number(v)).toLocaleString("ko-KR")}`}
            label={{ value: "억원", position: "insideTopLeft", fill: "#475569", fontSize: 11 }}
          />
          <YAxis
            yAxisId="growth"
            orientation="right"
            stroke="#f59e0b"
            fontSize={11}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => `${Number(v).toFixed(0)}%`}
          />
          {/* 주가는 세 번째 축이다. 축을 숨기고 라인만 얹는다 —
              축을 셋 다 그리면 눈이 어디를 봐야 할지 잃는다. */}
          {hasPrice && <YAxis yAxisId="price" orientation="right" hide domain={["auto", "auto"]} />}
          <Tooltip
            contentStyle={{
              backgroundColor: "#0f172a",
              border: "1px solid #334155",
              borderRadius: 6,
              fontSize: 12,
            }}
            formatter={(value, name) => {
              if (name === REVENUE_YOY || name === OP_YOY) return [fmt(value, "%"), name];
              if (name === CLOSE) return [fmt(value, "원"), name];
              return [fmt(value, "억"), name];
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />

          {/* 배경 — 규모감만 준다.
              ★ isAnimationActive={false}: 진입 애니메이션은 rAF가 돌지 않는 환경
                (백그라운드 탭·비표시 패널)에서 **길이 0인 채로 멈춰 차트가 빈 화면이 된다.**
                실측으로 겪었다 — 데이터 대시보드에 애니메이션은 얻는 게 없다(T42). */}
          <Bar yAxisId="amount" dataKey="revenue" name="매출" fill="#1e3a8a" barSize={18}
               isAnimationActive={false} />
          <Bar yAxisId="amount" dataKey="op" name="영업이익" fill="#0e7490" barSize={18}
               isAnimationActive={false} />
          <Line
            yAxisId="amount"
            type="monotone"
            dataKey="ttmRevenue"
            name="TTM 매출"
            stroke="#94a3b8"
            strokeWidth={1.5}
            strokeDasharray="4 3"
            dot={false}
            isAnimationActive={false}
            connectNulls={false}
          />
          {hasPrice && (
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="close"
              name={CLOSE}
              stroke="#a78bfa"
              strokeWidth={1.5}
              strokeDasharray="2 3"
              dot={{ r: 2, fill: "#a78bfa", strokeWidth: 0 }}
              isAnimationActive={false}
              connectNulls={false}
            />
          )}

          {/* 매출 성장률 — 두 번째로 중요하다 */}
          <Line
            yAxisId="growth"
            type="monotone"
            dataKey="revenueYoy"
            name={REVENUE_YOY}
            stroke="#f59e0b"
            strokeWidth={2.5}
            dot={{ r: 4, fill: "#f59e0b", strokeWidth: 0 }}
            activeDot={{ r: 6 }}
            isAnimationActive={false}
            // 부호 전환 구간(null)은 이어 그리지 않는다 — 없는 값을 만들어내면 안 된다.
            connectNulls={false}
          >
            <LabelList dataKey="revenueYoy" content={(p) => growthLabel({ ...p, fill: "#fbbf24" })} />
          </Line>

          {/* ★★ 주인공 — 가장 굵고, 가장 밝고, 점이 크다 */}
          <Line
            yAxisId="growth"
            type="monotone"
            dataKey="opYoy"
            name={OP_YOY}
            stroke="#34d399"
            strokeWidth={3.5}
            dot={{ r: 5, fill: "#34d399", strokeWidth: 0 }}
            activeDot={{ r: 7 }}
            isAnimationActive={false}
            connectNulls={false}
          >
            <LabelList dataKey="opYoy" content={(p) => growthLabel({ ...p, fill: "#6ee7b7" })} />
          </Line>
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
