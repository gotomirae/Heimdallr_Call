# PRD Ref: §7.1, §7.2 · ADR 3, 4
"""LLM 분석 프롬프트.

★★ `SYSTEM_PROMPT`는 **얼어 있어야 한다.**
   종목마다 바뀌는 내용을 여기에 넣으면 Prompt Caching이 통째로 깨진다(ADR 4).
   날짜·종목명·수치는 전부 유저 메시지로 간다. 이 파일에 f-string을 쓰지 마라.

★ Sonnet 5의 최소 캐시 프리픽스는 **1,024토큰**이다. 이보다 짧으면 에러 없이
  그냥 캐시되지 않는다(`cache_creation_input_tokens: 0`). 이 프롬프트는 그 위에 있다.
"""

from __future__ import annotations

#: 분석 결과 스키마 (PRD §7.2 그대로). tool-forced JSON으로 강제한다.
ANALYSIS_TOOL_NAME = "record_analysis"

ANALYSIS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "one_line_thesis": {
            "type": "string",
            "description": "왜 지금 이 종목을 봐야 하는지 한 문장",
        },
        "why_now": {"type": "string", "description": "2~3문장"},
        "growth_engine": {
            "type": "object",
            "properties": {
                "drivers": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["가격 인상", "물량 증가", "신규 고객", "신제품",
                                 "지역 확장", "CAPA 확대"],
                    },
                },
                "structural_or_temporary": {
                    "type": "string",
                    "enum": ["structural", "temporary"],
                },
                "evidence": {"type": "string", "description": "숫자를 포함한 근거"},
            },
            "required": ["drivers", "structural_or_temporary", "evidence"],
            "additionalProperties": False,
        },
        "acceleration_quality": {
            "type": "object",
            "properties": {
                "is_genuine": {"type": "boolean"},
                "base_effect_assessment": {
                    "type": "string",
                    "description": "전년동기 기저가 정상인지에 대한 판단",
                },
                "sustainability_quarters": {
                    "type": "integer",
                    "description": "가속이 이어질 것으로 보는 분기 수",
                },
            },
            "required": ["is_genuine", "base_effect_assessment", "sustainability_quarters"],
            "additionalProperties": False,
        },
        "triggers": {
            "type": "object",
            "properties": {
                "within_3m": {"$ref": "#/$defs/trigger_list"},
                "within_6m": {"$ref": "#/$defs/trigger_list"},
            },
            "required": ["within_3m", "within_6m"],
            "additionalProperties": False,
        },
        "price_position": {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["매력적", "적정", "부담", "과열"]},
                "reason": {"type": "string"},
                "priced_in": {"type": "array", "items": {"type": "string"}},
                "not_priced_in": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["verdict", "reason", "priced_in", "not_priced_in"],
            "additionalProperties": False,
        },
        "scenarios": {
            "type": "object",
            "properties": {
                "bull": {"$ref": "#/$defs/scenario"},
                "base": {"$ref": "#/$defs/scenario"},
                "bear": {"$ref": "#/$defs/scenario"},
            },
            "required": ["bull", "base", "bear"],
            "additionalProperties": False,
        },
        "risks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "risk": {"type": "string"},
                    "likelihood": {"type": "string", "enum": ["높음", "중간", "낮음"]},
                    "impact": {"type": "string", "enum": ["큼", "중간", "작음"]},
                    "watch_metric": {"type": "string"},
                },
                "required": ["risk", "likelihood", "impact", "watch_metric"],
                "additionalProperties": False,
            },
        },
        "next_data_to_watch": {
            "type": "array",
            "items": {"type": "string"},
            "description": "다음 분기에 반드시 확인할 지표 3개",
        },
        "how_i_could_be_wrong": {"type": "string"},
    },
    "required": [
        "one_line_thesis", "why_now", "growth_engine", "acceleration_quality",
        "triggers", "price_position", "scenarios", "risks",
        "next_data_to_watch", "how_i_could_be_wrong",
    ],
    "additionalProperties": False,
    "$defs": {
        "trigger_list": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "event": {"type": "string"},
                    "verifiable_metric": {
                        "type": "string",
                        "description": "숫자로 확인 가능한 지표",
                    },
                    "expected_date": {"type": "string", "description": "예: 2026-11"},
                },
                "required": ["event", "verifiable_metric", "expected_date"],
                "additionalProperties": False,
            },
        },
        "scenario": {
            "type": "object",
            "properties": {
                "probability": {"type": "number"},
                "condition": {"type": "string"},
                "implication": {"type": "string"},
            },
            "required": ["probability", "condition", "implication"],
            "additionalProperties": False,
        },
    },
}

#: ★ 얼어 있는 시스템 프롬프트. 종목별 내용을 절대 넣지 마라 (ADR 4).
SYSTEM_PROMPT = """\
당신은 한국 주식시장(KOSPI/KOSDAQ)의 분기 실적을 읽는 애널리스트다.

## 당신이 하는 일과 하지 않는 일

정량 분석은 이미 끝나 있다. 분기 실적·성장률·마진·TTM·스코어·주가반영도는
모두 계산되어 입력으로 주어진다. **숫자를 다시 계산하거나 검산하지 마라.**

당신의 일은 하나다: **이 숫자 패턴이 무엇을 의미하고, 다음 1~4개 분기에
무엇이 숫자로 확인되어야 하는가**를 판단하는 것.

## 판단 기준

**성장의 질을 구분하라.** 매출이 늘어난 이유가 가격인지 물량인지, 신규 고객인지
기존 고객의 재구매인지에 따라 지속성이 다르다. 구조적 변화(CAPA 증설, 신규 고객
확보, 제품 믹스 개선)와 일시적 요인(일회성 수주, 재고 조정, 환율)을 나눠라.

**기저효과를 의심하라.** 전년동기가 비정상적으로 낮았으면 올해 성장률은 자동으로
높게 나온다. 이건 가속이 아니다. `base_effect_warning`이 붙어 있으면 특히
그 관점에서 다시 보고, 2년 스택·TTM 추세·분기 최고 매출 경신 여부를 근거로 판단하라.

**"좋은 기업"과 "좋은 투자"를 구분하라.** 실적이 훌륭해도 주가가 이미 그것을
반영했다면 지금 사는 것은 다른 문제다. 주가반영도(PRI)와 그 분해(3개월 상대수익률,
52주 위치, PER 밴드 위치)를 보고, **이미 반영된 것**과 **아직 반영되지 않은 것**을
각각 구체적으로 짚어라.

**트리거는 검증 가능해야 한다.** "실적 개선 기대" 같은 것은 트리거가 아니다.
"3Q 매출 950억 상회 여부", "주요 고객사 양산 일정 확정"처럼 **다음 분기에
숫자나 사실로 확인할 수 있는 것**만 적어라. 각 트리거에 확인 지표와 예상 시점을 붙여라.

**시나리오 확률의 합은 1.0이 되어야 한다.** bull/base/bear 각각에 조건과 함의를 쓰되,
조건은 "무엇이 관측되면 이 시나리오인가"로 서술하라.

## 주의해야 할 업종 특성

- **건설·조선·플랜트**: 진행기준 매출이라 분기 변동이 크다. 수주잔고를 함께 봐야 한다.
- **바이오·제약**: 마일스톤 일시 인식이면 가속이 아니다.
- **게임**: 신작 출시 분기에만 급증하는 단발 패턴일 수 있다.
- **4분기**: 일회성 비용(재고평가손·성과급·손상차손)이 몰려 OPM이 구조적으로 낮다.
  또한 사업보고서 차감으로 산출되므로 잔차에 회계 조정이 몰린다. 4Q 수치는 신뢰도를 낮게 보라.

## 데이터가 없을 때

컨센서스가 "커버리지 없음"이면 서프라이즈를 논하지 마라. 코스닥 상장사의 약 60%는
증권사 커버리지가 없다 — **이것은 결함이 아니라 이 시스템이 겨냥하는 구간이다.**
확정 재무(현금흐름·주식수)가 아직 없는 잠정실적 시점이면 그 한계를 명시하라.

추정으로 빈칸을 메우지 마라. 모르는 것은 모른다고 하고, 그 사실이 판단에 어떤
제약을 주는지 `how_i_could_be_wrong`에 적어라.

## 출력

반드시 `record_analysis` 도구를 호출해 구조화된 결과만 남겨라. 한국어로 쓴다.
각 필드는 간결하게 — 문장을 늘리지 말고 판단과 근거를 담아라.
"""
