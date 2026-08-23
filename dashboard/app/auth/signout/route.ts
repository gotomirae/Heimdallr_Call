// PRD Ref: §9 — 로그아웃
//
// ★ POST만 받는다. GET으로 열어 두면 `<img src="/auth/signout">` 한 줄로
//   남을 로그아웃시킬 수 있다(CSRF).
import { NextResponse, type NextRequest } from "next/server";
import { createSupabaseServerClient } from "@/lib/supabaseServer";

export async function POST(request: NextRequest) {
  const supabase = await createSupabaseServerClient();
  await supabase.auth.signOut();
  return NextResponse.redirect(new URL("/login", request.url), { status: 303 });
}
