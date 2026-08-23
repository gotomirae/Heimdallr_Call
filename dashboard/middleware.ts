// PRD Ref: §9 — 대시보드 접근 제한 (사용자 지시 2026-08-23)
//
// ★★ **모든 경로를 기본 차단한다.** 새 페이지를 추가할 때마다 보호를 잊는 실수를
//   막으려면 "허용 목록"이 아니라 "차단이 기본"이어야 한다. 로그인·콜백만 연다.
//
// ★ 미들웨어는 **세션 갱신도 겸한다.** 서버 컴포넌트는 쿠키를 못 쓰므로
//   토큰이 만료돼도 스스로 갱신하지 못한다 — 여기서 해 줘야 로그인이 유지된다.
import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import { isAllowed } from "@/lib/access";

/** 로그인 없이 열어 두는 경로. **이 목록을 늘릴 때는 반드시 이유를 적어라.** */
const PUBLIC_PATHS = ["/login", "/auth/callback", "/auth/signout"];

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  let response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll: () => request.cookies.getAll(),
        setAll: (list) => {
          list.forEach(({ name, value }) => request.cookies.set(name, value));
          response = NextResponse.next({ request });
          list.forEach(({ name, value, options }) =>
            response.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  // ★ getUser()는 서버에서 토큰을 검증한다. getSession()은 쿠키를 그대로 믿으므로
  //   접근 제어에 쓰면 안 된다 — 쿠키는 클라이언트가 만든다.
  const { data } = await supabase.auth.getUser();
  const email = data.user?.email ?? null;

  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    // 이미 통과한 사람이 로그인 화면에 오면 대시보드로 되돌린다.
    if (pathname === "/login" && isAllowed(email)) {
      return NextResponse.redirect(new URL("/", request.url));
    }
    return response;
  }

  if (!isAllowed(email)) {
    const login = new URL("/login", request.url);
    // 로그인 뒤 원래 보려던 곳으로 돌려보낸다.
    if (pathname !== "/") login.searchParams.set("next", pathname);
    // 로그인은 했는데 명단에 없는 경우 — 왜 막혔는지 화면이 말해야 한다.
    if (email) login.searchParams.set("denied", "1");
    return NextResponse.redirect(login);
  }

  return response;
}

export const config = {
  // ★ 정적 자원과 파비콘은 통과시킨다 — 막으면 로그인 화면 자체가 깨진다.
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
};
