"use client";
// PRD Ref: §9, §10 — 열린 화면도 최신 DB 결과를 다시 읽는다.
import { useEffect, useTransition } from "react";
import { useRouter } from "next/navigation";

export default function AutoRefresh({ seconds }: { seconds: number }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState === "visible" && navigator.onLine && !pending) {
        startTransition(() => router.refresh());
      }
    };
    const interval = window.setInterval(refresh, seconds * 1000);
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("online", refresh);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener("online", refresh);
    };
  }, [router, seconds, pending]);
  return <p className="mx-auto max-w-7xl px-4 pt-2 text-xs text-slate-400" role="status">
    {pending ? "최신 자료 확인 중…" : `화면 자동 갱신 · ${seconds}초마다 확인`}
  </p>;
}
