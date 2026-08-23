// PRD Ref: §9 — OAuth 콜백
//
// 구글이 돌려보낸 code를 세션으로 바꾼다. **여기서 명단 검사도 한다** —
// 명단에 없으면 **세션을 즉시 버린다.** 그냥 로그인 화면으로만 돌려보내면
// 세션 쿠키가 남아 "로그인은 돼 있는데 아무 데도 못 가는" 상태가 된다.
import { NextResponse, type NextRequest } from "next/server";
import { createSupabaseServerClient } from "@/lib/supabaseServer";
import { isAllowed } from "@/lib/access";

export async function GET(request: NextRequest) {
  const { searchParams, origin } = request.nextUrl;
  const code = searchParams.get("code");
  const next = searchParams.get("next") || "/";
  const oauthError = searchParams.get("error_description") || searchParams.get("error");

  if (oauthError) {
    return NextResponse.redirect(
      `${origin}/login?error=${encodeURIComponent(oauthError)}`
    );
  }
  if (!code) {
    return NextResponse.redirect(`${origin}/login?error=${encodeURIComponent("코드가 없다")}`);
  }

  const supabase = await createSupabaseServerClient();
  const { error } = await supabase.auth.exchangeCodeForSession(code);
  if (error) {
    return NextResponse.redirect(
      `${origin}/login?error=${encodeURIComponent(error.message)}`
    );
  }

  const { data } = await supabase.auth.getUser();
  const email = data.user?.email ?? null;

  if (!isAllowed(email)) {
    // ★ 명단에 없으면 **세션을 버린다.** 남겨 두면 쿠키만 있고 접근은 안 되는
    //   어정쩡한 상태가 되어, 다시 로그인해도 같은 화면만 반복된다.
    await supabase.auth.signOut();
    return NextResponse.redirect(`${origin}/login?denied=1`);
  }

  // ★ 열린 리다이렉트를 막는다 — `next`는 **같은 사이트 경로**만 허용한다.
  const safeNext = next.startsWith("/") && !next.startsWith("//") ? next : "/";
  return NextResponse.redirect(`${origin}${safeNext}`);
}
