// PRD Ref: §7/9 · ADR50
import { NextRequest, NextResponse } from "next/server";
import { analysisAdmin, analysisAuthorized, analysisKey } from "@/lib/pro-analysis-server";
import constants from "@/lib/constants.json";
export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export async function GET(request: NextRequest) {
  if (!analysisAuthorized(request)) return NextResponse.json({status: "forbidden", message: "분석 암호를 입력해 주세요."}, {status: 403});
  const admin = analysisAdmin();
  if (!admin) return NextResponse.json({status: "unavailable"}, {status: 503});
  const q = request.nextUrl.searchParams;
  const key = analysisKey(q.get("kind") ?? "company", q.get("target") ?? q.get("code") ?? "", Number(q.get("year")) || undefined, Number(q.get("quarter")) || undefined);
  const {data, error} = await admin.from("pro_analysis_jobs").select("status,error,requested_at,claimed_at,completed_at,result").eq("request_key", key).limit(1);
  if (error) return NextResponse.json({status: "unavailable", message: "분석 큐 연결을 확인해 주세요."}, {status: 503});
  return NextResponse.json(data?.[0] ?? {status: "idle"});
}
export async function POST(request: NextRequest) {
  if (!analysisAuthorized(request)) return NextResponse.json({status: "forbidden", message: "분석 암호를 입력해 주세요."}, {status: 403});
  const admin = analysisAdmin();
  if (!admin) return NextResponse.json({status: "unavailable"}, {status: 503});
  const body = await request.json().catch(() => ({}));
  const kind = body.kind ?? "company", target = String(body.target ?? body.code ?? "").trim();
  if (!["company", "industry", "market", "strategy"].includes(kind) || !target || target.length > 100)
    return NextResponse.json({status: "invalid", message: "분석 대상을 확인해 주세요."}, {status: 400});
  const items: {year?: number; quarter?: number}[] = body.historical ? body.periods : [{year: body.year, quarter: body.quarter}];
  if (!Array.isArray(items) || !items.length || items.length > constants.pro_analysis.history_max_items)
    return NextResponse.json({status: "invalid", message: "과거 분기 범위를 확인해 주세요."}, {status: 400});
  const queued = [];
  for (const item of items) {
    const year = Number(item.year), quarter = Number(item.quarter);
    if (kind === "company") {
      if (!/^[0-9A-Z]{6}$/.test(target) || !Number.isInteger(year) || ![1,2,3,4].includes(quarter))
        return NextResponse.json({status: "invalid", message: "종목·분기를 확인해 주세요.", queued: queued.length}, {status: 400});
      const {data, error} = await admin.from("quarterly_fundamentals").select("code").eq("code", target).eq("fiscal_year", year).eq("fiscal_quarter", quarter).limit(1);
      if (error || !data?.length) return NextResponse.json({status: "invalid", message: "저장된 분기 재무가 없습니다.", queued: queued.length}, {status: 400});
    }
    const {data, error} = await admin.rpc("pro_enqueue_analysis", {p_request: {
      request_key: analysisKey(kind, target, kind === "company" ? year : undefined, kind === "company" ? quarter : undefined),
      kind, target, fiscal_year: kind === "company" ? year : null, fiscal_quarter: kind === "company" ? quarter : null,
      historical: body.historical === true, force_analysis: body.force === true, daily_limit: constants.pro_analysis.daily_limit,
    }});
    if (error) return NextResponse.json({status: "unavailable", message: "분석 큐 접수에 실패했습니다.", queued: queued.length}, {status: 503});
    queued.push(data);
  }
  return NextResponse.json({...queued[0], queued: queued.length}, {status: 202});
}
