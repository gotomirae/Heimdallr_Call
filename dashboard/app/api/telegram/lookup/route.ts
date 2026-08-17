// PRD Ref: §8.1
//
// 지금은 **미사용**이다. 미리 만들어 두는 이유:
// 나중에 HermesCall 웹훅에서 "watchlist에서 못 찾으면 Heimdallr로 넘김" 폴백 체이닝을
// 붙일 때 HermesCall 쪽을 5줄만 고치면 되게 하기 위함이다.
// (Heimdallr는 setWebhook을 호출하지 않는다 — 봇당 웹훅 1개 제약 때문이다. traps.md T13)
//
// 안 쓰더라도 대시보드 자체 검색에 재사용된다.
import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { NO_STORE_OPTIONS } from "@/lib/supabase";

export const runtime = "nodejs";

// ★ NO_STORE_OPTIONS 필수(T59) — 없으면 조회 결과가 디스크에 캐시돼
//   HermesCall이 며칠 전 등급을 받아 간다. 에러 없이 값만 낡는다.
const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  NO_STORE_OPTIONS,
);

/**
 * GET /api/telegram/lookup?q=005930  또는  ?q=리노공업
 *
 * 종목코드 또는 회사명으로 최신 스크리닝 결과를 돌려준다.
 * 못 찾으면 200 + { found: false } — 호출부(HermesCall)가 폴백을 이어갈 수 있어야 하므로
 * 404를 쓰지 않는다.
 */
export async function GET(request: NextRequest) {
  const q = (request.nextUrl.searchParams.get("q") ?? "").trim();
  if (!q) {
    return NextResponse.json({ found: false, reason: "missing_query" }, { status: 400 });
  }

  const isCode = /^[0-9A-Z]{6}$/.test(q.toUpperCase());
  const universe = supabase
    .from("krx_universe")
    .select("code,name,board,industry,market_cap_krw,is_excluded,exclude_reason");

  const { data: rows, error } = isCode
    ? await universe.eq("code", q.toUpperCase()).limit(1)
    : await universe.ilike("name", `%${q}%`).limit(5);

  if (error) {
    return NextResponse.json({ found: false, reason: "db_error" }, { status: 500 });
  }
  if (!rows || rows.length === 0) {
    return NextResponse.json({ found: false, reason: "not_in_universe" });
  }

  const stock = rows[0];

  // 최신 스크리닝 결과 1건. 없을 수 있으므로 결과가 비어도 정상 응답한다.
  const { data: screens } = await supabase
    .from("screen_results")
    .select("fiscal_year,fiscal_quarter,gate_passed,score_flash,pri,grade,has_consensus,base_effect_warning")
    .eq("code", stock.code)
    .order("fiscal_year", { ascending: false })
    .order("fiscal_quarter", { ascending: false })
    .limit(1);

  const screen = screens?.[0] ?? null;

  return NextResponse.json({
    found: true,
    stock,
    // ★ 필드 단위로 확인해야 한다. 상위 객체만 보고 하위를 읽으면 500이 난다(traps.md T18).
    screen: screen
      ? {
          quarter: `${screen.fiscal_year}.${screen.fiscal_quarter}Q`,
          gate_passed: screen.gate_passed ?? null,
          score: screen.score_flash ?? null,
          pri: screen.pri ?? null,
          grade: screen.grade ?? null,
          has_consensus: screen.has_consensus ?? null,
          base_effect_warning: screen.base_effect_warning ?? null,
        }
      : null,
    matches: rows.length,
    url: `${process.env.DASHBOARD_BASE_URL ?? ""}/stock/${stock.code}`,
  });
}
