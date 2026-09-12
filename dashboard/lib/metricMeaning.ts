// PRD Ref: §9.1-3 — 차트 전체 지표를 현재 위치에서 결정론적으로 해석한다.
import type { ChartPoint } from "./chart";
import type { TechnicalPoint } from "./technicalIndicators";

export interface MetricMeaning {
  label: string;
  value: string;
  meaning: string;
  watch: string;
  /** 지표를 실제 매수·매도 판단에 어떻게 연결할지. 단독 신호로 쓰지는 않는다. */
  action?: string;
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

export function priceMeaning(points: TechnicalPoint[], high52w?: number | null): MetricMeaning {
  const latest = points.at(-1);
  if (!latest) return { label: "네이버 일간 종가", value: "측정 불가", meaning: "실적과 가격의 시차를 판단할 수 없다.", watch: "네이버 일봉 수집 상태" };
  const closes = points.map((point) => point.close);
  const high = Math.max(...closes), low = Math.min(...closes);
  const position = high > low ? (latest.close - low) / (high - low) * 100 : null;
  const referenceHigh = high52w != null && high52w > 0 ? high52w : high;
  const drawdown = referenceHigh > 0 ? (latest.close / referenceHigh - 1) * 100 : null;
  const recent = points.slice(-21);
  const monthReturn = recent.length >= 2 ? (latest.close / recent[0].close - 1) * 100 : null;
  return {
    label: "네이버 일간 종가",
    value: `${latest.trade_date} ${latest.close.toLocaleString("ko-KR")}원${drawdown == null ? "" : ` · 52주 고점 대비 ${drawdown.toFixed(1)}%`}`,
    meaning: position == null
      ? "표시 구간 가격 범위가 없어 위치를 판단할 수 없다."
      : `${position >= 70 ? "표시 구간 상단" : position <= 30 ? "표시 구간 하단" : "표시 구간 중간"}이다. ` +
        `${monthReturn == null ? "최근 한 달 방향은 측정하지 못했다." : `최근 20거래일 수익률은 ${signed(monthReturn, "%")}다.`} ` +
        "하락 이유는 가격 모양만으로 단정하지 않고 아래 LLM의 실적·업황·수급 근거와 대조한다.",
    watch: "실적 발표 뒤 가격과 지수대비 수익률의 방향",
    action: position != null && position <= 30
      ? "하단이라는 이유만으로 매수하지 말고, 실적 가속 유지와 MACD 회복을 함께 확인해 분할 접근한다."
      : "고점에 가까울수록 추격보다 다음 실적 확인 또는 기술적 눌림을 기다린다.",
  };
}

export function macdMeaning(points: TechnicalPoint[]): MetricMeaning {
  const measured = points.filter((point) => finite(point.macd) && finite(point.signal) && finite(point.histogram));
  const latest = measured.at(-1), previous = measured.at(-2);
  if (!latest) return { label: "MACD(일간 12·26·9)", value: "측정 불가", meaning: "26거래일 이상의 일간 종가와 9일 신호선 준비가 필요하다.", watch: "일간 종가 수집 길이" };
  const expanding = previous ? Math.abs(latest.histogram!) > Math.abs(previous.histogram!) : null;
  const bullish = latest.macd! >= latest.signal!;
  return {
    label: "MACD(일간 12·26·9)",
    value: `${latest.trade_date} MACD ${latest.macd!.toFixed(1)} · Signal ${latest.signal!.toFixed(1)} · Histogram ${signed(latest.histogram!, "")}`,
    meaning: `${bullish ? "최근 12일 가격의 평균이 26일 평균보다 빠르게 올라 MACD가 신호선 위다." : "최근 12일 가격의 평균이 26일 평균보다 약해 MACD가 신호선 아래다."}${expanding == null ? "" : expanding ? " Histogram 절대값도 커져 현재 방향의 힘이 강해지고 있다." : " Histogram 절대값이 줄어 현재 방향의 힘은 약해지고 있다."}`,
    watch: "신호선 교차와 Histogram 방향 전환",
    action: bullish
      ? "실적 가속이 유지되고 RSI가 과열권이 아닐 때 눌림 후 Histogram 재확대를 매수 확인 신호로 쓴다. MACD가 다시 신호선 아래로 내려가면 비중 확대를 멈춘다."
      : "신규 매수는 MACD 상향 교차와 Histogram 양수 전환을 기다린다. 보유 중이면 지지선 이탈과 함께 하향 모멘텀이 확대될 때 축소를 검토한다.",
  };
}

export function rsiMeaning(points: TechnicalPoint[]): MetricMeaning {
  const latest = [...points].reverse().find((point) => finite(point.rsi));
  if (!latest) return { label: "RSI(일간 14)", value: "측정 불가", meaning: "15거래일 이상의 일간 종가가 필요하다.", watch: "일간 종가 수집 길이" };
  const rsi = latest.rsi!;
  return {
    label: "RSI(일간 14)",
    value: `${latest.trade_date} ${rsi.toFixed(1)}`,
    meaning: rsi >= 70 ? "최근 14거래일 상승폭이 하락폭보다 크게 누적돼 70 이상 과열권이다. 강한 추세이기도 하지만 단기 기대가 앞섰을 수 있다." : rsi <= 30 ? "최근 14거래일 하락폭이 우세해 30 이하 과매도권이다. 반등 여지는 있지만 하락 원인이 해소됐다는 뜻은 아니다." : rsi >= 45 ? "최근 14거래일 상승·하락 힘이 중립 이상이고 과열권 70 아래다." : "최근 14거래일 하락 힘이 우세하지만 30 이하의 극단적 과매도는 아니다.",
    watch: "45선 회복·이탈과 70/30 진입 여부",
    action: rsi >= 70
      ? "추격 매수는 피하고 RSI가 70 아래로 식은 뒤 MACD가 유지되는지 확인한다. 고점 갱신 실패와 RSI 하락이 겹치면 일부 이익 실현을 검토한다."
      : rsi <= 30
        ? "과매도만 보고 매수하지 말고 RSI 30 재돌파와 MACD Histogram 개선을 확인해 분할 진입한다."
        : rsi >= 45
          ? "45 위를 지키는 눌림은 추세 매수 후보지만, 실적 발표 직전에는 포지션을 나눠 이벤트 위험을 줄인다."
          : "45 회복 전에는 반등을 추세 전환으로 단정하지 않는다. 보유자는 30 진입보다 실적 훼손 여부를 먼저 확인한다.",
  };
}

export function fundamentalMetricMeanings(points: ChartPoint[]): MetricMeaning[] {
  return [
    amountMeaning(points, "revenue", "매출액"),
    amountMeaning(points, "op", "영업이익"),
    opmMeaning(points),
    yoyMeaning(points, "revenueYoy", "매출액 YoY"),
    yoyMeaning(points, "opYoy", "영업이익 YoY"),
    orderMeaning(points),
  ];
}

export function metricMeanings(points: ChartPoint[], technical: TechnicalPoint[]): MetricMeaning[] {
  return [
    ...fundamentalMetricMeanings(points),
    priceMeaning(technical),
    macdMeaning(technical),
    rsiMeaning(technical),
  ];
}
