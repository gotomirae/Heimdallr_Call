// PRD Ref: §9.1-3 — 일간 종가 기반 MACD(12,26,9)와 RSI(14)
import type { DailyPriceRow, WeeklyPriceRow } from "./types";

export interface TechnicalPoint extends DailyPriceRow { macd: number | null; signal: number | null; histogram: number | null; rsi: number | null; }

function isoWeekKey(value: string): string {
  const day = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  const weekday = day.getUTCDay() || 7;
  day.setUTCDate(day.getUTCDate() + 4 - weekday);
  const yearStart = new Date(Date.UTC(day.getUTCFullYear(), 0, 1));
  const week = Math.ceil((((day.getTime() - yearStart.getTime()) / 86_400_000) + 1) / 7);
  return `${day.getUTCFullYear()}-${String(week).padStart(2, "0")}`;
}

/** 반복 수집 중 같은 주의 목·금 종가가 함께 남아도 마지막 거래일 한 점만 쓴다. */
export function normalizeWeeklyRows(rows: WeeklyPriceRow[]): WeeklyPriceRow[] {
  const latest = new Map<string, WeeklyPriceRow>();
  for (const row of [...rows].sort((left, right) => left.trade_date.localeCompare(right.trade_date))) {
    if (!Number.isFinite(row.close) || row.close <= 0) continue;
    latest.set(isoWeekKey(row.trade_date), row);
  }
  return [...latest.values()].sort((left, right) => left.trade_date.localeCompare(right.trade_date));
}

/** 일봉 중복·비정상값 제거. 일간 지표에서는 주별 접기를 절대 하지 않는다. */
export function normalizeDailyRows(rows: DailyPriceRow[]): DailyPriceRow[] {
  const latest = new Map<string, DailyPriceRow>();
  for (const row of rows) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(row.trade_date) || !Number.isFinite(row.close) || row.close <= 0) continue;
    latest.set(row.trade_date, row);
  }
  return [...latest.values()].sort((left, right) => left.trade_date.localeCompare(right.trade_date));
}

function ema(values: number[], period: number): Array<number | null> {
  const out: Array<number | null> = Array(values.length).fill(null);
  if (values.length < period) return out;
  let current = values.slice(0, period).reduce((sum, value) => sum + value, 0) / period;
  out[period - 1] = current;
  const alpha = 2 / (period + 1);
  for (let i = period; i < values.length; i += 1) { current = values[i] * alpha + current * (1 - alpha); out[i] = current; }
  return out;
}

export function technicalIndicators(rows: DailyPriceRow[]): TechnicalPoint[] {
  const prices = rows.map((row) => row.close);
  const fast = ema(prices, 12), slow = ema(prices, 26);
  const macd = prices.map((_, i) => fast[i] != null && slow[i] != null ? fast[i]! - slow[i]! : null);
  const measuredMacd = macd.filter((v): v is number => v != null), signalMeasured = ema(measuredMacd, 9);
  let signalIndex = 0;
  const signal = macd.map((value) => value == null ? null : signalMeasured[signalIndex++]);
  const rsi: Array<number | null> = Array(prices.length).fill(null);
  if (prices.length > 14) {
    let gains = 0, losses = 0;
    for (let i = 1; i <= 14; i += 1) { const delta = prices[i] - prices[i - 1]; gains += Math.max(delta, 0); losses += Math.max(-delta, 0); }
    let avgGain = gains / 14, avgLoss = losses / 14;
    const value = () => avgLoss === 0 ? (avgGain === 0 ? 50 : 100) : 100 - 100 / (1 + avgGain / avgLoss);
    rsi[14] = value();
    for (let i = 15; i < prices.length; i += 1) { const delta = prices[i] - prices[i - 1]; avgGain = (avgGain * 13 + Math.max(delta, 0)) / 14; avgLoss = (avgLoss * 13 + Math.max(-delta, 0)) / 14; rsi[i] = value(); }
  }
  return rows.map((row, i) => ({ ...row, macd: macd[i], signal: signal[i], histogram: macd[i] != null && signal[i] != null ? macd[i]! - signal[i]! : null, rsi: rsi[i] }));
}
