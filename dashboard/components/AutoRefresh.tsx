"use client";
// PRD Ref: §9, §10 — 열린 화면도 최신 DB 결과를 다시 읽는다.
import { useEffect, useRef, useTransition } from "react";
import { useRouter } from "next/navigation";

const INTERACTION_GRACE_MS = 20_000;

export default function AutoRefresh({ seconds }: { seconds: number }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const pendingRef = useRef(false);
  const lastInteractionRef = useRef(Date.now());

  useEffect(() => {
    pendingRef.current = pending;
  }, [pending]);

  useEffect(() => {
    const noteInteraction = () => {
      lastInteractionRef.current = Date.now();
    };
    const refresh = (force = false) => {
      const interacting = Date.now() - lastInteractionRef.current < INTERACTION_GRACE_MS;
      if (
        document.visibilityState === "visible" && navigator.onLine &&
        !pendingRef.current && (force || !interacting)
      ) {
        pendingRef.current = true;
        startTransition(() => router.refresh());
      }
    };
    const interval = window.setInterval(() => refresh(false), seconds * 1000);
    const onVisibility = () => {
      if (document.visibilityState === "visible") refresh(true);
    };
    const onOnline = () => refresh(true);
    for (const event of ["pointerdown", "keydown", "input", "wheel", "touchstart"] as const) {
      window.addEventListener(event, noteInteraction, { passive: true, capture: true });
    }
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("online", onOnline);
    return () => {
      window.clearInterval(interval);
      for (const event of ["pointerdown", "keydown", "input", "wheel", "touchstart"] as const) {
        window.removeEventListener(event, noteInteraction, { capture: true });
      }
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("online", onOnline);
    };
  }, [router, seconds]);
  return <p className="mx-auto max-w-7xl px-4 pt-2 text-xs text-slate-400" role="status">
    {pending
      ? "최신 자료 확인 중… (현재 화면을 유지합니다)"
      : `화면 자동 갱신 · ${seconds}초마다 확인 · 클릭/입력 중에는 보류`}
  </p>;
}
