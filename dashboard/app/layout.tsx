import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Heimdallr Call",
  description: "분기실적 가속 · 주가 미반영 종목 발굴",
};

const NAV = [
  { href: "/", label: "발굴 목록" },
  { href: "/watchlist", label: "관심 종목" },
  { href: "/matrix", label: "2축 매트릭스" },
  { href: "/season", label: "시즌" },
  { href: "/outcome", label: "결과 추적" },
  { href: "/settings", label: "설정" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <header className="border-b border-slate-800 bg-slate-900/60">
          <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
            <Link href="/" className="text-lg font-semibold">
              🛡️ Heimdallr Call
            </Link>
            <nav className="flex gap-4 text-sm text-slate-200">
              {NAV.map((item) => (
                <Link key={item.href} href={item.href} className="hover:text-slate-100">
                  {item.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
