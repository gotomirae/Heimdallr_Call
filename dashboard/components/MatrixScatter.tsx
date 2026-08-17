"use client";
// PRD Ref: §9 /matrix — 2축 산점도. X=스코어, Y=주가반영도. ADR 5.
// ★ 스코어와 PRI를 한 숫자로 뭉개지 않는 이유가 이 화면이다.
//   같은 스코어라도 이미 오른 종목과 안 오른 종목은 전혀 다른 투자다.
import { useRouter } from "next/navigation";
import {
  CartesianGrid,
  Cell,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { GRADE_COLOR, type Grade } from "@/lib/types";

export interface MatrixPoint {
  code: string;
  name: string;
  score: number;
  pri: number;
  grade: Grade | null;
}

// constants.py의 SCORE_HIGH / SCORE_MID / PRI_LOW / PRI_HIGH와 같아야 한다.
const SCORE_HIGH = 75;
const SCORE_MID = 60;
const PRI_LOW = 40;
const PRI_HIGH = 65;

export default function MatrixScatter({ points }: { points: MatrixPoint[] }) {
  const router = useRouter();

  return (
    <div className="h-[540px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 16, right: 24, bottom: 24, left: 8 }}>
          <CartesianGrid stroke="#1e293b" />
          <XAxis
            type="number" dataKey="score" name="스코어" domain={[0, 100]}
            stroke="#cbd5e1" fontSize={12}
            label={{ value: "스코어 (펀더멘털 강도) →", position: "insideBottom", offset: -12, fill: "#cbd5e1", fontSize: 12 }}
          />
          <YAxis
            type="number" dataKey="pri" name="주가반영도" domain={[0, 100]}
            stroke="#cbd5e1" fontSize={12}
            label={{ value: "← 주가반영도 (낮을수록 미반영)", angle: -90, position: "insideLeft", fill: "#cbd5e1", fontSize: 12 }}
          />
          <ZAxis range={[60, 60]} />
          {/* 사분면 색상 — 목표 구간은 왼쪽 아래가 아니라 **오른쪽 아래**(고스코어·미반영)다.
              ★ Recharts 3.x는 ReferenceArea를 `rect`가 아니라 **`path`로 렌더**한다.
                `.recharts-reference-area rect`로 확인하면 0개로 나와 '안 그려졌다'고 오진한다.
                실제 확인은 `.recharts-reference-area-rect`(태그 무관)로 하고 getBBox를 본다.
              ★ 사분면 **라벨은 SVG 안에 두지 않는다.** `label` prop도 `<Label>` 자식도
                이 버전에서는 렌더되지 않았다(실측 text 0개). 아래 HTML 범례로 뺐다 —
                렌더가 보장되고, 화면 폭이 좁을 때 겹치지도 않는다. */}
          <ReferenceArea
            ifOverflow="visible"
            x1={SCORE_HIGH} x2={100} y1={0} y2={PRI_LOW}
            fill="#f59e0b" fillOpacity={0.09}
          />
          <ReferenceArea
            ifOverflow="visible"
            x1={SCORE_HIGH} x2={100} y1={PRI_HIGH} y2={100}
            fill="#6366f1" fillOpacity={0.07}
          />
          <ReferenceArea
            ifOverflow="visible"
            x1={0} x2={SCORE_MID} y1={PRI_HIGH} y2={100}
            fill="#ef4444" fillOpacity={0.07}
          />

          <ReferenceLine x={SCORE_HIGH} stroke="#334155" strokeDasharray="3 3" />
          <ReferenceLine x={SCORE_MID} stroke="#334155" strokeDasharray="3 3" />
          <ReferenceLine y={PRI_LOW} stroke="#334155" strokeDasharray="3 3" />
          <ReferenceLine y={PRI_HIGH} stroke="#334155" strokeDasharray="3 3" />

          <Tooltip
            cursor={{ strokeDasharray: "3 3" }}
            contentStyle={{
              backgroundColor: "#0f172a", border: "1px solid #334155",
              borderRadius: 6, fontSize: 12,
            }}
            content={({ payload }) => {
              const p = payload?.[0]?.payload as MatrixPoint | undefined;
              if (!p) return null;
              return (
                <div className="rounded border border-slate-700 bg-slate-900 px-3 py-2 text-xs">
                  <div className="font-semibold text-slate-100">
                    {p.grade ?? "·"} {p.name} <span className="text-slate-300">{p.code}</span>
                  </div>
                  <div className="text-slate-200">
                    스코어 {p.score.toFixed(1)} · 반영도 {p.pri.toFixed(1)}
                  </div>
                  <div className="mt-1 text-slate-300">클릭하면 상세로 이동</div>
                </div>
              );
            }}
          />

          <Scatter
            data={points}
            onClick={(p: unknown) => {
              const point = p as { code?: string } | undefined;
              if (point?.code) router.push(`/stock/${point.code}`);
            }}
            className="cursor-pointer"
            isAnimationActive={false}
          >
            {points.map((p) => (
              <Cell
                key={p.code}
                fill={p.grade ? GRADE_COLOR[p.grade] : "#94a3b8"}
                fillOpacity={p.grade === "★" || p.grade === "○" ? 0.95 : 0.45}
              />
            ))}
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
