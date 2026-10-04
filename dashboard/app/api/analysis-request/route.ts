// PRD Ref: §7 · §9.1 — 클릭형 LLM 분석 접수/상태 조회
import { createClient } from "@supabase/supabase-js";
import { NextRequest, NextResponse } from "next/server";
import { NO_STORE_OPTIONS } from "@/lib/supabase";

export const dynamic = "force-dynamic";
const CODE = /^[0-9A-Z]{6}$/;
const DAILY_REQUEST_LIMIT = 20;

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

async function savedAnalysisUsable(admin: NonNullable<ReturnType<typeof adminClient>>, code: string, year: number, quarter: number) {
  const {data, error} = await admin.from("analyses").select("payload")
    .eq("code", code).eq("fiscal_year", year).eq("fiscal_quarter", quarter).limit(1);
  if (error) throw new Error("저장된 분석 검증 상태 조회 실패");
  const payload = data?.[0]?.payload;
  return payload && typeof payload === "object" && payload._heimdallr?.invalid !== true
    && typeof payload.one_line_thesis === "string" && payload.one_line_thesis.trim().length > 0;
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
  if (data?.[0]?.status === "completed") {
    try {
      if (!await savedAnalysisUsable(admin, code, year, quarter))
        return NextResponse.json({...data[0], status: "failed", message: "⚠️ 저장 분석이 검증 실패 또는 미저장 상태입니다. 이전 접수 완료와 구분하며, 버튼으로 검증된 재분석을 요청할 수 있습니다."});
    } catch {
      return NextResponse.json({status: "unavailable", message: "분석 결과 상태 조회 실패 · 완료로 표시하지 않습니다."}, {status: 503});
    }
  }
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
  const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  const { count, error: countError } = await admin.from("dashboard_analysis_requests")
    .select("id", { count: "exact", head: true }).gte("requested_at", since);
  if (countError) return NextResponse.json({status: "unavailable", message: "접수 사용량을 확인하지 못해 새 분석을 보류합니다."}, {status: 503});
  if ((count ?? 0) >= DAILY_REQUEST_LIMIT) return NextResponse.json({ status: "rate_limited", message: "최근 24시간 접수 상한에 도달했다. 큐에 접수되지 않았으며 다음 갱신 창에서 다시 요청할 수 있다." }, { status: 429 });

  const payload = { request_key: requestKey, code, fiscal_year: year, fiscal_quarter: quarter,
    status: "pending", error: null, requested_at: new Date().toISOString(), claimed_at: null, completed_at: null };
  const result = current
    ? await admin.from("dashboard_analysis_requests").update(payload).eq("id", current.id).eq("status", current.status).eq("requested_at", current.requested_at).select().limit(1)
    : await admin.from("dashboard_analysis_requests").insert(payload).select().limit(1);
  if (result.error) return NextResponse.json({ status: "unavailable", message: "접수 충돌 또는 서버 오류입니다. 상태를 확인한 뒤 다시 요청해 주세요." }, { status: 503 });
  if (!result.data?.length) return NextResponse.json({status: "conflict", message: "요청 상태가 변경되었습니다. 현재 상태를 조회한 뒤 다시 요청해 주세요."}, {status: 409});
  return NextResponse.json(result.data?.[0] ?? { status: "pending" }, { status: 202 });
}
