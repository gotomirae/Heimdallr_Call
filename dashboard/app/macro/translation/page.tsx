// PRD Ref: §9, §10 — 미국·글로벌 공식 원문의 한국어 번역 보기
import Link from "next/link";
import { getMacroContext } from "@/lib/macroContext";

export const dynamic = "force-dynamic";

function translationOf(
  title: string,
  url: string,
  context: Awaited<ReturnType<typeof getMacroContext>>,
  eventDate?: string
): { heading: string; body: string; marketImpact?: string } {
  const briefing = context.briefings?.find((item) => item.url === url);
  if (briefing) return { heading: "공식 발표 한국어 핵심 번역", body: briefing.keyPoint ?? briefing.summary, marketImpact: briefing.marketImpact };
  const event = context.nextEvents?.find((item) => item.url === url && (!eventDate || item.date === eventDate));
  if (event) return { heading: "공식 발표 일정 한국어 설명", body: `${event.date} 예정 · ${event.event}\n핵심 확인 변수: ${event.watch}`, marketImpact: event.response };
  if (/federalreserve\.gov/i.test(url)) {
    return { heading: "미 연준 성명 한국어 핵심 번역", body: context.summary.forward.replace(/ 아래 미국 물가.*$/, "") };
  }
  if (/cboe\.com/i.test(url)) {
    return { heading: "CBOE VIX 한국어 설명", body: "VIX는 S&P 500 옵션 가격에서 계산한 향후 30일 예상 변동성 지수입니다. 수치가 빠르게 오르면 시장 참가자의 위험회피 비용이 높아졌다는 뜻이며, 방향과 상승 속도를 함께 확인합니다.", marketImpact: "20 아래는 비교적 안정, 25 이상은 위험회피 경계로 봅니다. VIX 상승과 주가지수 하락이 겹치면 고평가 종목 추격을 줄이고 실적·현금흐름이 확인되는 후보를 분할 확인합니다." };
  }
  if (/fearandgreedgraph\.com/i.test(url)) {
    const fear = context.fearGreed;
    return { heading: "Fear & Greed Index 한국어 설명", body: `시장 심리 지수는 주가 모멘텀·강도·변동성 등 여러 신호를 0~100으로 합친 값입니다. 현재 스냅샷은 ${fear?.value?.toFixed(1) ?? "미측정"}(${fear?.label ?? "상태 미확인"})입니다.`, marketImpact: "25 미만은 극도의 공포, 75 초과는 극도의 탐욕입니다. 절대값 하나로 매매하지 않고 VIX·지수 방향·기업 이익 전망이 같은 방향인지 함께 확인합니다." };
  }
  if (/tradingview\.com|finance\.yahoo\.com/i.test(url) || title.includes("전 거래일 종가")) {
    return { heading: "미국 시장 마감 한국어 설명", body: context.summary.current };
  }
  return {
    heading: "한국어 번역 준비 중",
    body: "이 원문은 현재 스냅샷에 한국어 번역이 저장되지 않았습니다. 아래 공식 원문에서 발표 수치와 기준일을 확인해 주세요.",
  };
}

export default async function MacroTranslationPage({
  searchParams,
}: {
  searchParams: { source?: string; eventDate?: string };
}) {
  const context = await getMacroContext();
  const source = typeof searchParams.source === "string" ? searchParams.source : "";
  const eventDate = typeof searchParams.eventDate === "string" ? searchParams.eventDate : undefined;
  const sourceEvent = context.nextEvents?.find((candidate) => candidate.url === source && (!eventDate || candidate.date === eventDate));
  const item = context.items.find((candidate) => candidate.url === source) ?? (sourceEvent ? {
    title: `${sourceEvent.source} · 향후 공식 일정`, url: sourceEvent.url, publishedAt: sourceEvent.date,
  } : undefined);

  if (!item) {
    return <main className="mx-auto max-w-3xl space-y-4 px-4 py-8">
      <h1 className="text-2xl font-black text-white">매크로 한국어 번역</h1>
      <p className="rounded-lg border border-amber-700/60 bg-amber-950/30 p-4 text-sm text-amber-100">
        현재 검증된 매크로 스냅샷에서 해당 원문을 찾지 못했습니다.
      </p>
      <Link href="/" className="text-sky-300 underline">미국·글로벌 매크로로 돌아가기</Link>
    </main>;
  }

  const translation = translationOf(item.title, item.url, context, eventDate);
  return <main className="mx-auto max-w-4xl space-y-5 px-4 py-8">
    <nav className="text-sm text-slate-400"><Link href="/" className="text-sky-300 underline">발굴 목록</Link> / 미국·글로벌 매크로 / 한국어 번역</nav>
    <header className="rounded-2xl border border-sky-700/50 bg-sky-950/25 p-5">
      <p className="text-xs font-bold tracking-wide text-sky-300">OFFICIAL SOURCE · KOREAN VIEW</p>
      <h1 className="mt-2 text-2xl font-black text-white">{item.title}</h1>
      <p className="mt-2 text-sm text-slate-300">발표·시장 기준일 {item.publishedAt ?? "미확인"} · 스냅샷 확인 {context.checkedAt}</p>
    </header>
    <article className="rounded-2xl border border-slate-700 bg-slate-950/60 p-5 md:p-7">
      <h2 className="text-lg font-extrabold text-emerald-200">{translation.heading}</h2>
      <p className="mt-4 whitespace-pre-line text-base leading-8 text-slate-100">{translation.body}</p>
      {translation.marketImpact && <div className="mt-5 rounded-lg border-l-4 border-amber-400 bg-amber-950/25 p-4"><h3 className="font-black text-amber-200">시장 의미·대응</h3><p className="mt-2 leading-7 text-slate-100">{translation.marketImpact}</p></div>}
      <div className="mt-6 rounded-lg border border-amber-700/50 bg-amber-950/20 p-3 text-xs leading-5 text-amber-100">
        공식 원문의 핵심 수치·정책 방향을 한국어로 옮긴 화면입니다. 법적·투자 판단이 필요한 문구는 원문과 함께 확인하세요.
      </div>
    </article>
    <div className="flex flex-wrap gap-3">
      <a href={item.url} target="_blank" rel="noopener noreferrer" className="rounded-lg bg-sky-500 px-4 py-2 text-sm font-bold text-white hover:bg-sky-400">공식 원문 열기</a>
      <Link href="/" className="rounded-lg border border-slate-600 px-4 py-2 text-sm font-bold text-slate-200 hover:bg-slate-800">매크로 화면으로 돌아가기</Link>
    </div>
  </main>;
}
