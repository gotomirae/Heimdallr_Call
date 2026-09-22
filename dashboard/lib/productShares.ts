// PRD Ref: §9.1 — 최근 정기보고서의 제품·사업부 매출 비중
import type { DisclosureExcerptRow } from "./orderSignals";

export interface ProductShare {
  name: string;
  sharePct: number;
}

const GENERIC = /^(구분|품목|제품|사업부문|매출액|비율|합계|계|내수|수출|기타)$/;

/** 공시 표의 명시된 백분율만 읽는다. 금액으로 비중을 추정하지 않는다. */
export function productSharesFromExcerpt(row: DisclosureExcerptRow | null): ProductShare[] {
  const section = row?.sections?.["주요 제품 및 서비스"];
  if (typeof section !== "string") return [];
  const found = new Map<string, number>();
  for (const line of section.split(/\n+/)) {
    const cells = line.split("|").map((cell) => cell.trim()).filter(Boolean);
    const percentIndex = cells.findIndex((cell) => /^-?[\d,.]+\s*%$/.test(cell));
    if (percentIndex < 0) continue;
    const sharePct = Number(cells[percentIndex].replace(/[,%\s]/g, ""));
    if (!Number.isFinite(sharePct) || sharePct < 0 || sharePct > 100) continue;
    const name = cells.slice(0, percentIndex).reverse().find((cell) =>
      /[가-힣A-Za-z]/.test(cell) && !GENERIC.test(cell) && cell.length <= 60
    );
    if (!name || found.has(name)) continue;
    found.set(name, sharePct);
  }
  return [...found.entries()]
    .map(([name, sharePct]) => ({ name, sharePct }))
    .sort((left, right) => right.sharePct - left.sharePct)
    .slice(0, 8);
}
