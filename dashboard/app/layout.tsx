import type { Metadata } from "next";
import Link from "next/link";
import { currentEmail } from "@/lib/supabaseServer";
import "./globals.css";

export const metadata: Metadata = {
  title: "Heimdallr Call",
  description: "분기실적 가속 · 주가 미반영 종목 발굴",
};

const NAV = [
  { href: "/", label: "발굴 목록" },
  { href: "/matrix", label: "2축 매트릭스" },
  { href: "/season", label: "시즌" },
  { href: "/outcome", label: "결과 추적" },
  { href: "/settings", label: "설정" },
];

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // ★ 미들웨어가 이미 막았으므로 여기 값은 '보여주기'용이다 — 접근 판정을 여기서
  //   다시 하지 않는다. 두 곳에서 판정하면 규칙이 갈라진다.
  const email = await currentEmail();

  return (
    <html lang="ko">
      <body>
        <header className="border-b border-slate-800 bg-slate-900/60">
          <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
            <Link href="/" className="text-lg font-semibold">
              🛡️ Heimdallr Call
            </Link>
            {/* ★ 로그인 전에는 감춘다 — 눌러도 전부 로그인 화면으로 되돌아오므로
                보여 주면 "왜 안 열리지"만 만든다. */}
            {email && (
              <nav className="flex gap-4 text-sm text-slate-200">
                {NAV.map((item) => (
                  <Link key={item.href} href={item.href} className="hover:text-slate-100">
                    {item.label}
                  </Link>
                ))}
              </nav>
            )}
            {/* ★ 누구로 보고 있는지 항상 보여준다 — 여러 계정을 쓰는 사람이
                "왜 안 보이지"로 헤매는 것을 막는다. */}
            {email && (
              <div className="ml-auto flex items-center gap-3 text-xs text-slate-300">
                <span className="hidden sm:inline">{email}</span>
                <form action="/auth/signout" method="post">
                  <button
                    type="submit"
                    className="rounded border border-slate-600 px-2 py-1 hover:bg-slate-800"
                  >
                    로그아웃
                  </button>
                </form>
              </div>
            )}
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
