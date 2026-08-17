# PRD Ref: 부록 B (업종 예외 처리), §4.1 G3
"""업종 제외 / 주의 판정 — **순수 함수. 외부 I/O 금지.**

업종 문자열은 추측이 아니라 KIND 실측 분포에서 뽑았다(2026-08-13, 2,687행):
    기타 금융업 104 · 금융 지원 서비스업 90 · 부동산 임대 및 공급업 27 ·
    신탁업 및 집합투자업 15 · 보험업 11 · 은행 및 저축기관 5 ·
    보험 및 연금관련 서비스업 2 · 재 보험업 1

판정 결과는 krx_universe.is_excluded / exclude_reason / sector_caveat에 기록해
나중에 검증 가능하게 한다(부록 B).
"""

from __future__ import annotations

from dataclasses import dataclass

# ═══ 제외 (분석 대상 아님) — KRX 업종명 완전일치 ═══
EXCLUDE_INDUSTRIES: dict[str, str] = {
    "은행 및 저축기관": "bank",
    "보험업": "insurance",
    "재 보험업": "insurance",
    "보험 및 연금관련 서비스업": "insurance",
    # 증권·자산운용·스팩이 여기 모인다. 매출액 개념이 다르다.
    "금융 지원 서비스업": "securities",
    # 순수지주회사가 여기 모인다(실측: '홀딩스/지주' 이름 86건 중 41건).
    "기타 금융업": "holding_or_other_finance",
    "신탁업 및 집합투자업": "reit_fund",
    "부동산 임대 및 공급업": "real_estate",
}

# ═══ 주의 표시 (제외하지 않되 sector_caveat=true) — 부록 B.2 ═══
# 업종명 부분일치
CAVEAT_INDUSTRY_TOKENS: tuple[tuple[str, str], ...] = (
    ("건설", "construction"),  # 진행기준 매출 — 분기 변동이 크다
    ("토목", "construction"),
    ("선박", "shipbuilding"),  # '선박 및 보트 건조업'
    ("조선", "shipbuilding"),
    ("의약품", "bio_pharma"),  # 마일스톤 일시 인식으로 가속 판정 왜곡
    ("의료용 물질", "bio_pharma"),
    ("생물학적", "bio_pharma"),
    ("무기 및 총포탄", "defense"),
)
# 주요제품 텍스트 부분일치 (업종명으로는 잡히지 않는 것들)
#   게임사는 업종이 '소프트웨어 개발 및 공급업'이라 업종으로 잡으면 SW 전체가 걸린다.
CAVEAT_PRODUCT_TOKENS: tuple[tuple[str, str], ...] = (
    ("게임", "game"),  # 신작 출시 분기에만 급증하는 단발 패턴
    ("방산", "defense"),
    ("군수", "defense"),
)


@dataclass(frozen=True)
class SectorVerdict:
    is_excluded: bool
    exclude_reason: str | None  # 'spac'|'bank'|'insurance'|... |'admin_issue'|'trade_stop'|'young_listing'
    sector_caveat: bool
    caveat_reason: str | None


def classify(
    *,
    industry: str | None,
    products: str | None = None,
    is_spac: bool = False,
    is_admin_issue: bool = False,
    is_trade_stopped: bool = False,
    quarters_since_listing: int | None = None,
    min_quarters: int = 5,
) -> SectorVerdict:
    """G3 판정. 제외 사유는 **하나만** 남기되 우선순위를 고정한다.

    우선순위: 스팩 → 관리종목 → 거래정지 → 업종 → 상장 히스토리 부족.
    (사유가 흔들리면 나중에 분포를 세도 의미가 없다.)

    quarters_since_listing이 None이면 '히스토리 부족' 판정을 **하지 않는다** —
    판정 불가와 False를 구분한다.
    """
    industry_text = (industry or "").strip()
    products_text = (products or "").strip()

    # 주의 플래그는 제외 여부와 독립적으로 계산한다(제외돼도 기록은 남긴다).
    caveat_reason: str | None = None
    for token, reason in CAVEAT_INDUSTRY_TOKENS:
        if token in industry_text:
            caveat_reason = reason
            break
    if caveat_reason is None:
        for token, reason in CAVEAT_PRODUCT_TOKENS:
            if token in products_text:
                caveat_reason = reason
                break

    reason: str | None = None
    if is_spac:
        reason = "spac"
    elif is_admin_issue:
        reason = "admin_issue"
    elif is_trade_stopped:
        reason = "trade_stop"
    elif industry_text in EXCLUDE_INDUSTRIES:
        reason = EXCLUDE_INDUSTRIES[industry_text]
    elif quarters_since_listing is not None and quarters_since_listing < min_quarters:
        reason = "young_listing"

    return SectorVerdict(
        is_excluded=reason is not None,
        exclude_reason=reason,
        sector_caveat=caveat_reason is not None,
        caveat_reason=caveat_reason,
    )


def quarters_since(listed_at, today) -> int | None:
    """상장 후 경과 분기 수. 상장일이 없으면 None(판정 불가)."""
    if listed_at is None:
        return None
    months = (today.year - listed_at.year) * 12 + (today.month - listed_at.month)
    return max(months // 3, 0)
