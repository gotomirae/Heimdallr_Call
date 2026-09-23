import type { Metadata } from "next";
import Link from "next/link";
import AutoRefresh from "@/components/AutoRefresh";
import FastNav from "@/components/FastNav";
import constants from "@/lib/constants.json";
import "./globals.css";

export const metadata: Metadata = {
  title: "Heimdallr Call",
  description: "분기실적 가속 · 주가 미반영 종목 발굴",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <header className="border-b border-slate-800 bg-slate-900/60">
          <div className="mx-auto flex max-w-7xl items-center gap-6 px-4 py-3">
            <Link href="/" className="text-lg font-semibold">
              🛡️ Heimdallr Call
            </Link>
            <FastNav />
          </div>
        </header>
        <AutoRefresh seconds={constants.dashboard_refresh_seconds} />
        <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
