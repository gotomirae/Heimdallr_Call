// PRD Ref: §9.1 · §8 — 밸류에이션
//
// ★ 파이썬 쪽 짝은 `src/notify/run.py`의 `ttm_net_income` / forward PER 블록이다.
//   **같은 종목에서 텔레그램과 화면이 다른 배수를 말하면 신뢰가 통째로 깨진다** —
//   규칙을 바꿀 때는 반드시 양쪽을 같이 고친다.
//
// ★ 후행 PER(증권사 화면의 PER)은 **표시하지 않는다.** 과거 12개월 EPS 기준이라
//   실적 급가속 구간에서 크게 과대평가되고, 이 시스템이 겨냥하는 구간이 정확히
//   거기다. 나란히 두면 큰 쪽에 눈이 가서 "이미 비싸다"는 정반대 결론이 나온다.
import type { ConsensusRow, FundamentalRow } from "./types";
import { qIndex } from "./format";

/**
 * 그 분기까지의 4분기 누적 순이익. **최근 4분기 PER의 분모다.**
 *
 * ★ 4개 분기가 다 모이지 않으면 연율화하지 않고 null을 준다.
 *   3분기치를 ×4/3 하면 계절성이 강한 한국 기업에서 조용히 틀린다.
 */
export function ttmNetIncome(
  funds: FundamentalRow[],
  year: number,
  quarter: number
): number | null {
  const index = qIndex(year, quarter);
  const byIndex = new Map(funds.map((f) => [qIndex(f.fiscal_year, f.fiscal_quarter), f]));
  const values = [0, 1, 2, 3].map((o) => byIndex.get(index - o)?.np ?? null);
  if (values.some((v) => v == null)) return null;
  return values.reduce((a, b) => (a as number) + (b as number), 0) as number;
}

/** 시가총액 ÷ 최근 4분기 순이익. 이익이 0 이하면 배수가 의미를 잃으므로 null. */
export function trailing4qPer(
  marketCapKrw: number | null | undefined,
  ttmNp: number | null
): number | null {
  if (!marketCapKrw || ttmNp == null || ttmNp <= 0) return null;
  return marketCapKrw / ttmNp;
}

export interface ForwardPer {
  per: number | null;
  /** 무엇을 근거로 만든 숫자인지. 추정 위의 추정이라 반드시 화면에 밝힌다. */
  basis: string | null;
}

/**
 * 향후 4개 분기 추정 순이익 기준 선행 PER.
 *
 * 재료는 **연간 컨센서스**(`fiscal_quarter = 0`)다. 분기 컨센은 한 분기뿐이라
 * '향후 4분기'를 만들 수 없다.
 *
 * 계산:
 *   1) 그 회계연도에서 **이미 발표된 분기 순이익**을 연간 추정에서 뺀다 → 남은 분기 추정
 *   2) 남은 분기가 4개에 모자라면 **연간 추정의 분기 평균**으로 이어 붙인다
 *      (다음 해 추정치는 수집하지 않기 때문이다 — 이건 추정 위의 추정이라 basis에 밝힌다)
 *
 * ★ 컨센서스가 없으면 **만들어내지 않는다.** null이다.
 */
export function forwardPer(
  annual: ConsensusRow | null,
  funds: FundamentalRow[],
  marketCapKrw: number | null | undefined
): ForwardPer {
  const annualNp = annual?.np_est ?? null;
  if (!annual || annualNp == null || annualNp <= 0 || !marketCapKrw) {
    return { per: null, basis: null };
  }
  const fy = annual.fiscal_year;
  const byIndex = new Map(funds.map((f) => [qIndex(f.fiscal_year, f.fiscal_quarter), f]));
  const reported = [1, 2, 3, 4].map((q) => byIndex.get(qIndex(fy, q))?.np ?? null);
  const done = reported.filter((v): v is number => v != null);
  const remainingQuarters = 4 - done.length;

  if (remainingQuarters <= 0) {
    // 그 해가 다 발표됐으면 연간 추정 자체가 '다음 4분기'다.
    return { per: marketCapKrw / annualNp, basis: `${fy}년 컨센 기준` };
  }
  const remainingNp = annualNp - done.reduce((a, b) => a + b, 0);
  const perQuarter = remainingNp / remainingQuarters;
  const next4 = remainingNp + perQuarter * (4 - remainingQuarters);
  return {
    per: next4 > 0 ? marketCapKrw / next4 : null,
    basis: `${fy}년 컨센 ${Math.round(annualNp / 1e8).toLocaleString("ko-KR")}억 기준`,
  };
}
