"use client";
// PRD Ref: §9 · §10.0 — 대시보드 탭 전환 사전 로드

import Link from "next/link";
import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

const NAV = [
  { href: "/", label: "발굴 목록" },
  { href: "/watchlist", label: "관심 종목" },
  { href: "/matrix", label: "2축 매트릭스" },
  { href: "/season", label: "시즌" },
  { href: "/outcome", label: "결과 추적" },
  { href: "/settings", label: "설정" },
] as const;

export default function FastNav() {
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    // 브라우저가 한가할 때 상단 탭의 RSC 경로를 미리 준비한다. 서버 데이터는 각
    // 페이지의 no-store 계약을 유지하므로 오래된 화면을 고정하지 않는다.
    const warm = () => NAV.forEach(({ href }) => {
      if (href !== pathname) router.prefetch(href);
    });
    const windowWithIdle = window as Window & {
      requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
      cancelIdleCallback?: (id: number) => void;
    };
    if (windowWithIdle.requestIdleCallback) {
      const id = windowWithIdle.requestIdleCallback(warm, { timeout: 1_500 });
      return () => windowWithIdle.cancelIdleCallback?.(id);
    }
    const id = window.setTimeout(warm, 250);
    return () => window.clearTimeout(id);
  }, [pathname, router]);

  return <nav className="flex gap-4 overflow-x-auto text-sm text-slate-200" aria-label="대시보드 탭">
    {NAV.map((item) => {
      const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
      return <Link
        key={item.href}
        href={item.href}
        prefetch
        onPointerEnter={() => router.prefetch(item.href)}
        onFocus={() => router.prefetch(item.href)}
        className={`whitespace-nowrap border-b-2 py-1 transition-colors ${active ? "border-sky-400 font-bold text-white" : "border-transparent hover:text-white"}`}
      >
        {item.label}
      </Link>;
    })}
  </nav>;
}
