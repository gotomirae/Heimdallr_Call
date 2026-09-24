# PRD Ref: §8.6 — 향후 3년 산업 성장률 게이트
"""추천 알림에 쓰는 검증된 산업 성장 전망.

넓은 KRX 업종을 임의의 성장 산업으로 둔갑시키지 않는다. 제품 설명에서 성장
세부산업의 증거어가 확인되고, 출처·기준연도·3년 CAGR이 모두 있는 경우만 쓴다.
미측정 산업은 0%가 아니라 ``None``이며 추천 게이트에서 제외한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.config.constants import TECHNICAL_MIN_SECTOR_CAGR_PCT


@dataclass(frozen=True)
class SectorGrowthProfile:
    name: str
    cagr_3y_pct: float
    current_growth_pct: float | None
    next_growth_pct: float | None
    story: str
    events: tuple[str, ...]
    source: str
    source_url: str
    as_of: str


# 수치는 출처가 특정한 세부시장만 둔다. 포괄 섹터 전체에 이 수치를 전파하지 않는다.
_PROFILES: tuple[tuple[tuple[str, ...], tuple[str, ...], SectorGrowthProfile], ...] = (
    (("반도체 IDM", "반도체 DSP", "반도체 OSAT", "반도체 장비", "반도체 부품", "반도체 소재"),
     ("hbm", "고대역폭"),
     SectorGrowthProfile(
         "AI·HBM 반도체 밸류체인", 30.0, 58.0, None,
         "AI 가속기당 메모리 탑재량 증가와 HBM 세대 전환이 장비·소재·후공정 수요를 함께 끌어올리는 구간",
         ("차세대 HBM 양산·고객 인증", "AI 데이터센터 CAPEX 갱신"),
         "SK hynix 2026 HBM market outlook", "https://news.skhynix.com/en/2026-market-outlook-focus-on-the-hbm-led-memory-supercycle/", "2026-09")),
    (("소프트웨어·IT", "인터넷·플랫폼"),
     ("인공지능", "ai", "클라우드", "데이터센터", "data center"),
     SectorGrowthProfile(
         "AI 소프트웨어·클라우드", 15.7, None, None,
         "기업용 생성형 AI가 실험 단계에서 유료 워크로드와 추론 인프라 지출로 이동하는 구간",
         ("기업 AI 예산 확정", "신규 클라우드·AI 서비스 상용화"),
         "Gartner direct AI services outlook", "https://www.gartner.com/en/documents/8318253", "2026-09")),
    (("전력인프라", "신재생에너지", "2차전지"),
     ("ess", "에너지저장", "전력망", "변압기", "송전", "배전", "데이터센터"),
     SectorGrowthProfile(
         "전력망·에너지저장", 27.0, None, None,
         "데이터센터 전력 수요와 재생에너지 계통 연결이 송배전·변압기·저장장치 투자를 앞당기는 구간",
         ("전력망 투자계획 발주", "데이터센터 전력 인입·ESS 프로젝트"),
         "Grand View Research grid-scale battery storage outlook", "https://www.grandviewresearch.com/industry-analysis/grid-scale-battery-storage-market", "2026-09")),
)


def sector_growth_profile(
    sector: str | None, products: str | None, industry: str | None = None
) -> SectorGrowthProfile | None:
    """세부산업 증거어와 CAGR 문턱을 모두 만족할 때만 전망을 돌려준다."""
    text = f"{products or ''} {industry or ''}".lower()
    for sectors, evidence, profile in _PROFILES:
        if sector in sectors and (not evidence or any(token in text for token in evidence)):
            return profile if profile.cagr_3y_pct >= TECHNICAL_MIN_SECTOR_CAGR_PCT else None
    return None
