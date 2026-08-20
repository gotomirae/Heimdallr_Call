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

/** 규칙별 제외어. 이 말이 있으면 그 규칙은 건너뛴다. */
const EXCLUDES: Record<string, string[]> =
  (constants.sector_excludes ?? {}) as Record<string, string[]>;

/** 업종 칸에서만 쓰는 키워드(제품 칸에서는 무시). */
const INDUSTRY_ONLY = new Set<string>(
  (constants.sector_industry_only ?? []) as string[]
);

/** 화면 필터에 쓸 전체 목록. 규칙 순서 + 기타. */
export const ALL_SECTORS: string[] = [...RULES.map((r) => r.sector), UNKNOWN_SECTOR];

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
function firstHit(text: string, allowIndustryWords: boolean): string | null {
  if (!text) return null;
  let bestPos = Number.MAX_SAFE_INTEGER;
  let bestOrder = Number.MAX_SAFE_INTEGER;
  let best: string | null = null;

  RULES.forEach((r, order) => {
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
