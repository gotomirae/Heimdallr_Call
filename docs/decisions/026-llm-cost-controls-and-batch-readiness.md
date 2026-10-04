# LLM 비용 방어와 할인형 Batch 전환 조건

PRD Ref: §7.3 · ADR 3, 4, 9

핵심 투자판단은 `claude-sonnet-5`를 유지한다. 저가 모델이나 다른 Provider로 조용히 바꾸지 않는다. 현재 `src/analysis/batch.py`는 일반 API 순차 호출이며 Anthropic Message Batches의 50% 할인 경로가 아니다.

현재 적용: 동일 근거 재호출 방지·고정 프롬프트 캐시·호출 전 입력 토큰 검증. 승인된 단건 검증은 웹검색 없이 SDK 재시도 0, 출력 상한과 최악 비용 하드캡을 검사한다. 월 잔여 예산보다 비싼 단건도 생성 전에 차단한다. 월 비용 집계는 1,000행 이후까지 페이징한다. 월 실링과 일일 상한을 올리지 않는다.

## 할인형 Batch는 아직 운영 미적용

배치 접수와 결과 수신 사이에 러너가 종료될 수 있다. 다음 영속 계약 없이 submit 후 기다리는 방식은 중복 과금과 월 실링 우회를 만들 수 있으므로 전환하지 않는다.

1. 요청별 고유 키: 종목·분기·단계·근거 hash·요청 계약 hash. Canonical 입력과 요청 snapshot을 비공개 DB에 저장한다.
2. 원자적 예산 예약: 최악 비용을 월 잔여에서 예약하며, 일반 호출도 미정산 예약액을 포함해 실링을 검사한다. 예약이 실패하면 접수하지 않는다.
3. 접수 장부: Provider batch ID/custom ID와 상태를 저장한다. 접수 응답 유실은 `submission_unknown`으로 격리하고 자동 재접수하지 않는다.
4. 별도 결과 회수: 미완료 배치만 조회하고 생성 재호출 없이 결과를 받는다. Provider usage를 할인 단가로 정산한다.
5. 중복 회수 방어: 응답 ID별 비용 기록·결과 저장은 원자적이고 멱등이어야 한다. 검증 실패도 실제 비용은 기록하지만 정상 분석으로 저장하지 않는다.
6. 최신 근거 변경 시 구 요청으로 새 분석을 덮어쓰지 않는다. 원문 없음·결측은 성공이나 0으로 바꾸지 않는다.

현재 service-role PostgREST 접근은 있으나 SQL DDL 적용용 DB URL/비밀번호/관리 토큰은 없다. 운영 테이블·RPC 없이 할인 전환을 활성화하지 않는다. 다음 구현은 비공개 장부/원자적 RPC SQL, Provider adapter, 제출·회수 CLI, 실패 replay 테스트와 실제 할인 usage 검증을 함께 수행해야 한다. 이 문서는 구현 완료나 운영 적용 증거가 아니다.

## 승인된 실제 검증

2026-10-04 SK하이닉스 000660 2026Q2, dashboard_on_demand 운영 계약으로 1회 생성 및 검증 후 저장했다. 웹검색 0·자동 재시도 0, $0.15 승인 상한. 실제 비용 $0.085395, uncached 입력 4,900·cache-write 8,998·cache-hit 0·출력 5,310토큰. 12개 보고서 항목과 저장 후 메타 제외 Canonical 검증 오류 0, invalid=false. 근거 없는 사실 숫자 6개를 제거했다. 이 단건으로 모델 우수성·캐시 절감 실측·전체 기업 성공을 선언하지 않는다.

공식 근거: [가격](https://platform.claude.com/docs/en/about-claude/pricing), [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), [Message Batches](https://platform.claude.com/docs/en/build-with-claude/batch-processing).
