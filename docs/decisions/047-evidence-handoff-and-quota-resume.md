# ADR 47 · 공통 근거 패키지·미확보 재조사·사용량 자동 재개

2026-10-11, 사용자 직접 승인. PRD §8.7 L.

- Codex의 검증 facts·gaps·원본 위치를 동일 요청 handoff로 전달한다. 전체 양식은 유지하며 기존 계산/차트/게시/PPT 도구를 재사용하고 Claude는 독립 검증·반증·공백 해소에 집중한다. provider·모델을 임의 변경하지 않는다.
- Codex 미검색/미열람/미분석 항목은 Claude가 반드시 검색 및 분석 시도하며 gap별 검색어/결과/분석 시도/미확보 사유를 기록한다. 전 gap 커버리지와 실제 Notion 전체 재조회 없이 완료하지 않는다. legacy handoff 부재도 장부/원고 공백 대조 증거가 필요하다.
- 산업 자료 선택은 최신 하위 폴더 하나에서 전체 하위 폴더의 최근 달력상 3개월 발행 자료 전체로 변경한다. 문서 발행일 우선이며 업로드/수정일/폴더 날짜 대체 금지. 산업 PDF 보존 목적지는 기존 bootstrap으로 분리한다.
- 사용량 대기는 실패 횟수를 소모하지 않는다. Claude pending/USAGE·retry_after, Codex 동일 pending/working을 보존하고 같은 ID·원고·세션에서 자동 재개한다. 중단/재개 주기별 1회 Telegram 알림을 예약·기록하고 불확실 재전송은 금지한다. source=jarvis는 무발송이다.
- 새로운 UUID·worker/CLI PID 실행 티켓과 실행별 응답/usage를 보존한다. 실제 두 프로세스 종료가 확인될 때만 orphan 복구를 시작하며 종료 불확실·legacy 티켓 부재는 자동 재실행하지 않는다. 후처리/파일/재조회 실패는 같은 세션의 제한된 기술 재시도(1분)이며 무한 품질 실패 재시도는 하지 않는다.
- 기존 Telegram Claude/PPT opt-in, JARVIS 자동 analysis, sent 비재처리, 기존 자동화/1분 작업은 유지한다. 사용량 회복은 명시 reset 또는 기본 30분 Claude 대기·Codex 30분 heartbeat로 확인한다. PC·앱·로그인·인터넷 조건과 실제 인증 오류는 별개다.
