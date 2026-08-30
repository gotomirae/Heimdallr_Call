// PRD Ref: §9 — 전 종목 스크리너 경로
//
// ★ 발굴 목록과 스크리너는 같은 표·필터다. 두 구현을 복제하지 않고
//   `/screener`는 통합 화면의 "전 종목" 상태로 보낸다.
import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

export default function ScreenerPage({
  searchParams,
}: {
  searchParams: Record<string, string | string[] | undefined>;
}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(searchParams)) {
    if (Array.isArray(value)) value.forEach((item) => params.append(key, item));
    else if (value != null) params.set(key, value);
  }
  if (!params.has("gate")) params.set("gate", "all");
  redirect(`/?${params.toString()}`);
}
