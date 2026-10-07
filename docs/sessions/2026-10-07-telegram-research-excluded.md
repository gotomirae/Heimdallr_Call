# Telegram 리서치 소스 제외 — 2026-10-07

사용자 요청: Telegram 리서치를 소스에서 제외한다.

## 반영

- Codex Kairos의 SKILL.md·source-policy.md·deck-structure.md·industry-report.md·notion-workflow.md와 Claude kairos-deck SKILL.md, 총 6개 사용자 스킬 파일에서 Telegram 채널 조회·리서치 인증·필수 보고서 항목을 제거했다. 봇 요청 수신·진행·완료 알림은 유지한다.
- 저장소 PRD·WORKFLOW·JARVIS 안내와 env example에 제외 결정을 반영했다. 과거 2026-10-06 세션 기록의 연구 인증 사용자 단계를 취소했다고 명시했다.
- BROKER_REPORT_PRIORITY_CHANNELS와 TELEGRAM_RESEARCH_CHANNELS는 빈 목록. Telegram 수집기의 status/search/auth는 설정·자격증명 조회·네트워크 연결 전에 disabled를 반환한다. 기존 세션·역사 자료는 삭제하지 않았다.
- LLM의 증권사 리포트 검색은 공식 리서치센터·회사 IR·공시 원문을 사용한다. 과거 report_context의 priority_channels도 새 프롬프트에서 비운다.
- Codex 큐와 Claude 실행 프롬프트에 과거 체크포인트·sources의 Telegram 자료를 새 분석 근거에서 제외하도록 명시했다. 같은 보고서는 원 발행기관에서 직접 확보한다.
- ADR 32·T255·AGENTS 진행 상태를 기록했다. 운영 SQL 변경과 예약 작업 재설치는 필요 없다.

## 실측

- 활성 스킬의 SungwooInsight/DOC_POOL/sunstudy1234 채널명과 연구 status/search/auth 명령 참조 0건.
- 실제 CLI status/search/auth 3개 모두 disabled / EXCLUDED_FROM_ANALYSIS_SOURCES / channels=[] 반환, 종료 코드 0. 시험용 대상 search는 비활성 수집기 상태 확인만 했고 분석·연결·페이지 생성은 하지 않았다.
- env 접근 전에 종료하는 각 3개 경로 회귀 검증 추가. 봇 큐·알림 기존 회귀를 포함한 오프라인 전체 1,275 passed / 2 skipped / 3 needs_network deselected (21.81초).
- git diff --check 통과. 외부 API 호출·운영 분석 요청·Notion 페이지 작성·Claude 생성 0건.

## 변경 위치

저장소: .env.example, AGENTS.md, docs/PRD.md, docs/traps.md, docs/decisions/032-exclude-telegram-research-sources.md, 이 세션 기록, docs/sessions/2026-10-06-jarvis-hi.md, src/analysis/analyze.py, src/collectors/telegram_sources.py, src/config/constants.py, telegram_bridge/JARVIS.md, telegram_bridge/WORKFLOW.md, telegram_bridge/bridge.py, telegram_bridge/deck_runner.py, tests/test_analysis_input.py, tests/test_freshness.py, tests/test_kairos_bridge.py, tests/test_telegram_sources.py.

사용자 스킬은 C:/Users/user/.codex/skills/kairos의 위 5개 파일과 C:/Users/user/.claude/skills/kairos-deck/SKILL.md에 직접 적용했으며 Heimdallr 저장소 밖이다.

## 다음 작업

Telegram 리서치 인증은 더 이상 필요 없다. 이후 실제 JARVIS 요청에서 Drive·Notion·공시·IR·증권사 공식 자료·공공 통계·웹 원문을 사용한다. 이미 발행된 역사 보고서를 자동 수정하거나 시험용 Notion 페이지를 만들지 않는다. 실제 요청의 전체 파이프라인 검증은 별도로 남아 있다.
