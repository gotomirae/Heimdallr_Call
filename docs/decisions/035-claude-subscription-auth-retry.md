# ADR 35: Claude 구독 인증 장애를 같은 작업의 재시도로 보존

PRD Ref: §8.7 G/H/J-5 · 2026-10-08

## 결정

- CLI 인증 오류 또는 비정상 종료 직후 로그인 소실은 `CLAUDE_LOGIN_REQUIRED`로 기록하고 사용량 제한과 같은 pending/30분 retry_after/기존 3회 재시도 상한을 사용한다. 로그인 없음은 claim 전에 검사하므로 attempts가 증가하지 않는다.
- 로그인 장애의 시작과 KST 마지막 알림 날짜는 로컬 SQLite에 보존한다. 30분 지속 시 기존 Heimdallr 봇의 개인 채팅으로 하루 한 번 안내한다. 발송 전에 날짜를 예약하며 전송 결과가 불확실해도 같은 날 다시 보내지 않는다. 발송 실패는 상태 메타데이터에 예외 클래스만 남긴다.
- `claude setup-token`의 `CLAUDE_CODE_OAUTH_TOKEN`만 깨끗하게 자식 환경에 추가 허용한다. API 키·Anthropic auth token·외부 endpoint/provider는 차단하고 authMethod도 검증한다. 토큰 존재만으로 검사 성공을 가정하지 않는다.
- 실제 CLI의 auth status는 가짜 OAuth 환경 토큰에도 loggedIn=true/oauth_token을 표시했다. 실행 중 인증 실패 후에는 표면 로그인 표시가 돌아와도 장애 기록을 지우지 않고 실제 인증된 실행까지 유지한다.
- 이미 완료된 실제 A1은 재접수하지 않는다. 시험용 Notion 페이지·운영 요청·시험 알림을 생성하지 않는다.

## 근거

유니트론텍 A1의 최초 CLAUDE_EXIT와 로그인 소실이 영구 failed로 처리되어 자동 회복이 끊겼다. JARVIS는 failed 후 pending/working 전환도 다시 추적하므로 새 요청이나 DB 스키마 확장 없이 기존 경로로 복구한다. 구독 토큰은 [Claude 공식 인증 문서](https://code.claude.com/docs/en/authentication)의 setup-token 방식이며 실제 값은 ignored 파일에서만 관리한다.
