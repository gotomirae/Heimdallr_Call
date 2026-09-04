// PRD Ref: §9.1-3 — 주간 종가 기반 MACD(12,26,9)와 RSI(14)
import type { WeeklyPriceRow } from "./types";

export interface TechnicalPoint extends WeeklyPriceRow { macd: number | null; signal: number | null; histogram: number | null; rsi: number | null; }

function ema(values: number[], period: number): Array<number | null> {
  const out: Array<number | null> = Array(values.length).fill(null);
  if (values.length < period) return out;
  let current = values.slice(0, period).reduce((sum, value) => sum + value, 0) / period;
  out[period - 1] = current;
  const alpha = 2 / (period + 1);
  for (let i = period; i < values.length; i += 1) { current = values[i] * alpha + current * (1 - alpha); out[i] = current; }
  return out;
}

export function technicalIndicators(rows: WeeklyPriceRow[]): TechnicalPoint[] {
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
