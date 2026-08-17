// PRD Ref: §9 — 투자 섹터 분류 (읽는 시점)
//
// ★★ **규칙은 `src/universe/sector_map.py`가 유일한 출처다.**
//   `constants.json`으로 내보낸 것을 여기서 읽는다 — TS에 규칙을 다시 적으면
//   두 곳이 조용히 어긋난다(참고 프로젝트에서 실제로 겪은 사고).
//   규칙을 바꿀 때는 파이썬을 고치고 `python -m src.config.export_constants`를 돌린다.
//
// ★ **읽는 시점에 분류하는 이유:** DB의 `sector` 컬럼은 마이그레이션이 필요하고,
//   적용 전까지 화면이 KRX 업종명('기타 금속 가공제품 제조업')으로 떨어진다.
//   `industry`·`products`는 이미 DB에 있으니 그걸로 바로 분류하면 DDL이 필요 없다.
//   컬럼이 채워져 있으면 그것을 우선한다(배치가 계산한 값이 더 정확할 수 있다).
import constants from "@/lib/constants.json";
import type { UniverseRow } from "./types";

interface Rule {
  sector: string;
  keywords: string[];
}

const RULES: Rule[] = (constants.sector_rules ?? []) as Rule[];
export const UNKNOWN_SECTOR: string = constants.sector_unknown ?? "기타";

/** 화면 필터에 쓸 전체 목록. 규칙 순서 + 기타. */
export const ALL_SECTORS: string[] = [...RULES.map((r) => r.sector), UNKNOWN_SECTOR];

function haystack(...parts: (string | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ").replace(/\s+/g, " ").toLowerCase();
}

/**
 * 투자 섹터명. 못 가리면 `기타`.
 *
 * ★ **제품을 업종보다 먼저** 본다. 업종만 보면 '특수 목적용 기계 제조업' 93종목이
 *   전부 같은 섹터가 되는데, 그 안에 반도체장비·디스플레이장비·건설기계가 섞여 있다.
 * ★ 규칙 **순서가 우선순위다.** 파이썬 쪽 배열 순서가 그대로 JSON에 실려 온다.
 */
export function classifySector(
  industry: string | null | undefined,
  products: string | null | undefined,
  name?: string | null
): string {
  const productText = haystack(products);
  for (const r of RULES) {
    if (r.keywords.some((k) => productText.includes(k))) return r.sector;
  }
  const fallback = haystack(industry, name);
  for (const r of RULES) {
    if (r.keywords.some((k) => fallback.includes(k))) return r.sector;
  }
  return UNKNOWN_SECTOR;
}

/**
 * 종목의 섹터. DB 컬럼이 있으면 그것을, 없으면 읽는 시점에 분류한다.
 *
 * ★ KRX 업종명으로 떨어지지 **않는다.** 그 이름은 투자 판단에 쓸 수 없고,
 *   화면에 그대로 나오면 섹터 열이 있으나 마나가 된다(사용자 지적).
 */
export function sectorOf(u: UniverseRow | undefined): string {
  if (!u) return UNKNOWN_SECTOR;
  if (u.sector) return u.sector;
  return classifySector(u.industry, u.products, u.name);
}
