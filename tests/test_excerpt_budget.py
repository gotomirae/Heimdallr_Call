# PRD Ref: §7.1 · ADR 4 · traps.md T82, T100
"""발췌 길이 상수가 **한 곳에서만** 나오는지. 외부 I/O 없이 돈다.

T100: 수집기가 2,400자로 뽑는데 분석기가 2,000자에서 잘랐다. 저장된 453건 중
**428건(94%)이 평균 432자씩 버려졌고**, 잘린 건 언제나 마지막 절
`주요계약 및 연구개발활동` — 수주계약·국책과제가 적힌, **발췌를 도입한 이유
그 자체인 절**이다(T93). 두 값이 다른 파일에 따로 적혀 있었고, 검사는
`2_001`을 숫자로 박아 둬 수집기가 올라간 뒤에도 초록불이었다(T82와 같은 모양).
"""

from __future__ import annotations

from src.analysis import analyze
from src.analysis.analyze import AnalysisInput, build_user_message
from src.collectors import dart_excerpt
from src.config.constants import (
    EXCERPT_BUDGET_CHARS,
    EXCERPT_LABEL_HEADROOM_CHARS,
    EXCERPT_MAX_CHARS,
)


def test_analyzer_cap_is_larger_than_collector_budget():
    """★★ 이 부등식이 깨지면 **뽑아 놓고 버린다.** 에러도 경고도 나지 않는다."""
    assert EXCERPT_MAX_CHARS > EXCERPT_BUDGET_CHARS, (
        f"분석기 상한 {EXCERPT_MAX_CHARS}자가 수집기 예산 {EXCERPT_BUDGET_CHARS}자보다 "
        "작거나 같다 — 저장된 발췌의 끝(주요계약·연구개발)이 말없이 잘린다"
    )


def test_headroom_covers_the_longest_source_label():
    """출처 라벨이 발췌 자리를 먹으면 안 된다. 가장 긴 것은 분기 불일치 경고문이다."""
    longest = ("[출처: ★ 2026년 2분기 정기보고서 — **2026년 3분기 것이 아니다.** "
               "여기 적힌 사실을 이번 분기 사건으로 쓰지 마라.]\n\n")
    assert len(longest) <= EXCERPT_LABEL_HEADROOM_CHARS


def test_collector_and_analyzer_read_the_same_constant():
    """★ 두 모듈이 각자 숫자를 들고 있으면 반드시 어긋난다(T82: 같은 값이 5곳, 4곳이 달랐다)."""
    assert dart_excerpt.DEFAULT_BUDGET_CHARS is EXCERPT_BUDGET_CHARS
    assert analyze.EXCERPT_MAX_CHARS is EXCERPT_MAX_CHARS


def test_a_full_length_stored_excerpt_survives_intact():
    """실측 재현: 저장된 발췌 중앙값(2,461자)이 라벨과 함께 통째로 들어가는가."""
    label = "[출처: 2026년 2분기 정기보고서]\n\n"
    body = "가" * 2_461
    message = build_user_message(
        AnalysisInput(code="A", name="N", board="KOSPI", excerpt=label + body)
    )
    assert body in message, "저장해 둔 발췌가 분석 입력에서 잘렸다"


def test_runaway_excerpt_is_still_capped():
    """상한을 올린 것이지 없앤 것이 아니다 — 폭주는 여전히 막는다(ADR 4)."""
    message = build_user_message(
        AnalysisInput(code="A", name="N", board="KOSPI", excerpt="x" * 50_000)
    )
    assert "x" * (EXCERPT_MAX_CHARS + 1) not in message


def test_collector_budget_fits_the_token_ceiling():
    """한글 1자 ≈ 0.96토큰. 발췌가 입력 상한을 혼자 밀어내지 않는지 본다."""
    from src.config.constants import LLM_INPUT_TOKEN_BUDGET

    # 시스템(4,573) + 도구 스키마(3,765) + 표·시세(~1,700) = ~10,038 실측(2026-08-23)
    fixed_tokens = 10_038
    excerpt_tokens = EXCERPT_MAX_CHARS * 0.96
    assert fixed_tokens + excerpt_tokens <= LLM_INPUT_TOKEN_BUDGET
