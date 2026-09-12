// PRD Ref: §9 — 발굴 목록 전송 계약
// 반복되는 객체 키를 1,100여 행마다 보내지 않도록 wire에서는 고정 순서 tuple을 쓴다.
import { HORIZONS } from "./outcome";
import type { GrowthCategory } from "./growthCategory";
import type { Grade } from "./types";

export interface DiscoveryRow {
  code: string;
  name: string;
  board: string | null;
  sector: string;
  sectorProcess: "전" | "후" | null;
  sectorTheme: string;
  sectorBasis: "주요제품" | "ETF 유사 테마" | "미분류";
  industry: string | null;
  marketCap: number | null;
  quarter: string;
  quarterIndex: number;
  gatePassed: boolean | null;
  turnaround: boolean | null;
  category: GrowthCategory;
  grade: Grade | null;
  score: number | null;
  pri: number | null;
  hasConsensus: boolean | null;
  baseEffect: boolean | null;
  failReasons: string[];
  revenueYoy: number | null;
  revenueQoq: number | null;
  opYoy: number | null;
  opQoq: number | null;
  opStatusLabel: string | null;
  opmYoyDelta: number | null;
  per4q: number | null;
  forwardPer: number | null;
  roe: number | null;
  forwardRoe: number | null;
  ret5d: number | null;
  excess: Partial<Record<(typeof HORIZONS)[number], number | null>>;
}

export type DiscoveryRowWire = [
  string, string, string | null, string, "전" | "후" | null, string,
  "주요제품" | "ETF 유사 테마" | "미분류", string | null, number | null,
  string, number, boolean | null, boolean | null, GrowthCategory, Grade | null,
  number | null, number | null, boolean | null, boolean | null, string[],
  number | null, number | null, number | null, number | null, string | null,
  number | null, number | null, number | null, number | null, number | null,
  number | null, number | null, number | null, number | null, number | null,
  number | null,
];

export function packDiscoveryRow(row: DiscoveryRow): DiscoveryRowWire {
  return [
    row.code, row.name, row.board, row.sector, row.sectorProcess, row.sectorTheme,
    row.sectorBasis, row.industry, row.marketCap, row.quarter, row.quarterIndex,
    row.gatePassed, row.turnaround, row.category, row.grade, row.score, row.pri,
    row.hasConsensus, row.baseEffect, row.failReasons, row.revenueYoy, row.revenueQoq,
    row.opYoy, row.opQoq, row.opStatusLabel, row.opmYoyDelta, row.per4q,
    row.forwardPer, row.roe, row.forwardRoe, row.ret5d,
    row.excess[-5] ?? null, row.excess[0] ?? null, row.excess[5] ?? null,
    row.excess[20] ?? null, row.excess[60] ?? null,
  ];
}

export function unpackDiscoveryRow(row: DiscoveryRowWire): DiscoveryRow {
  return {
    code: row[0], name: row[1], board: row[2], sector: row[3], sectorProcess: row[4],
    sectorTheme: row[5], sectorBasis: row[6], industry: row[7], marketCap: row[8],
    quarter: row[9], quarterIndex: row[10], gatePassed: row[11], turnaround: row[12],
    category: row[13], grade: row[14], score: row[15], pri: row[16],
    hasConsensus: row[17], baseEffect: row[18], failReasons: row[19],
    revenueYoy: row[20], revenueQoq: row[21], opYoy: row[22], opQoq: row[23],
    opStatusLabel: row[24], opmYoyDelta: row[25], per4q: row[26],
    forwardPer: row[27], roe: row[28], forwardRoe: row[29], ret5d: row[30],
    excess: { [-5]: row[31], [0]: row[32], [5]: row[33], [20]: row[34], [60]: row[35] },
  };
}
