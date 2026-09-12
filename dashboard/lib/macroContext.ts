// PRD Ref: §9, §10 — 미국 중심 글로벌 매크로 맥락을 발굴 목록에 연결한다.

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
  /** 공식 매크로의 실물 수혜가 구조화 실적에서도 확인되는 섹터를 먼저 비교한다. */
  preferredSectors: string[];
  summary: {
    current: string;
    forward: string;
    recommendedSort: string;
  };
}

// 2026-09-12 공식 원문 확인. 대시보드 렌더 때 외부 사이트를 다시 부르지 않는다.
// ★ 외부 RSS를 핵심 렌더 경로에 두면 공급자 응답이 느린 날 화면 전체 스트림이
//   4초 이상 열린 채 남는다. 공식 자료 갱신은 검증 후 이 스냅샷을 바꾸고, 화면은
//   Supabase 조회와 독립적으로 즉시 같은 판단을 사용한다.
const VERIFIED_OFFICIAL_ITEMS: MacroItem[] = [
  {
    title: "미 연준 FOMC 성명 (2026-07-29)",
    url: "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260729a.htm",
    publishedAt: "2026-07-29",
  },
  {
    title: "미 연준 통화정책보고서 (2026년 7월)",
    url: "https://www.federalreserve.gov/monetarypolicy/2026-07-mpr-summary.htm",
    publishedAt: "2026-07-10",
  },
  {
    title: "미국 2026년 8월 고용 (BLS)",
    url: "https://www.bls.gov/news.release/empsit.htm",
    publishedAt: "2026-09-04",
  },
  {
    title: "미국 2026년 8월 생산자물가 (BLS)",
    url: "https://www.bls.gov/news.release/ppi.nr0.htm",
    publishedAt: "2026-09-10",
  },
  {
    title: "미국 2026년 2분기 GDP 2차 추정 (BEA)",
    url: "https://www.bea.gov/data/gdp/gross-domestic-product",
    publishedAt: "2026-08-26",
  },
  {
    title: "IMF 세계경제전망 업데이트 (2026년 7월)",
    url: "https://www.imf.org/en/publications/weo/issues/2026/07/08/world-economic-outlook-update-july-2026",
    publishedAt: "2026-07-08",
  },
];

const CURRENT_CONTEXT: MacroContext = {
  source: "미 연준·BLS·BEA·IMF 공식 자료 (2026-09-12 확인)",
  checkedAt: "2026-09-12",
  items: VERIFIED_OFFICIAL_ITEMS,
  flags: { rates: true, industry: true, geopolitics: true },
  sortMode: "quality_price",
  // AI 설비투자·데이터센터 전력 수요의 직접 공급망부터 둔다. 방산·조선은 지정학적
  // 수요가 실적으로 확인된 경우의 다음 묶음이다. 이 목록만으로 종목을 통과시키지는
  // 않고 buildSectorPriorities의 ★/○·PRI·실적 조건을 만족한 섹터 안에서만 승격한다.
  preferredSectors: [
    "반도체 장비", "반도체 소재", "반도체 부품", "반도체 DSP", "반도체 OSAT",
    "반도체 IDM", "전력인프라", "통신·네트워크", "방산·우주", "조선·해운",
  ],
  summary: {
    current: "현재(미국 중심): 연준은 정책금리를 3.50~3.75%로 동결했지만 물가는 2% 목표보다 높다고 봤습니다. 미국 8월 고용은 +16.2만명·실업률 4.1%로 버티는 반면, 8월 생산자물가는 전월 대비 +0.4%로 금리 민감 성장주의 멀티플 부담이 남아 있습니다.",
    forward: "글로벌 전망: IMF는 세계 성장률을 2026년 3.0%·2027년 3.4%로 보며, 전쟁·에너지 충격을 AI 투자 붐이 일부 상쇄한다고 판단했습니다. 미국의 AI·데이터센터 설비투자와 연결된 반도체·전력 공급망은 우선 보되, 고금리·통상·지정학 위험 때문에 실제 이익·낮은 PRI·낮은 F.PER를 함께 확인합니다.",
    recommendedSort: "추천 정렬: 미국 AI·글로벌 공급망 적합 섹터 → 높은 투자 매력도 → 낮은 PRI → 낮은 내년 F.PER → 높은 내년 F.ROE → 높은 영업이익 YoY → 등급 → 최신 분기",
  },
};

/**
 * 공식 원문을 검증해 둔 스냅샷을 반환한다.
 *
 * 뉴스 제목 빈도나 감성은 점수로 만들지 않는다. 외부 공식 사이트의 순간 장애가
 * 대시보드 연결·클릭까지 붙들지 않도록 페이지 요청 중 네트워크 I/O도 하지 않는다.
 */
export async function getMacroContext(): Promise<MacroContext> {
  return {
    ...CURRENT_CONTEXT,
    items: [...CURRENT_CONTEXT.items],
    preferredSectors: [...CURRENT_CONTEXT.preferredSectors],
  };
}
