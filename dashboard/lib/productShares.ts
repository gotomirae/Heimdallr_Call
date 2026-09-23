// PRD Ref: §9.1 — 최근 정기보고서의 제품·사업부 매출 비중
import type { DisclosureExcerptRow } from "./orderSignals";

export interface ProductShare {
  name: string;
  sharePct: number;
}

export interface ProductShareDisclosure {
  shares: ProductShare[];
  sourceLabel: string | null;
  periodLabel: string | null;
  rceptNo: string | null;
  sectionFound: boolean;
  truncated: boolean;
  statusLabel: string;
}

const GENERIC = /^(구분|품목|제품|제품명|제품구분|주요제품|사업부문|매출액|매출|금액|비중|비율|구성비|합계|총계|소계|계|내수|수출|기타|당사|자사)$/;
const TRUNCATED = /…?\s*\(이하\s*[\d,]+자\s*생략\)/;

function cellsOf(line: string): string[] {
  return line.split("|").map((cell) => cell.trim()).filter(Boolean);
}

function numberOf(cell: string): number | null {
  if (!/^-?[\d,.]+\s*%?$/.test(cell)) return null;
  const value = Number(cell.replace(/[,%\s]/g, ""));
  return Number.isFinite(value) ? value : null;
}

function explicitPercentOf(cell: string): number | null {
  const match = cell.match(/(?:^|\()\s*(-?[\d,.]+)\s*%\s*\)?$/);
  if (!match) return null;
  const value = Number(match[1].replace(/,/g, ""));
  return Number.isFinite(value) ? value : null;
}

function genericCell(cell: string): boolean {
  return GENERIC.test(cell.replace(/\s+/g, ""));
}

function nameFromCells(cells: string[], end: number, nameColumn: number | null): string | null {
  const namedCell = nameColumn != null && nameColumn < end ? cells[nameColumn] : null;
  const fallback = cells.slice(0, end).reverse().find((cell) =>
    /[가-힣A-Za-z]/.test(cell) && !genericCell(cell) && cell.length <= 60
  ) ?? null;
  if (namedCell && /[가-힣A-Za-z]/.test(namedCell) && !genericCell(namedCell)) {
    // rowspan이 텍스트로 풀리면 회사/사업부가 품목 열로 한 칸 밀린다.
    if (fallback && fallback !== namedCell && /(?:회사|법인|사업|사업부문)\)?$/.test(namedCell.replace(/\s+/g, ""))) return fallback;
    return namedCell;
  }
  return fallback;
}

function periodLabels(row: DisclosureExcerptRow): { source: string; period: string } | null {
  if (row.fiscal_year == null || row.fiscal_quarter == null) return null;
  const labels: Record<number, [string, string]> = {
    1: ["1분기보고서", "해당 사업연도 1분기 누적"],
    2: ["반기보고서", "해당 사업연도 반기 누적"],
    3: ["3분기보고서", "해당 사업연도 3분기 누적"],
    4: ["사업보고서", "해당 사업연도 연간"],
  };
  const label = labels[row.fiscal_quarter];
  return label ? { source: `${row.fiscal_year}년 ${label[0]}`, period: label[1] } : null;
}

/** 공시 표의 명시된 백분율만 읽고, 출처 보고서·누적 기간·발췌 상태를 함께 반환한다. */
export function productShareDisclosure(row: DisclosureExcerptRow | null): ProductShareDisclosure {
  const period = row ? periodLabels(row) : null;
  const base = {
    sourceLabel: period?.source ?? null,
    periodLabel: period?.period ?? null,
    rceptNo: row?.rcept_no ?? null,
  };
  const section = row?.sections?.["주요 제품 및 서비스"];
  if (typeof section !== "string") return {
    ...base, shares: [], sectionFound: false, truncated: false,
    statusLabel: row ? "제품·서비스 절이 발췌 범위에 없음" : "정기보고서 원문 수집 대기",
  };

  const found = new Map<string, number>();
  const lines = section.split(/\n+/);
  const headerDeclaresPercent = lines.slice(0, 8).some((line) => /(?:비중|비율|구성비|점유율|%)\s*\)?/.test(line));
  let nameColumn: number | null = null;
  let pendingName: string | null = null;
  for (const line of lines) {
    const cells = cellsOf(line);
    let explicitNameColumn = cells.findIndex((cell) => /^(?:품목|제품명|제품구분|주요제품)$/.test(cell.replace(/\s+/g, "")));
    if (explicitNameColumn < 0) explicitNameColumn = cells.findIndex((cell) => cell.replace(/\s+/g, "") === "사업부문");
    if (explicitNameColumn >= 0) nameColumn = explicitNameColumn;
    let percentIndex = cells.findIndex((cell) => explicitPercentOf(cell) != null);
    // `%`가 각 값에 반복되지 않아도 머리글이 `비중(%)`이면 그 열의 첫 현재기간 값을 쓴다.
    if (percentIndex < 0 && headerDeclaresPercent) {
      const amountIndex = cells.findIndex((cell) => {
        const value = numberOf(cell);
        return value != null && (cell.includes(",") || Math.abs(value) > 100);
      });
      if (amountIndex >= 0) {
        percentIndex = cells.findIndex((cell, index) => {
          const value = numberOf(cell);
          return index > amountIndex && value != null && value >= 0 && value <= 100;
        });
      }
    }
    if (percentIndex < 0) {
      const amountIndex = cells.findIndex((cell) => {
        const value = numberOf(cell);
        return value != null && (cell.includes(",") || Math.abs(value) > 100);
      });
      // 금액행과 비율행이 분리된 표는 마지막 텍스트 셀이 제품명인 경우가 많다.
      // rowspan이 풀리며 머리글 열 번호가 어긋날 수 있어 이 경로에서는 열 번호를 쓰지 않는다.
      if (amountIndex >= 0) pendingName = nameFromCells(cells, amountIndex, null);
      continue;
    }
    const sharePct = explicitPercentOf(cells[percentIndex]) ?? numberOf(cells[percentIndex]);
    if (sharePct == null || sharePct < 0 || sharePct > 100) continue;
    const amountIndex = cells.findIndex((cell) => {
      const value = numberOf(cell);
      return value != null && (cell.includes(",") || Math.abs(value) > 100);
    });
    const name = nameFromCells(cells, amountIndex >= 0 ? amountIndex : percentIndex, nameColumn) ?? pendingName;
    pendingName = null;
    if (!name || found.has(name)) continue;
    found.set(name, sharePct);
  }
  const shares = [...found.entries()]
    .map(([name, sharePct]) => ({ name, sharePct }))
    .sort((left, right) => right.sharePct - left.sharePct)
    .slice(0, 8);
  const truncated = TRUNCATED.test(section);
  return {
    ...base, shares, sectionFound: true, truncated,
    statusLabel: shares.length > 0
      ? "공시 명시 비중 확인"
      : truncated ? "발췌가 잘려 비중 원문 확인 필요" : "공시에 명시된 비중 열 미확인",
  };
}

/** 기존 소비자를 위한 간단 목록. 금액으로 비중을 추정하지 않는다. */
export function productSharesFromExcerpt(row: DisclosureExcerptRow | null): ProductShare[] {
  return productShareDisclosure(row).shares;
}
