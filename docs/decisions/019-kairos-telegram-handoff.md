# ADR 19 — Heimdallr Telegram 요청의 Kairos 전달

- 상태: 채택
- 날짜: 2026-09-18
- 관련: PRD §8, ADR 3·6·8, traps.md T44

## 결정

Heimdallr의 기존 GitHub Actions 수신기만 전용 봇의 `getUpdates`를 실행한다. 인증된 개인 채팅에서 기업명·코드를 단독 입력하면 기존 짧은 실적 리포트와 별도로 Supabase `kairos_requests`에 Telegram update ID 기준 요청을 기록한다. 로컬 Windows 수집기는 DB를 읽어 로컬 큐에 복사하고 `codex queue`로 현재 프로젝트의 Codex 작업을 깨운다. 실제 작업 ID와 원문을 `bridge.py poll`로 대조한 뒤 Kairos 스킬을 수행한다.

완성 원고는 지정 Notion 양식에 저장하고 재조회한 뒤 링크를 같은 Telegram 개인 채팅으로 돌려준다. 기존 `C:\Codex\Kairos`의 봇·큐·미처리 작업은 별도 상태로 유지한다.

## 이유

Kairos 수집기를 그대로 Heimdallr 봇에 연결하면 두 `getUpdates` 소비자가 경쟁해 요청이 조용히 사라진다(T44). 반대로 GitHub Actions 안에서는 로컬 Codex 작업과 연결된 Drive·Notion 도구를 사용할 수 없다. 영구 DB 수신함을 중간에 두면 한 폴러 원칙과 분석 작업의 재시도·중복 방지를 함께 지킬 수 있다.

## 검증 경계

새 테이블 적용, 코드 배포, 로컬 예약 작업 설치 후 실제 Telegram 요청 1건을 재생해 DB의 상태 전이와 Notion 링크 전달을 확인해야 종단 간 완료다. 설정 검증 중 시험용 Notion 페이지를 만들지 않는다.
