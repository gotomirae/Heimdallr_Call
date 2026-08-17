# PRD Ref: §4.4 (2축 매트릭스) · ADR 5
"""2축 매트릭스 — 최종 분류. 순수 함수. 외부 I/O 금지.

|                | PRI < 40 | PRI 40~65 | PRI > 65 |
|----------------|----------|-----------|----------|
| 스코어 ≥ 75     | ★        | ○         | △        |
| 스코어 60~75    | ○        | ·         | ·        |
| 스코어 < 60     | ·        | ·         | ✕        |

- 텔레그램 ⚡ 즉시 알림: **★ 와 ○ 만.** △와 ·는 대시보드에만.
- `base_effect_warning=True`면 한 단계 낮춘다 (★→○, ○→·).
- `sector_caveat`는 등급을 유지하되 알림 본문에 주의 문구를 붙인다.

△(고스코어·고반영)를 버리지 않는 이유: 실적이 계속 가속 중인데 이미 오른 종목은
"지금 사면 안 되는 종목"이 아니라 **"조정 시 담을 종목"**이다. PRI가 떨어지면
자동으로 ○/★로 승격된다(PRD §8.5).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.config.constants import (
    NOTIFY_GRADES,
    PRI_HIGH,
    PRI_LOW,
    SCORE_HIGH,
    SCORE_MID,
)

STAR = "★"
CIRCLE = "○"
TRIANGLE = "△"
DOT = "·"
CROSS = "✕"

#: 강등 순서. ★→○→· (△와 ✕는 강등 대상이 아니다 — 이미 주의/제외 등급이다)
_DEMOTE = {STAR: CIRCLE, CIRCLE: DOT}


@dataclass
class GradeResult:
    grade: str | None
    base_grade: str | None  # 강등 전 등급
    demoted: bool = False
    notify: bool = False
    reason: str | None = None


def base_grade(score: float | None, pri: float | None) -> str | None:
    """강등 전 등급. 스코어나 PRI를 모르면 판정하지 않는다(None)."""
    if score is None:
        return None
    if pri is None:
        # PRI 미측정(시세 실패 등)은 '반영도 판정 불가'다.
        # 스코어만으로 ★를 주면 "이미 다 오른 종목"을 최우선으로 밀어 올릴 수 있다.
        return None

    if score >= SCORE_HIGH:
        if pri < PRI_LOW:
            return STAR
        if pri <= PRI_HIGH:
            return CIRCLE
        return TRIANGLE
    if score >= SCORE_MID:
        return CIRCLE if pri < PRI_LOW else DOT
    return CROSS if pri > PRI_HIGH else DOT


def classify(
    score: float | None,
    pri: float | None,
    *,
    base_effect_warning: bool = False,
    gate_passed: bool | None = True,
) -> GradeResult:
    """최종 등급. 게이트를 통과하지 못했으면 등급을 매기지 않는다."""
    if gate_passed is not True:
        return GradeResult(
            grade=None,
            base_grade=None,
            reason="gate_failed" if gate_passed is False else "gate_undecidable",
        )

    initial = base_grade(score, pri)
    if initial is None:
        return GradeResult(grade=None, base_grade=None, reason="insufficient_data")

    grade = initial
    demoted = False
    if base_effect_warning and initial in _DEMOTE:
        grade = _DEMOTE[initial]
        demoted = True

    return GradeResult(
        grade=grade,
        base_grade=initial,
        demoted=demoted,
        notify=grade in NOTIFY_GRADES,
        reason="base_effect_demoted" if demoted else None,
    )
