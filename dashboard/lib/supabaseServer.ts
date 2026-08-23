// PRD Ref: §9 — 인증용 Supabase 클라이언트 (사용자 지시 2026-08-23)
//
// ★ 데이터 조회용 클라이언트(`lib/supabase.ts`)와 **다른 물건**이다.
//   그쪽은 anon key로 RLS 읽기만 하고 세션이 없다. 이쪽은 **쿠키에 세션을 실어**
//   "누가 보고 있는가"를 판별한다. 둘을 합치면 데이터 조회마다 쿠키를 만지게 되고
//   서버 컴포넌트 캐시와 얽혀 조용히 깨진다.
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

/**
 * 서버 컴포넌트/라우트 핸들러용. 쿠키에서 세션을 읽는다.
 *
 * ★ 서버 컴포넌트에서는 쿠키를 **쓸 수 없다**(읽기만 된다). 그래서 set/remove는
 *   조용히 삼킨다 — 여기서 예외를 올리면 페이지가 통째로 500이 난다.
 *   세션 갱신은 `middleware.ts`가 담당한다.
 */
export async function createSupabaseServerClient() {
  const store = await cookies();
  return createServerClient(url, anonKey, {
    cookies: {
      getAll: () => store.getAll(),
      setAll: (list) => {
        try {
          list.forEach(({ name, value, options }) => store.set(name, value, options));
        } catch {
          // 서버 컴포넌트에서 호출된 경우 — 미들웨어가 이미 갱신한다.
        }
      },
    },
  });
}

/** 지금 로그인한 사람의 이메일. 없으면 null. */
export async function currentEmail(): Promise<string | null> {
  const supabase = await createSupabaseServerClient();
  // ★ `getSession()`이 아니라 `getUser()`다 — getSession은 쿠키를 그대로 믿지만
  //   getUser는 서버에서 토큰을 검증한다. 접근 제어에는 검증된 쪽을 써야 한다.
  const { data, error } = await supabase.auth.getUser();
  if (error || !data.user) return null;
  return data.user.email ?? null;
}
