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
}

const BOK_RSS = "https://www.bok.or.kr/portal/bbs/B0000552/news.rss?menuNo=200690";

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
    const selected = (relevant.length > 0 ? relevant : candidates).slice(0, 3);
    const corpus = selected.map((item) => `${item.title} ${item.description}`).join(" ");
    return {
      source: "한국은행 공식 RSS",
      checkedAt,
      items: selected.map(({ title, url, publishedAt }) => ({ title, url, publishedAt })),
      flags: {
        rates: /금리|통화정책|물가|인플레이션/.test(corpus),
        industry: /수출|반도체|기업경영|산업|투자/.test(corpus),
        geopolitics: /중동|관세|통상|지정학/.test(corpus),
      },
    };
  } catch {
    return {
      source: "한국은행 공식 RSS",
      checkedAt,
      items: [],
      flags: { rates: false, industry: false, geopolitics: false },
    };
  }
}
