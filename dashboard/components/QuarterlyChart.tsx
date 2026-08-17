"use client";
// PRD Ref: §9.1-3 — 8분기 이중축 차트.
// ★ 이 화면의 주인공은 **매출 YoY 성장률 라인**이다. 가속이 눈으로 보여야 한다.
//   막대(매출·영업이익)는 배경이고, 성장률 라인을 시각적으로 강조한다. TTM은 점선.
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartPoint } from "@/lib/chart";
import { DASH } from "@/lib/format";

function fmt(value: unknown, unit: string): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return DASH;
  return `${value.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}${unit}`;
}

export default function QuarterlyChart({ points }: { points: ChartPoint[] }) {
  if (points.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-slate-500">
        분기 재무가 없다 — 수집되지 않았거나 상장 직후일 수 있다.
      </p>
    );
  }

  return (
    <div className="h-80 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={points} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
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
          <Tooltip
            contentStyle={{
              backgroundColor: "#0f172a",
              border: "1px solid #334155",
              borderRadius: 6,
              fontSize: 12,
            }}
            formatter={(value, name) =>
              name === "매출 YoY 성장률"
                ? [fmt(value, "%"), name]
                : [fmt(value, "억"), name]
            }
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />

          {/* 배경 — 규모감만 준다.
              ★ isAnimationActive={false}: 진입 애니메이션은 rAF가 돌지 않는 환경
                (백그라운드 탭·비표시 패널)에서 **길이 0인 채로 멈춰 차트가 빈 화면이 된다.**
                실측으로 겪었다 — 데이터 대시보드에 애니메이션은 얻는 게 없다. */}
          <Bar yAxisId="amount" dataKey="revenue" name="매출" fill="#1e40af" barSize={22}
               isAnimationActive={false} />
          <Bar yAxisId="amount" dataKey="op" name="영업이익" fill="#0e7490" barSize={22}
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

          {/* ★ 주인공 — 가장 굵고, 가장 밝고, 점이 크다 */}
          <Line
            yAxisId="growth"
            type="monotone"
            dataKey="revenueYoy"
            name="매출 YoY 성장률"
            stroke="#f59e0b"
            strokeWidth={3.5}
            dot={{ r: 5, fill: "#f59e0b", strokeWidth: 0 }}
            activeDot={{ r: 7 }}
            isAnimationActive={false}
            // 부호 전환 구간(null)은 이어 그리지 않는다 — 없는 값을 만들어내면 안 된다.
            connectNulls={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
