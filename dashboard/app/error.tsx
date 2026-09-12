"use client";
// PRD Ref: §9.2 — 일시적 연결 실패가 빈 화면이나 멈춤처럼 남지 않게 복구한다.

import { useEffect, useState } from "react";

export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const [online, setOnline] = useState(true);

  useEffect(() => {
    const sync = () => setOnline(navigator.onLine);
    sync();
    window.addEventListener("online", sync);
    window.addEventListener("offline", sync);
    return () => {
      window.removeEventListener("online", sync);
      window.removeEventListener("offline", sync);
    };
  }, []);

  return (
    <div className="rounded-lg border border-amber-700/70 bg-amber-950/30 px-4 py-6 text-sm text-slate-100" role="alert">
      <h2 className="font-semibold text-amber-200">
        {online ? "자료 연결이 잠시 끊겼습니다." : "현재 네트워크가 오프라인입니다."}
      </h2>
      <p className="mt-2 text-slate-300">현재 화면 상태는 브라우저에 보존됩니다. 연결이 돌아오면 다시 시도하세요.</p>
      <button
        type="button"
        onClick={reset}
        disabled={!online}
        className="mt-3 rounded border border-amber-600 px-3 py-1.5 font-medium text-amber-100 hover:bg-amber-900/50 disabled:cursor-not-allowed disabled:opacity-50"
      >
        다시 연결
      </button>
    </div>
  );
}
