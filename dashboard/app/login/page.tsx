// PRD Ref: §9 — 로그인 (사용자 지시 2026-08-23)
//
// ★ 구글 로그인만 둔다. 허용 명단 13명이 전부 @gmail.com이라 이메일 인증 메일을
//   보낼 이유가 없다 — Supabase 기본 SMTP는 시간당 발송 한도가 아주 낮아
//   여러 명이 동시에 로그인하면 메일이 안 온다.
import LoginButton from "@/components/LoginButton";

export const dynamic = "force-dynamic";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; denied?: string; error?: string }>;
}) {
  const params = await searchParams;

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-md flex-col justify-center">
      <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-6">
        <h1 className="text-xl font-bold text-white">🛡️ Heimdallr Call</h1>
        <p className="mt-1 text-sm text-slate-200">
          허용된 사용자만 볼 수 있는 대시보드다.
        </p>

        {/* ★ 왜 막혔는지를 반드시 말한다. 그냥 로그인 화면으로 되돌리면
            "로그인했는데 왜 또?"가 되어 사람이 계정을 의심한다. */}
        {params.denied === "1" && (
          <p className="mt-4 rounded border border-amber-700 bg-amber-950/40 px-3 py-2 text-sm text-amber-200">
            <strong className="text-amber-100">접근 권한이 없는 계정이다.</strong>{" "}
            로그인은 됐지만 허용 명단에 없다. 다른 계정으로 로그인하거나 관리자에게 요청하라.
          </p>
        )}
        {params.error && (
          <p className="mt-4 rounded border border-rose-700 bg-rose-950/40 px-3 py-2 text-sm text-rose-200">
            로그인에 실패했다: {params.error}
          </p>
        )}

        <div className="mt-6">
          <LoginButton next={params.next ?? "/"} />
        </div>

        <p className="mt-4 text-xs leading-relaxed text-slate-300">
          <strong className="text-slate-200">이메일 주소만 확인한다</strong> — 비밀번호는 이
          사이트가 보지도 저장하지도 않는다. 구글 로그인이 안 되면 이메일 코드를 쓰면 된다.
        </p>
      </div>
    </div>
  );
}
