// PRD Ref: §9.2 (방어 코드) · traps.md T7, T40
// 대시보드는 anon key + RLS(읽기 전용)로 Supabase를 직접 조회한다.
import { createClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!url || !anonKey) {
  throw new Error(
    "NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY가 없다. " +
      "dashboard/.env.local을 확인하라."
  );
}

export const supabase = createClient(url, anonKey);

/** PostgREST가 한 번에 1,000행만 주는 한계(T7)를 넘기 위한 페이지 크기. */
const PAGE_SIZE = 1000;

/** `42703` = 컬럼 없음. 스키마 마이그레이션 적용 전 구간에서 난다. */
const UNDEFINED_COLUMN = "42703";

/**
 * 에러 메시지에서 없는 컬럼 이름을 뽑는다.
 * PostgREST 메시지 예: `column screen_results.updated_at does not exist`
 */
export function parseMissingColumn(message: string | undefined): string | null {
  if (!message) return null;
  const match = message.match(/column\s+(?:[\w.]+\.)?["']?([\w]+)["']?\s+does not exist/i);
  return match ? match[1] : null;
}

/**
 * 누락 컬럼을 하나씩 걷어내며 재조회한다.
 *
 * ★ PostgREST는 **한 번에 하나씩만** 알려준다. 그래서 한 번 폴백하고 마는 패턴으로는
 *   컬럼이 둘 이상 빠졌을 때 여전히 500이 난다 — 반드시 루프여야 한다(PRD §9.2).
 * ★ DDL은 REST로 실행할 수 없어 사람이 SQL Editor에 적용하기 전까지 공백이 생긴다.
 *   그 사이 새 컬럼 하나 때문에 이미 잘 돌던 화면이 통째로 죽으면 안 된다.
 *
 * 걷어낸 컬럼 이름을 `dropped`로 돌려주므로, 화면에서 "이 값은 아직 없다"를 밝힐 수 있다.
 */
export async function selectWithOptionalColumns<T>(
  table: string,
  columns: string[],
  build: (query: ReturnType<typeof supabase.from>, cols: string) => PromiseLike<{
    data: unknown;
    error: { code?: string; message?: string } | null;
  }>
): Promise<{ rows: T[]; dropped: string[] }> {
  let remaining = [...columns];
  const dropped: string[] = [];

  // 컬럼 수만큼만 돌면 반드시 끝난다 — 무한 루프 방지.
  for (let attempt = 0; attempt <= columns.length; attempt += 1) {
    const { data, error } = await build(supabase.from(table), remaining.join(","));
    if (!error) {
      return { rows: (data as T[]) ?? [], dropped };
    }
    if (error.code !== UNDEFINED_COLUMN) throw error;

    const missing = parseMissingColumn(error.message);
    // 어떤 컬럼인지 못 읽으면 더 시도해봐야 같은 실패다.
    if (!missing || !remaining.includes(missing)) throw error;

    remaining = remaining.filter((c) => c !== missing);
    dropped.push(missing);
    if (remaining.length === 0) return { rows: [], dropped };
  }
  return { rows: [], dropped };
}

/**
 * range() 페이징으로 전 행을 읽는다.
 *
 * ★ `.limit(5000)`을 줘도 1,000행만 온다(T7). 잘려나가는 건 정렬 하위 —
 *   시총으로 정렬하면 소형주가 사라지는데, 이 시스템의 발굴 대상이 정확히 그 구간이다.
 *   실측: 같은 테이블이 limit(5000) → 1,000행 / 페이징 → 1,322행.
 */
export async function selectAll<T>(
  table: string,
  columns: string,
  refine?: (q: any) => any
): Promise<T[]> {
  const out: T[] = [];
  for (let offset = 0; ; offset += PAGE_SIZE) {
    let query: any = supabase.from(table).select(columns);
    if (refine) query = refine(query);
    const { data, error } = await query.range(offset, offset + PAGE_SIZE - 1);
    if (error) throw error;
    const chunk = (data as T[]) ?? [];
    out.push(...chunk);
    if (chunk.length < PAGE_SIZE) break;
  }
  return out;
}
