"use client";
// PRD Ref: §9 — 로그인 (사용자 지시 2026-08-23)
//
// ★ 클라이언트 컴포넌트여야 한다. OAuth도 OTP도 브라우저에서 시작하는 흐름이다.
//
// ★★ **두 가지를 둔 이유:**
//   구글 로그인이 UX가 낫지만 Supabase에 provider를 켜 둬야 한다(구글 클라우드에서
//   OAuth 클라이언트를 만들어야 한다). 실측(2026-08-23): 이 프로젝트는 `google: false`,
//   `email: true`였다 — 즉 **이메일 코드는 지금 바로 되고 구글은 설정이 필요하다.**
//   그래서 둘 다 두고, 구글이 꺼져 있으면 그 사실을 화면이 말한다.
import { useState } from "react";
import { createBrowserClient } from "@supabase/ssr";

function client() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );
}

export default function LoginButton({ next }: { next: string }) {
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function signInGoogle() {
    setBusy(true);
    setMessage(null);
    // ★ redirectTo는 **현재 origin**으로 만든다. 하드코딩하면 로컬(3000)과
    //   배포(vercel.app)가 갈라져 한쪽이 조용히 깨진다.
    const callback = new URL("/auth/callback", window.location.origin);
    callback.searchParams.set("next", next);
    const { error } = await client().auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: callback.toString() },
    });
    if (error) {
      setBusy(false);
      setMessage(
        error.message.includes("not enabled")
          ? "구글 로그인이 아직 켜져 있지 않다. 아래 이메일 코드로 로그인하라."
          : error.message
      );
    }
  }

  async function sendCode() {
    setBusy(true);
    setMessage(null);
    // ★ `shouldCreateUser: true` — 처음 오는 사람도 들어와야 한다.
    //   명단 검사는 로그인 **뒤에** 미들웨어가 한다(여기서 명단을 보면
    //   브라우저에 명단이 노출된다).
    const { error } = await client().auth.signInWithOtp({
      email: email.trim(),
      options: { shouldCreateUser: true },
    });
    setBusy(false);
    if (error) setMessage(error.message);
    else {
      setSent(true);
      setMessage("메일로 6자리 코드를 보냈다. 몇 분 걸릴 수 있다.");
    }
  }

  async function verifyCode() {
    setBusy(true);
    setMessage(null);
    const { error } = await client().auth.verifyOtp({
      email: email.trim(),
      token: code.trim(),
      type: "email",
    });
    if (error) {
      setBusy(false);
      setMessage(error.message);
      return;
    }
    // ★ 여기서 명단을 검사하지 않는다 — 미들웨어가 한다.
    //   명단에 없으면 `/login?denied=1`로 되돌아오며 이유가 표시된다.
    window.location.href = next.startsWith("/") ? next : "/";
  }

  const input =
    "w-full rounded border border-slate-600 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-400";

  return (
    <div className="space-y-4">
      <button
        type="button"
        onClick={signInGoogle}
        disabled={busy}
        className="flex w-full items-center justify-center gap-2 rounded border border-slate-600 bg-white px-4 py-2.5 text-sm font-semibold text-slate-900 hover:bg-slate-100 disabled:opacity-60"
      >
        <svg className="h-4 w-4" viewBox="0 0 24 24" aria-hidden="true">
          <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.76h3.57c2.08-1.92 3.27-4.74 3.27-8.09z" />
          <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.76c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z" />
          <path fill="#FBBC05" d="M5.84 14.11a6.6 6.6 0 0 1 0-4.22V7.05H2.18a11 11 0 0 0 0 9.9l3.66-2.84z" />
          <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.05l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38z" />
        </svg>
        {busy ? "처리 중…" : "구글 계정으로 로그인"}
      </button>

      <div className="flex items-center gap-3 text-xs text-slate-400">
        <span className="h-px flex-1 bg-slate-700" />
        또는 이메일 코드
        <span className="h-px flex-1 bg-slate-700" />
      </div>

      {!sent ? (
        <div className="space-y-2">
          <input
            type="email"
            inputMode="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@gmail.com"
            className={input}
            aria-label="이메일 주소"
          />
          <button
            type="button"
            onClick={sendCode}
            disabled={busy || !email.includes("@")}
            className="w-full rounded border border-slate-600 bg-slate-800 px-4 py-2 text-sm text-slate-100 hover:bg-slate-700 disabled:opacity-50"
          >
            {busy ? "보내는 중…" : "인증 코드 받기"}
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          <input
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="6자리 코드"
            className={input}
            aria-label="인증 코드"
          />
          <button
            type="button"
            onClick={verifyCode}
            disabled={busy || code.trim().length < 6}
            className="w-full rounded border border-amber-600 bg-amber-600/20 px-4 py-2 text-sm font-semibold text-amber-100 hover:bg-amber-600/30 disabled:opacity-50"
          >
            {busy ? "확인 중…" : "로그인"}
          </button>
          <button
            type="button"
            onClick={() => { setSent(false); setCode(""); setMessage(null); }}
            className="w-full text-xs text-slate-400 hover:text-slate-200"
          >
            다른 이메일로 다시 시도
          </button>
        </div>
      )}

      {message && (
        <p className="rounded border border-slate-600 bg-slate-950/60 px-3 py-2 text-xs text-slate-200">
          {message}
        </p>
      )}
    </div>
  );
}
