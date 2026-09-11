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
const ETF_THEMES: Record<string, string> =
  (constants.sector_etf_themes ?? {}) as Record<string, string>;

/** 규칙별 제외어. 이 말이 있으면 그 규칙은 건너뛴다. */
const EXCLUDES: Record<string, string[]> =
  (constants.sector_excludes ?? {}) as Record<string, string[]>;

/** 업종 칸에서만 쓰는 키워드(제품 칸에서는 무시). */
const INDUSTRY_ONLY = new Set<string>(
  (constants.sector_industry_only ?? []) as string[]
);
const SEMICONDUCTOR_CONTEXT: string[] =
  (constants.semiconductor_context ?? []) as string[];
const SEMICONDUCTOR_EQUIPMENT_STANDALONE: string[] =
  (constants.semiconductor_equipment_standalone ?? []) as string[];
const SEMICONDUCTOR_SPECIFIC_ORDER: string[] =
  (constants.semiconductor_specific_order ?? []) as string[];
const SEMICONDUCTOR_SECTORS = new Set([...SEMICONDUCTOR_SPECIFIC_ORDER, "반도체 IDM"]);

/** 화면 필터에 쓸 전체 목록. 규칙 순서 + 기타. */
export const ALL_SECTORS: string[] = [...RULES.map((r) => r.sector), UNKNOWN_SECTOR];

export type SectorBasis = "주요제품" | "ETF 유사 테마" | "미분류";

export interface SectorInfo {
  sector: string;
  etfTheme: string;
  basis: SectorBasis;
}

function haystack(...parts: (string | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ").replace(/\s+/g, " ").toLowerCase();
}

/**
 * 가장 **앞에서** 걸린 섹터. 같은 위치면 규칙 순서가 앞선 쪽.
 *
 * ★ `src/universe/sector_map.py`의 `_first_hit`과 **같은 알고리즘이어야 한다.**
 *   달라지면 같은 종목이 화면과 DB에서 다른 섹터로 보인다 — 에러는 나지 않는다.
 *   `tests/test_sector_map_parity.py`가 두 구현을 실제 값으로 대조한다.
 */
function semiconductorHit(text: string, allowIndustryWords: boolean): string | null {
  const rulesBySector = new Map(RULES.map((rule) => [rule.sector, rule.keywords]));
  const equipment = SEMICONDUCTOR_SPECIFIC_ORDER[0];
  const equipmentPositions = (rulesBySector.get(equipment) ?? [])
    .map((keyword) => text.indexOf(keyword)).filter((position) => position >= 0);
  const contextPositions = SEMICONDUCTOR_CONTEXT
    .map((keyword) => text.indexOf(keyword)).filter((position) => position >= 0);
  const standaloneEquipment = SEMICONDUCTOR_EQUIPMENT_STANDALONE
    .some((keyword) => text.includes(keyword));
  if (contextPositions.length === 0 && !standaloneEquipment) return null;

  const anchor = Math.min(...equipmentPositions, ...contextPositions);
  const competitorPositions: number[] = [];
  for (const rule of RULES) {
    if (SEMICONDUCTOR_SECTORS.has(rule.sector)) continue;
    if ((EXCLUDES[rule.sector] ?? []).some((bad) => text.includes(bad))) continue;
    for (const keyword of rule.keywords) {
      if (!allowIndustryWords && INDUSTRY_ONLY.has(keyword)) continue;
      const position = text.indexOf(keyword);
      if (position >= 0) competitorPositions.push(position);
    }
  }
  if (competitorPositions.length > 0 && Math.min(...competitorPositions) < anchor) return null;
  for (const sector of ["반도체 소재", "반도체 부품"]) {
    if ((rulesBySector.get(sector) ?? []).some((keyword) => text.includes(keyword))) return sector;
  }
  if (equipmentPositions.length > 0) return equipment;
  return "반도체 IDM";
}

function firstHit(text: string, allowIndustryWords: boolean): string | null {
  if (!text) return null;
  const semiconductor = semiconductorHit(text, allowIndustryWords);
  if (semiconductor !== null) return semiconductor;
  let bestPos = Number.MAX_SAFE_INTEGER;
  let bestOrder = Number.MAX_SAFE_INTEGER;
  let best: string | null = null;

  RULES.forEach((r, order) => {
    if (SEMICONDUCTOR_SECTORS.has(r.sector)) return;
    const bad = EXCLUDES[r.sector] ?? [];
    if (bad.some((b) => text.includes(b))) return; // 제외어 → 이 규칙은 없는 셈

    let pos = -1;
    for (const k of r.keywords) {
      if (!allowIndustryWords && INDUSTRY_ONLY.has(k)) continue;
      const at = text.indexOf(k);
      if (at >= 0 && (pos < 0 || at < pos)) pos = at;
    }
    if (pos < 0) return;

    if (pos < bestPos || (pos === bestPos && order < bestOrder)) {
      bestPos = pos;
      bestOrder = order;
      best = r.sector;
    }
  });
  return best;
}

/**
 * 투자 섹터명. 못 가리면 `기타`.
 *
 * ★ **제품을 업종보다 먼저** 본다. 업종만 보면 '특수 목적용 기계 제조업' 93종목이
 *   전부 같은 섹터가 되는데, 그 안에 반도체장비·디스플레이장비·건설기계가 섞여 있다.
 * ★ **위치가 규칙 순서를 이긴다** — products는 본업을 앞에 적기 때문이다.
 *   규칙 순서는 같은 위치일 때의 동점 처리로 남는다.
 * ★ **회사명은 매칭에 쓰지 않는다** — '주성엔지니어링'이 건설로 분류됐다.
 */
export function classifySector(
  industry: string | null | undefined,
  products: string | null | undefined,
  _name?: string | null
): string {
  const fromProducts = firstHit(haystack(products), false);
  if (fromProducts !== null) return fromProducts;

  const fromIndustry = firstHit(haystack(industry), true);
  if (fromIndustry !== null) return fromIndustry;

  return UNKNOWN_SECTOR;
}

/**
 * 발굴 목록에 표시할 투자 섹터 정보.
 *
 * 주요 제품이 있으면 제품을 최우선으로 삼고, 제품으로 식별되지 않을 때만
 * KRX 업종을 ETF와 비교 가능한 넓은 테마로 사용한다. ETF 상품명 자체는
 * 운용사별로 바뀌므로 상품 코드를 저장하지 않는다.
 */
export function sectorInfoOf(u: UniverseRow | undefined): SectorInfo {
  if (!u) return { sector: UNKNOWN_SECTOR, etfTheme: UNKNOWN_SECTOR, basis: "미분류" };
  if (u.sector) {
    const productSector = firstHit(haystack(u.products), false);
    const industrySector = firstHit(haystack(u.industry), true);
    const basis: SectorBasis = productSector === u.sector
      ? "주요제품"
      : industrySector === u.sector
        ? "ETF 유사 테마"
        : "주요제품";
    return {
      sector: u.sector,
      etfTheme: ETF_THEMES[u.sector] ?? u.sector,
      basis,
    };
  }
  const productSector = firstHit(haystack(u.products), false);
  if (productSector) {
    return {
      sector: productSector,
      etfTheme: ETF_THEMES[productSector] ?? productSector,
      basis: "주요제품",
    };
  }
  const industrySector = firstHit(haystack(u.industry), true);
  if (industrySector) {
    return {
      sector: industrySector,
      etfTheme: ETF_THEMES[industrySector] ?? industrySector,
      basis: "ETF 유사 테마",
    };
  }
  return { sector: UNKNOWN_SECTOR, etfTheme: UNKNOWN_SECTOR, basis: "미분류" };
}

/**
 * 종목의 섹터. DB 컬럼이 있으면 그것을, 없으면 읽는 시점에 분류한다.
 *
 * ★ KRX 업종명으로 떨어지지 **않는다.** 그 이름은 투자 판단에 쓸 수 없고,
 *   화면에 그대로 나오면 섹터 열이 있으나 마나가 된다(사용자 지적).
 */
export function sectorOf(u: UniverseRow | undefined): string {
  return sectorInfoOf(u).sector;
}
