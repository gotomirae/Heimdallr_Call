# ADR 31 — Codex 완료 후 Claude 심층 분석과 자료 내용 날짜

날짜: 2026-10-06. 사용자 결정 D60·D61, 작업서 H·I.

JARVIS source의 Codex sent 전환 트랜잭션에 DB 트리거로 Claude analysis를 접수한다. 폴링 시 이미 🧠 상태가 보여 경합을 없앤다. 과거 sent 백필과 Telegram 직접 요청 자동 실행은 하지 않는다.

analysis와 deck은 request_id·mode별 열린 작업을 dedupe하되 단일 working 인덱스로 구독 Claude를 공유한다. analysis pending/working이면 같은 요청의 deck을 claim하지 않는다. analysis는 Codex Notion과 실제 로컬 작업 ID의 장부·sources·Drive·웹을 읽어 같은 부모 Notion과 Drive MD로 끝낸다. deck은 사용자 버튼으로만 실행하며 최신 성공 분석 MD를 이어받는다. 사용량 재시도 중에도 deck은 기다린다.

2_1. 산업 & 종목과 2. Invest_WiKi를 Codex 참고 루트로 추가한다. 날짜 속성→유효한 제목 날짜→생성일로 최근 달력상 3개월을 판단하고 수정일을 쓰지 않는다. 허브는 항목별 날짜로 확인한다. 현재 근거와 역사 비교를 구분하며 사용 글 제목·링크·내용 날짜·판단 기준을 체크포인트에 기록해 Claude가 같은 자료를 읽는다. SnowBall Heritage 앱 개발 메모 제외는 유지한다.
