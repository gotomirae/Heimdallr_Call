// PRD Ref: §9 /settings · schema.sql RLS 주석
//
// ★★ `cost_log`에는 **anon SELECT 정책이 없다**(의도적 설계).
//    비용은 공개 대상이 아니므로 anon 키로는 못 읽는다 —
//    그런데 RLS는 **에러가 아니라 빈 배열**을 준다. 그래서 클라이언트에서
//    바로 읽으면 "이번 달 비용 $0"으로 조용히 잘못 표시된다(실측으로 겪었다).
//
//    스키마 주석이 지시한 대로 **서버사이드 라우트를 경유**한다.
//    service_role 키는 RLS를 우회하며, 이 키는 서버에서만 존재한다
//    (`NEXT_PUBLIC_` 접두사가 없으므로 브라우저 번들에 들어가지 않는다).
import { createClient } from "@supabase/supabase-js";
import { NO_STORE_OPTIONS } from "@/lib/supabase";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export interface CostSummary {
  available: boolean;
  reason?: string;
  monthKey: string;
  spentUsd: number;
  monthCalls: number;
  totalCalls: number;
}

export async function GET() {
  const url = process.env.SUPABASE_URL ?? process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_KEY;

  const now = new Date();
  const monthKey = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const empty: CostSummary = {
    available: false,
    monthKey,
    spentUsd: 0,
    monthCalls: 0,
    totalCalls: 0,
  };

  // ★ 키가 없으면 **없다고 말한다.** 0으로 응답하면 "비용이 안 든다"로 읽힌다.
  if (!url || !serviceKey) {
    return NextResponse.json({
      ...empty,
      reason:
        "SUPABASE_SERVICE_KEY가 없다. cost_log는 anon으로 읽을 수 없어 " +
        "서버 키가 있어야 비용을 표시할 수 있다.",
    });
  }

  try {
    // ★ NO_STORE_OPTIONS 필수 — 없으면 Next가 응답을 디스크에 캐시해 며칠 전
    //   비용을 계속 보여준다(T59). 라우트에 force-dynamic이 있어도 막히지 않는다.
    const admin = createClient(url, serviceKey, NO_STORE_OPTIONS);
    const { data, error } = await admin
      .from("cost_log")
      .select("cost_usd,env,created_at")
      .eq("env", "prod");
    if (error) throw error;

    const rows = data ?? [];
    const month = rows.filter((r) => (r.created_at ?? "").startsWith(monthKey));
    return NextResponse.json({
      available: true,
      monthKey,
      spentUsd: month.reduce((s, r) => s + Number(r.cost_usd ?? 0), 0),
      monthCalls: month.length,
      totalCalls: rows.length,
    } satisfies CostSummary);
  } catch (err) {
    return NextResponse.json({
      ...empty,
      reason: `조회 실패: ${(err as Error).message}`,
    });
  }
}
