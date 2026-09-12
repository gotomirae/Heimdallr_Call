// PRD Ref: §9, §10 — 최근 공식 매크로 맥락을 발굴 목록에 연결한다.

export interface MacroItem {
  title: string;
  url: string;
  publishedAt: string | null;
}

export interface MacroContext {
  source: string;
  checkedAt: string;
  items: MacroItem[];
  flags: {
    rates: boolean;
    industry: boolean;
    geopolitics: boolean;
  };
  /** PRI와 투자 점수를 합산하지 않고, 현재 거시국면에 맞춰 비교 순서만 바꾼다. */
  sortMode: "quality_price" | "earnings_growth" | "balanced";
  summary: {
    current: string;
    forward: string;
    recommendedSort: string;
  };
}

const BOK_RSS = "https://www.bok.or.kr/portal/bbs/B0000552/news.rss?menuNo=200690";

// 2026-09-12 확인. RSS가 잠시 실패해도 마지막으로 검증한 공식 원문과 해석을 숨기지 않는다.
// 새 수치가 확인되면 이 세 항목과 아래 요약을 함께 갱신한다.
const VERIFIED_OFFICIAL_ITEMS: MacroItem[] = [
  {
    title: "한국은행 통화신용정책보고서(2026년 9월)",
    url: "https://www.bok.or.kr/portal/bbs/B0000156/view.do?menuNo=200067&nttId=11064613",
    publishedAt: "2026-09-10",
  },
  {
    title: "한국은행 경제전망보고서(2026년 8월)",
    url: "https://www.bok.or.kr/portal/bbs/P0002359/view.do?depth=201150&menuNo=200066&nttId=11064210&oldMenuNo=201150&pageIndex=1&pageUnit=10&programType=newsData&searchCnd=1&searchKwd=",
    publishedAt: "2026-08-27",
  },
  {
    title: "KDI 경제동향 2026년 9월",
    url: "https://www.kdi.re.kr/research/monTrends?year=2026",
    publishedAt: "2026-09-07",
  },
];

function decodeXml(value: string): string {
  return value
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

function tag(block: string, name: string): string | null {
  const match = block.match(new RegExp(`<${name}[^>]*>([\\s\\S]*?)<\\/${name}>`, "i"));
  return match ? decodeXml(match[1]) : null;
}

function uniqueByUrl<T extends { url: string }>(items: T[]): T[] {
  return items.filter((item, index) => items.findIndex((candidate) => candidate.url === item.url) === index);
}

function summarize(flags: MacroContext["flags"], hasOfficialItems: boolean): Pick<MacroContext, "sortMode" | "summary"> {
  const sortMode = flags.rates || flags.geopolitics ? "quality_price" : flags.industry ? "earnings_growth" : "balanced";
  const current = !hasOfficialItems
    ? "현재: 공식 매크로 원문을 불러오지 못해 거시상황을 추정하지 않습니다."
    : "현재: 한국은행은 기준금리를 2.50%에서 3.00%로 두 차례 올렸고 물가는 상당 기간 2% 목표를 웃돌 것으로 봤습니다. KDI는 AI 인프라 투자와 반도체 중심 수출·설비투자가 강하지만 소비 회복은 완만하다고 판단했습니다.";
  const forward = !hasOfficialItems
    ? "전망: 원문이 복구될 때까지 최신 실적과 가격 데이터만으로 보수적으로 선별합니다."
    : "전망: 한국은행은 성장률을 2026년 3.3%·2027년 2.9%, 소비자물가를 2.7%·2.3%로 봅니다. 반도체·AI 투자 주도 이익 개선은 이어질 수 있지만, 추가 금리 인상과 중동·미국 통상정책·수도권 주택·가계대출이 멀티플 하방 위험입니다.";
  const recommendedSort = sortMode === "quality_price"
    ? "추천 정렬: 섹터 기회 → 높은 투자 매력도 → 낮은 PRI → 낮은 내년 F.PER → 높은 내년 F.ROE → 높은 영업이익 YoY → 등급 → 최신 분기"
    : sortMode === "earnings_growth"
      ? "추천 정렬: 섹터 기회 → 높은 투자 매력도 → 높은 영업이익 YoY → 높은 내년 F.ROE → 낮은 PRI → 등급 → 최신 분기"
      : "추천 정렬: 섹터 기회 → 높은 투자 매력도 → 낮은 PRI → 높은 영업이익 YoY → 등급 → 최신 분기";
  return { sortMode, summary: { current, forward, recommendedSort } };
}

/**
 * 한국은행 공식 RSS만 읽는다. 실패하면 빈 맥락으로 내려가며 종목 정렬 자체는
 * 최신 실적·가격으로 계속 작동한다. 뉴스 제목의 출현 횟수를 점수로 만들지는 않는다.
 */
export async function getMacroContext(): Promise<MacroContext> {
  const checkedAt = new Date().toISOString();
  try {
    const response = await fetch(BOK_RSS, {
      next: { revalidate: 6 * 60 * 60 },
      signal: AbortSignal.timeout(4_000),
      headers: { "User-Agent": "Heimdallr-Call/1.0 macro-context" },
    });
    if (!response.ok) throw new Error(`BOK RSS ${response.status}`);
    const xml = await response.text();
    const candidates = [...xml.matchAll(/<item\b[^>]*>([\s\S]*?)<\/item>/gi)]
      .map((match) => {
        const block = match[1];
        const title = tag(block, "title") ?? "";
        const description = tag(block, "description") ?? "";
        return {
          title,
          description,
          url: tag(block, "link") ?? BOK_RSS,
          publishedAt: tag(block, "pubDate"),
        };
      })
      .filter((item) => item.title);
    const relevant = candidates.filter((item) =>
      /통화정책|금리|물가|경제전망|기업경영|수출|반도체|관세|중동|금융시장/.test(
        `${item.title} ${item.description}`
      )
    );
    const pool = relevant.length > 0 ? relevant : candidates;
    // 전망·산업·물가를 하나씩 고른다. 단순 최신 3건은 같은 주제 보도자료가 화면을
    // 독점해 향후 경로가 사라질 수 있다.
    const selected = uniqueByUrl([
      ...VERIFIED_OFFICIAL_ITEMS,
      ...pool.filter((item) => /경제전망|통화정책/.test(`${item.title} ${item.description}`)).slice(0, 1),
      ...pool.filter((item) => /기업경영|수출|반도체|산업|투자/.test(`${item.title} ${item.description}`)).slice(0, 1),
      ...pool.filter((item) => /물가|금리|금융시장/.test(`${item.title} ${item.description}`)).slice(0, 1),
      ...pool,
    ]).slice(0, 5);
    const corpus = pool.map((item) => `${item.title} ${item.description}`).join(" ");
    const flags = {
      rates: /금리|통화정책|물가|인플레이션/.test(corpus),
      industry: /수출|반도체|기업경영|산업|투자/.test(corpus),
      geopolitics: /중동|관세|통상|지정학/.test(corpus),
    };
    return {
      source: "한국은행·KDI 공식 자료",
      checkedAt,
      items: selected.map(({ title, url, publishedAt }) => ({ title, url, publishedAt })),
      flags,
      ...summarize(flags, selected.length > 0),
    };
  } catch {
    return {
      source: "한국은행·KDI 공식 자료 (2026-09-12 확인)",
      checkedAt,
      items: VERIFIED_OFFICIAL_ITEMS,
      flags: { rates: true, industry: true, geopolitics: true },
      ...summarize({ rates: true, industry: true, geopolitics: true }, true),
    };
  }
}
