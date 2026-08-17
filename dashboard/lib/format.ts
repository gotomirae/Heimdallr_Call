// PRD Ref: §9 · traps.md T11 (단위를 못 읽으면 추측해서 곱하지 않는다)

/** 결측은 반드시 '—'로 보인다. 0으로 채우면 "측정했는데 0"과 구분되지 않는다. */
export const DASH = "—";

export function eok(value: number | null | undefined): string {
  if (value == null) return DASH;
  return `${(value / 1e8).toLocaleString("ko-KR", { maximumFractionDigits: 0 })}억`;
}

export function jo(value: number | null | undefined): string {
  if (value == null) return DASH;
  return `${(value / 1e12).toFixed(1)}조`;
}

/** 시총은 규모에 따라 조/억을 바꿔 읽는다. */
export function marketCap(value: number | null | undefined): string {
  if (value == null) return DASH;
  return value >= 1e12 ? jo(value) : eok(value);
}

export function pct(
  value: number | null | undefined,
  digits = 1,
  unit = "%"
): string {
  if (value == null) return DASH;
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}${unit}`;
}

export function num(value: number | null | undefined, digits = 0): string {
  if (value == null) return DASH;
  return value.toLocaleString("ko-KR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function quarterLabel(year: number, quarter: number): string {
  return `${year}.${quarter}Q`;
}

/** 분기 인덱스 — 연도 경계를 넘어 비교하려면 반드시 이걸 쓴다. */
export function qIndex(year: number, quarter: number): number {
  return year * 4 + (quarter - 1);
}

/**
 * 부호가 바뀌는 구간은 %가 아니라 라벨이다(T25).
 * `op_status_label`이 있으면 그것을 우선 보여준다.
 */
export function growthOrLabel(
  value: number | null | undefined,
  label: string | null | undefined
): string {
  if (label) return label;
  return pct(value);
}
