export default function Loading() {
  return (
    <div
      className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-6 text-sm text-white"
      role="status"
      aria-live="polite"
    >
      최신 자료를 불러오는 중…
    </div>
  );
}
