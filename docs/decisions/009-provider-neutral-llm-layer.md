# ADR 9 — LLM Provider를 분석 도메인에서 분리한다

날짜: 2026-08-27

## 결정

Heimdallr의 재무 계산·선별·저장·표현 계층은 특정 LLM SDK 객체에 의존하지 않는다.
Provider Adapter는 공통 `LLMRequest`를 받아 `LLMResponse`와 `NormalizedUsage`를 반환한다.

- 현재 운영 기본값은 검증된 Anthropic 경로를 보존한다.
- OpenAI Responses API를 선택 가능한 Primary 분석 경로로 제공한다.
- OpenAI 기본 전환은 동일 replay와 승인된 소수 canary 검증 뒤에만 한다.
- Claude의 반론·Risk Reviewer 역할은 Primary 전환과 별도 Phase로 구현한다.
- Provider 실패 시 다른 Provider로 조용히 자동 폴백하지 않는다.
- 모델명과 공식 단가가 모두 명시되지 않으면 유료 호출 전에 차단한다.

## 이유

기존 `src/analysis/analyze.py`에는 Anthropic SDK 호출, tool schema, token counting,
usage 해석과 분석 오케스트레이션이 결합돼 있었다. 이 상태에서는 Provider를 바꿀 때
재무 입력·검증·비용 방어·화면 payload까지 함께 흔들릴 수 있다.

공통 계약 뒤로 SDK 차이를 격리하면 기존 화면 JSON과 결정론적 계산을 유지한 채 같은
입력으로 Provider만 비교할 수 있다. 비용 usage도 먼저 정규화하므로 cached input을
일반 input과 이중 과금하는 오류를 막는다.

## 되돌리면 무엇이 무너지는가

Provider SDK 응답 객체가 다시 분석 계층으로 새면 token usage, 불완전 종료, refusal,
Structured Output의 의미가 호출부마다 달라진다. 그 결과 비용 실링과 저장 검증이
Provider별로 조용히 어긋나고, 모델 교체가 다시 대규모 리팩터링이 된다.
