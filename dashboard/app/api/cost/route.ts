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
  months: Array<{ monthKey: string; spentUsd: number; calls: number }>;
  nextMonthKey: string;
  nextMonthForecastUsd: number | null;
  forecastBasis: string | null;
}

const PAGE_SIZE = 1000;

function kstParts(date: Date): { year: number; month: number; day: number } {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const value = (type: string) => Number(parts.find((part) => part.type === type)?.value);
  return { year: value("year"), month: value("month"), day: value("day") };
}

function monthKeyOf(date: Date): string {
  const { year, month } = kstParts(date);
  return `${year}-${String(month).padStart(2, "0")}`;
}

export async function GET() {
  const url = process.env.SUPABASE_URL ?? process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_KEY;

  const now = new Date();
  const { year, month, day } = kstParts(now);
  const monthKey = monthKeyOf(now);
  const nextMonthDate = new Date(Date.UTC(year, month, 1));
  const nextMonthKey = monthKeyOf(nextMonthDate);
  const empty: CostSummary = {
    available: false,
    monthKey,
    spentUsd: 0,
    monthCalls: 0,
    totalCalls: 0,
    months: [],
    nextMonthKey,
    nextMonthForecastUsd: null,
    forecastBasis: null,
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
    // SC: cost_log가 1,000행을 넘어도 월 비용과 호출 수가 잘리지 않아야 한다.
    const rows: Array<{ cost_usd: number | null; created_at: string | null }> = [];
    for (let from = 0; ; from += PAGE_SIZE) {
      const { data, error } = await admin
        .from("cost_log")
        .select("cost_usd,created_at")
        .eq("env", "prod")
        .order("created_at", { ascending: true })
        .range(from, from + PAGE_SIZE - 1);
      if (error) throw error;
      const page = data ?? [];
      rows.push(...page);
      if (page.length < PAGE_SIZE) break;
    }

    const grouped = new Map<string, { spentUsd: number; calls: number }>();
    for (const row of rows) {
      if (!row.created_at) continue;
      const key = monthKeyOf(new Date(row.created_at));
      const current = grouped.get(key) ?? { spentUsd: 0, calls: 0 };
      current.spentUsd += Number(row.cost_usd ?? 0);
      current.calls += 1;
      grouped.set(key, current);
    }
    const months = [...grouped.entries()]
      .map(([key, value]) => ({ monthKey: key, ...value }))
      .sort((a, b) => b.monthKey.localeCompare(a.monthKey))
      .slice(0, 12);
    const current = grouped.get(monthKey) ?? { spentUsd: 0, calls: 0 };

    // 완료된 비용 발생 월이 있으면 최근 3개월 평균. 없으면 이번 달 일평균을
    // 다음 달 일수로 환산한다. 근거 문자열을 함께 보내 숫자만 단정적으로 보이지 않게 한다.
    const completed = months.filter((item) => item.monthKey !== monthKey && item.spentUsd > 0).slice(0, 3);
    const nextMonthDays = new Date(Date.UTC(nextMonthDate.getUTCFullYear(), nextMonthDate.getUTCMonth() + 1, 0)).getUTCDate();
    const nextMonthForecastUsd = completed.length > 0
      ? completed.reduce((sum, item) => sum + item.spentUsd, 0) / completed.length
      : current.calls > 0
        ? (current.spentUsd / day) * nextMonthDays
        : null;
    const forecastBasis = completed.length > 0
      ? `최근 비용 발생 ${completed.length}개월 평균`
      : current.calls > 0
        ? `이번 달 ${day}일까지의 일평균 × 다음 달 ${nextMonthDays}일`
        : null;

    return NextResponse.json({
      available: true,
      monthKey,
      spentUsd: current.spentUsd,
      monthCalls: current.calls,
      totalCalls: rows.length,
      months,
      nextMonthKey,
      nextMonthForecastUsd,
      forecastBasis,
    } satisfies CostSummary);
  } catch (err) {
    return NextResponse.json({
      ...empty,
      reason: `조회 실패: ${(err as Error).message}`,
    });
  }
}
