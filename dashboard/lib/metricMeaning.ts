// PRD Ref: §9.1-3 — 차트 전체 지표를 현재 위치에서 결정론적으로 해석한다.
import type { ChartPoint } from "./chart";
import type { TechnicalPoint } from "./technicalIndicators";

export interface MetricMeaning {
  label: string;
  value: string;
  meaning: string;
  watch: string;
}

function finite(value: number | null | undefined): value is number {
  return value != null && Number.isFinite(value);
}

function signed(value: number, unit: string): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}${unit}`;
}

function latestPair(points: ChartPoint[], key: "revenue" | "op" | "opm" | "revenueYoy" | "opYoy") {
  const measured = points.filter((point) => finite(point[key]));
  return { latest: measured.at(-1) ?? null, previous: measured.at(-2) ?? null, measured };
}

function amountMeaning(points: ChartPoint[], key: "revenue" | "op", label: string): MetricMeaning {
  const { latest, previous, measured } = latestPair(points, key);
  if (!latest || !finite(latest[key])) {
    return { label, value: "측정 불가", meaning: "절대금액이 없어 사업 규모의 현재 위치를 판단할 수 없다.", watch: "다음 확정 재무 수집 여부" };
  }
  const value = latest[key]!;
  const prior = previous && finite(previous[key]) ? previous[key]! : null;
  const high = Math.max(...measured.map((point) => point[key] as number));
  // 영업이익 부호가 바뀌면 %를 만들지 않는다. 흑전·적전은 상태 변화다.
  const change = prior != null && prior !== 0 && (key !== "op" || value * prior > 0)
    ? (value / prior - 1) * 100
    : null;
  const atHigh = value >= high - Math.max(Math.abs(high) * 0.001, 0.1);
  return {
    label,
    value: `${latest.label} ${value.toLocaleString("ko-KR", { maximumFractionDigits: 0 })}억${change == null ? "" : ` · 직전 대비 ${signed(change, "%")}`}`,
    meaning: atHigh
      ? `표시된 ${measured.length}개 분기 중 최고 수준이다. 성장률이 아니라 실제 사업 규모가 올라온 상태다.`
      : `표시 구간 최고 ${high.toLocaleString("ko-KR", { maximumFractionDigits: 0 })}억의 ${(value / high * 100).toFixed(0)}% 수준이다. 성장률이 높아도 절대금액은 고점 아래일 수 있다.`,
    watch: change == null ? "다음 분기 절대금액" : change >= 0 ? "증가가 다음 분기에도 이어지는지" : "감소가 계절성인지 수요 둔화인지",
  };
}

function opmMeaning(points: ChartPoint[]): MetricMeaning {
  const { latest, previous, measured } = latestPair(points, "opm");
  if (!latest || !finite(latest.opm)) return { label: "OPM", value: "측정 불가", meaning: "본업의 이익률을 판단할 수 없다.", watch: "영업이익과 매출 동시 확보" };
  const delta = previous && finite(previous.opm) ? latest.opm - previous.opm : null;
  const high = Math.max(...measured.map((point) => point.opm as number));
  return {
    label: "OPM",
    value: `${latest.label} ${latest.opm.toFixed(1)}%${delta == null ? "" : ` · 직전 대비 ${signed(delta, "%p")}`}`,
    meaning: latest.opm >= high - 0.05
      ? "표시 구간 최고 마진이다. 매출 증가분이 실제 영업이익으로 전환되는 힘이 가장 강한 위치다."
      : `표시 구간 최고 ${high.toFixed(1)}%보다 ${(high - latest.opm).toFixed(1)}%p 낮다. 규모 성장과 수익성 회복을 따로 봐야 한다.`,
    watch: delta != null && delta > 0 ? "판가·제품믹스·고정비 효과의 지속성" : "원가 상승 또는 저마진 매출 비중 확대 여부",
  };
}

function yoyMeaning(points: ChartPoint[], key: "revenueYoy" | "opYoy", label: string): MetricMeaning {
  const { latest, previous, measured } = latestPair(points, key);
  const latestReported = [...points].reverse().find((point) => point.op != null || point.revenue != null);
  if (!latest || !finite(latest[key])) {
    const transition = key === "opYoy" ? latestReported?.opStatusLabel : null;
    return {
      label,
      value: transition ? `${latestReported?.label} ${transition}` : "측정 불가",
      meaning: transition
        ? `${transition} 구간은 전년 값의 부호가 달라 성장률 %를 계산하면 왜곡된다. 결측이 아니라 상태 변화다.`
        : "전년 같은 분기 비교값이 없어 성장 속도를 판단할 수 없다.",
      watch: "다음 동분기 비교가 가능한 시점의 절대금액",
    };
  }
  const delta = previous && finite(previous[key]) ? latest[key]! - previous[key]! : null;
  const level = latest[key]!;
  return {
    label,
    value: `${latest.label} ${signed(level, "%")}${delta == null ? "" : ` · 직전 성장률 대비 ${signed(delta, "%p")}`}`,
    meaning: delta == null
      ? "성장률 수준은 확인되지만 가속 여부를 비교할 이전 측정값이 없다."
      : delta > 0
        ? `전년 대비 성장 속도가 빨라지는 위치다. 다만 ${measured.length}개 측정값 중 낮은 기저가 있는지 절대금액과 함께 봐야 한다.`
        : delta < 0
          ? `성장 속도가 느려지는 위치다. ${level > 0 ? "성장 자체는 플러스이므로 금액 감소와 같은 뜻은 아니다." : "전년보다 절대 수준도 낮아졌을 가능성이 크다."}`
          : "전분기와 같은 성장 속도다. 가속도 둔화도 아닌 유지 구간이다.",
    watch: key === "revenueYoy" ? "물량·판가 중 무엇이 매출 속도를 바꾸는지" : "매출보다 이익 성장률이 빠른지와 일회성 비용·환입",
  };
}

function orderMeaning(points: ChartPoint[]): MetricMeaning {
  const latest = [...points].reverse().find((point) => finite(point.orderBacklog) || finite(point.newOrders));
  if (!latest) return {
    label: "수주잔고 · 신규수주",
    value: "구조화 수치 미수집",
    meaning: "0이 아니라 측정 불가다. 현재 매출 뒤의 파이프라인 지속성을 숫자로 확인할 수 없는 상태다.",
    watch: "다음 정기보고서의 동일 단위 수주잔고·신규수주",
  };
  return {
    label: "수주잔고 · 신규수주",
    value: `${latest.label} 잔고 ${finite(latest.orderBacklog) ? `${latest.orderBacklog.toFixed(0)}억` : "—"} · 신규 ${finite(latest.newOrders) ? `${latest.newOrders.toFixed(0)}억` : "—"}`,
    meaning: "신규수주는 새로 들어오는 속도, 수주잔고는 앞으로 매출로 전환될 일감의 총량이다. 둘이 함께 늘어야 성장 지속성이 강하다.",
    watch: "같은 단위·범위로 다음 분기와 비교 가능한지",
  };
}

function priceMeaning(points: TechnicalPoint[]): MetricMeaning {
  const latest = points.at(-1);
  if (!latest) return { label: "실제 주간 종가", value: "측정 불가", meaning: "실적과 가격의 시차를 판단할 수 없다.", watch: "네이버 일봉 수집 상태" };
  const closes = points.map((point) => point.close);
  const high = Math.max(...closes), low = Math.min(...closes);
  const position = high > low ? (latest.close - low) / (high - low) * 100 : null;
  return {
    label: "실제 주간 종가",
    value: `${latest.trade_date} ${latest.close.toLocaleString("ko-KR")}원${position == null ? "" : ` · 표시 구간 ${position.toFixed(0)}% 위치`}`,
    meaning: position == null ? "표시 구간 가격 범위가 없어 위치를 판단할 수 없다." : position >= 70 ? "표시 구간 상단이다. 좋은 실적이 이미 가격에 반영됐을 가능성을 함께 점검해야 한다." : position <= 30 ? "표시 구간 하단이다. 미반영 기회일 수도 있지만 시장이 본 리스크가 무엇인지 확인해야 한다." : "표시 구간 중간이다. 가격만으로 과열·침체를 단정하기 어렵다.",
    watch: "실적 발표 뒤 가격과 지수대비 수익률의 방향",
  };
}

function macdMeaning(points: TechnicalPoint[]): MetricMeaning {
  const measured = points.filter((point) => finite(point.macd) && finite(point.signal) && finite(point.histogram));
  const latest = measured.at(-1), previous = measured.at(-2);
  if (!latest) return { label: "MACD(주봉 12·26·9)", value: "측정 불가", meaning: "26주 이상의 주간 종가와 9주 신호선 준비가 필요하다.", watch: "주간 종가 수집 길이" };
  const expanding = previous ? Math.abs(latest.histogram!) > Math.abs(previous.histogram!) : null;
  const bullish = latest.macd! >= latest.signal!;
  return {
    label: "MACD(주봉 12·26·9)",
    value: `${latest.trade_date} MACD ${latest.macd!.toFixed(1)} · Signal ${latest.signal!.toFixed(1)} · Histogram ${signed(latest.histogram!, "")}`,
    meaning: `${bullish ? "MACD가 신호선 위라 주간 추세 모멘텀은 상승 우위다." : "MACD가 신호선 아래라 주간 추세 모멘텀은 하락 우위다."}${expanding == null ? "" : expanding ? " 두 선의 간격이 커져 현재 방향의 힘이 강해지고 있다." : " 두 선의 간격이 줄어 현재 방향의 힘은 약해지고 있다."}`,
    watch: "신호선 교차와 Histogram 방향 전환",
  };
}

function rsiMeaning(points: TechnicalPoint[]): MetricMeaning {
  const latest = [...points].reverse().find((point) => finite(point.rsi));
  if (!latest) return { label: "RSI(주봉 14)", value: "측정 불가", meaning: "15주 이상의 주간 종가가 필요하다.", watch: "주간 종가 수집 길이" };
  const rsi = latest.rsi!;
  return {
    label: "RSI(주봉 14)",
    value: `${latest.trade_date} ${rsi.toFixed(1)}`,
    meaning: rsi >= 70 ? "70 이상 과열권이다. 강한 추세일 수 있지만 단기 기대가 과도한지 점검할 위치다." : rsi <= 30 ? "30 이하 과매도권이다. 반등 여지는 있지만 하락 원인이 해소됐다는 뜻은 아니다." : rsi >= 45 ? "중립선 45 위, 과열권 70 아래다. 상승 힘은 남아 있지만 과열로 단정할 단계는 아니다." : "중립선 45 아래, 과매도권 30 위다. 하락 힘이 우세하지만 극단적 침체는 아니다.",
    watch: "45선 회복·이탈과 70/30 진입 여부",
  };
}

export function metricMeanings(points: ChartPoint[], technical: TechnicalPoint[]): MetricMeaning[] {
  return [
    amountMeaning(points, "revenue", "매출액"),
    amountMeaning(points, "op", "영업이익"),
    opmMeaning(points),
    yoyMeaning(points, "revenueYoy", "매출액 YoY"),
    yoyMeaning(points, "opYoy", "영업이익 YoY"),
    orderMeaning(points),
    priceMeaning(technical),
    macdMeaning(technical),
    rsiMeaning(technical),
  ];
}
