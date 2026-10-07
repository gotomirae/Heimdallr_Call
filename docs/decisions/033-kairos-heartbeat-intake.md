# ADR 33: 전용 대화 heartbeat가 접수와 재개를 담당한다

2026-10-07 · 사용자 JARVIS J절

codex queue는 미열림 대화의 예약 실행을 보장하지 않는다. 가벼운 전용 프로젝트 대화의 kairos-intake를 07:00–24:00 KST 30분 간격으로 ACTIVE 유지한다. 기존 working 전용 kairos는 PAUSED 유지한다. 수집기는 DB를 로컬 큐로 복사하고 heartbeat 모드에서 queue 메시지를 보내지 않는다.

poll 한 번 후 빈 큐면 도구 없이 종료한다. 작업이 있으면 사용량 잔여 10%와 ordinaryUsageAllowed를 확인하고 working 우선, 없으면 가장 오래된 pending 한 건만 claim한다. 같은 장부·페이지를 재사용하고 sent를 재처리하지 않는다. 유휴 1회 20,000 토큰 초과이면 30분으로 조정한다. ACTIVE/PAUSED 직접 파일 실험은 선택이며 이번에는 하지 않았다. 앱 내부 SQLite 수정과 커넥터 없는 headless 분석은 사용하지 않는다.

Telegram 연구 제외·source=jarvis 무발송·실제 Notion 검증과 H절 sent 트리거 계약을 유지한다. 실제 검증은 docs/sessions/2026-10-07-jarvis-intake.md에 기록한다.

첫 유휴 실측은 캐시포함170,563토큰(캐시165,120·비캐시+출력5,443)이므로 J절 기준에 따라 현재 간격은30분이다. 실제 -1 Codex Notion과 JARVIS 완료 알림은 확인했으며 Claude A1은 구독 재인증이 필요하다. 상세 운영 증거는 docs/sessions/2026-10-07-jarvis-intake.md에 보존한다.
