// PRD Ref: §7 · §9.1 — 클릭형 LLM 분석 접수/상태 조회
import { createClient } from "@supabase/supabase-js";
import { NextRequest, NextResponse } from "next/server";
import { NO_STORE_OPTIONS } from "@/lib/supabase";

export const dynamic = "force-dynamic";
const CODE = /^[0-9A-Z]{6}$/;
const DAILY_REQUEST_LIMIT = 20;
const REFRESH_COOLDOWN_MS = 7 * 24 * 60 * 60 * 1000;

function adminClient() {
  const url = process.env.SUPABASE_URL ?? process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_KEY;
  if (!url || !key) return null;
  return createClient(url, key, NO_STORE_OPTIONS);
}

function sameOrigin(request: NextRequest): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return false;
  try {
    const actual = new URL(origin);
    const configured = process.env.DASHBOARD_BASE_URL;
    if (actual.hostname === "localhost" || actual.hostname === "127.0.0.1") return true;
    return configured ? actual.host === new URL(configured).host : actual.host === request.nextUrl.host;
  } catch {
    return false;
  }
}

function keyOf(code: string, year: number, quarter: number) {
  return `${code}:${year}:${quarter}`;
}

export async function GET(request: NextRequest) {
  const code = String(request.nextUrl.searchParams.get("code") ?? "").toUpperCase();
  const year = Number(request.nextUrl.searchParams.get("year"));
  const quarter = Number(request.nextUrl.searchParams.get("quarter"));
  if (!CODE.test(code) || !Number.isInteger(year) || ![1, 2, 3, 4].includes(quarter)) {
    return NextResponse.json({ status: "invalid", message: "종목·분기 형식이 올바르지 않다." }, { status: 400 });
  }
  const admin = adminClient();
  if (!admin) return NextResponse.json({ status: "unavailable", message: "분석 접수 서버 설정이 없다." }, { status: 503 });
  const { data, error } = await admin.from("dashboard_analysis_requests")
    .select("status,error,requested_at,claimed_at,completed_at")
    .eq("request_key", keyOf(code, year, quarter)).limit(1);
  if (error) return NextResponse.json({ status: "unavailable", message: error.message }, { status: 503 });
  return NextResponse.json(data?.[0] ?? { status: "idle" });
}

export async function POST(request: NextRequest) {
  if (!sameOrigin(request)) return NextResponse.json({ status: "forbidden", message: "대시보드 화면에서만 요청할 수 있다." }, { status: 403 });
  const admin = adminClient();
  if (!admin) return NextResponse.json({ status: "unavailable", message: "분석 접수 서버 설정이 없다." }, { status: 503 });
  const body = await request.json().catch(() => ({}));
  const code = String(body.code ?? "").toUpperCase();
  const year = Number(body.year);
  const quarter = Number(body.quarter);
  if (!CODE.test(code) || !Number.isInteger(year) || ![1, 2, 3, 4].includes(quarter)) {
    return NextResponse.json({ status: "invalid", message: "종목·분기 형식이 올바르지 않다." }, { status: 400 });
  }
  // 화면이 임의의 과거·미래 분기를 결제하지 못하게 실제 재무 행을 확인한다.
  const { data: fund, error: fundError } = await admin.from("quarterly_fundamentals")
    .select("code").eq("code", code).eq("fiscal_year", year).eq("fiscal_quarter", quarter).limit(1);
  if (fundError || !fund?.length) return NextResponse.json({ status: "invalid", message: "분석할 확정 분기 데이터가 없다." }, { status: 400 });

  const requestKey = keyOf(code, year, quarter);
  const { data: existing, error: readError } = await admin.from("dashboard_analysis_requests")
    .select("id,status,error,requested_at,completed_at").eq("request_key", requestKey).limit(1);
  if (readError) return NextResponse.json({ status: "unavailable", message: readError.message }, { status: 503 });
  const current = existing?.[0];
  if (current && ["pending", "working", "deferred"].includes(current.status)) return NextResponse.json(current);
  if (current?.status === "completed" && current.completed_at && Date.now() - new Date(current.completed_at).getTime() < REFRESH_COOLDOWN_MS) {
    return NextResponse.json({ ...current, message: "최근 7일 안에 완료된 최신 분석을 표시한다." });
  }
  const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  const { count } = await admin.from("dashboard_analysis_requests")
    .select("id", { count: "exact", head: true }).gte("requested_at", since);
  if ((count ?? 0) >= DAILY_REQUEST_LIMIT) return NextResponse.json({ status: "deferred", message: "최근 24시간 접수 상한에 도달했다. 다음 갱신 창에서 다시 요청할 수 있다." }, { status: 429 });

  const payload = { request_key: requestKey, code, fiscal_year: year, fiscal_quarter: quarter,
    status: "pending", error: null, requested_at: new Date().toISOString(), claimed_at: null, completed_at: null };
  const result = current
    ? await admin.from("dashboard_analysis_requests").update(payload).eq("id", current.id).select().limit(1)
    : await admin.from("dashboard_analysis_requests").insert(payload).select().limit(1);
  if (result.error) return NextResponse.json({ status: "unavailable", message: result.error.message }, { status: 503 });
  return NextResponse.json(result.data?.[0] ?? { status: "pending" }, { status: 202 });
}
