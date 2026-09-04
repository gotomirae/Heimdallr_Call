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
import { SERIES_COLOR, type ChartPoint } from "@/lib/chart";
import { DASH } from "@/lib/format";

const REVENUE_YOY = "매출 YoY";
const OP_YOY = "영업이익 YoY";
const OPM = "OPM";

// ★ 색은 `lib/chart.ts`가 단일 출처다. **여기서 export하면 안 된다** —
//   이 파일은 "use client"라, 서버 컴포넌트(상세 페이지 설명 글)가 여기서
//   비컴포넌트 export를 가져오면 빌드·tsc를 통과하고 **런타임에 500**이 난다(T41).
const { OP_COLOR, OP_LABEL, OPM_COLOR, REVENUE_COLOR, REVENUE_LABEL } = SERIES_COLOR;

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
      <p className="py-8 text-center text-sm text-slate-300">
        분기 재무가 없다 — 수집되지 않았거나 상장 직후일 수 있다.
      </p>
    );
  }

  return (
    <div className="h-96 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={points} margin={{ top: 24, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="#1e293b" vertical={false} />
          {/* ★ 진행 중 분기(실적 미발표)는 라벨에 표시를 남긴다 — 막대가 없는 게
              결측인지 아직 발표 전인지 구분되지 않으면 오독한다. */}
          <XAxis
            dataKey="label"
            stroke="#cbd5e1"
            fontSize={12}
            tickLine={false}
            tickFormatter={(v, i) => (points[i]?.isCurrentQuarter ? `${v}*` : String(v))}
          />
          <YAxis
            yAxisId="amount"
            stroke={SERIES_COLOR.AXIS_COLOR}
            fontSize={11}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => `${Math.round(Number(v)).toLocaleString("ko-KR")}`}
            label={{ value: "억원", position: "insideTopLeft", fill: "#94a3b8", fontSize: 11 }}
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
          {/* OPM은 성장률과 단위는 같아도 범위가 전혀 다르다. 영업이익 YoY가
              수백~수천%인 턴어라운드에서 같은 축을 쓰면 OPM이 평평하게 눌린다. */}
          <YAxis yAxisId="opm" hide domain={["auto", "auto"]} />
          <Tooltip
            contentStyle={{
              backgroundColor: "#0f172a",
              border: "1px solid #334155",
              borderRadius: 6,
              fontSize: 12,
            }}
            formatter={(value, name) => {
              if (name === REVENUE_YOY || name === OP_YOY || name === OPM) return [fmt(value, "%"), name];
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
            stroke={SERIES_COLOR.TTM_COLOR}
            strokeWidth={1.5}
            strokeDasharray="4 3"
            dot={false}
            isAnimationActive={false}
            connectNulls={false}
          />
          <Line
            yAxisId="opm"
            type="monotone"
            dataKey="opm"
            name={OPM}
            stroke={OPM_COLOR}
            strokeWidth={2}
            strokeDasharray="5 3"
            dot={{ r: 3, fill: OPM_COLOR, strokeWidth: 0 }}
            isAnimationActive={false}
            connectNulls={false}
          />

          {/* 매출 성장률 — **녹색 실선** */}
          <Line
            yAxisId="growth"
            type="monotone"
            dataKey="revenueYoy"
            name={REVENUE_YOY}
            stroke={REVENUE_COLOR}
            strokeWidth={2.5}
            dot={{ r: 4, fill: REVENUE_COLOR, strokeWidth: 0 }}
            activeDot={{ r: 6 }}
            isAnimationActive={false}
            // 부호 전환 구간(null)은 이어 그리지 않는다 — 없는 값을 만들어내면 안 된다.
            connectNulls={false}
          >
            <LabelList dataKey="revenueYoy" content={(p) => growthLabel({ ...p, fill: REVENUE_LABEL })} />
          </Line>

          {/* ★★ 주인공 — 영업이익 성장률. **노란 실선**. 가장 굵고 점이 크다. */}
          <Line
            yAxisId="growth"
            type="monotone"
            dataKey="opYoy"
            name={OP_YOY}
            stroke={OP_COLOR}
            strokeWidth={3.5}
            dot={{ r: 5, fill: OP_COLOR, strokeWidth: 0 }}
            activeDot={{ r: 7 }}
            isAnimationActive={false}
            connectNulls={false}
          >
            <LabelList dataKey="opYoy" content={(p) => growthLabel({ ...p, fill: OP_LABEL })} />
          </Line>
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
