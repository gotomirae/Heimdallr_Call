# 2026-11-26 — 노션 내보내기 백필이 끝나지 않던 문제 (NEXUS 세션)

PRD Ref: §9 · T302

## 한 일
- `NotionSink.upsert`에 `create_only`(이미 있는 행 건너뜀 → 'exists')·`refresh_props`(버전이 같으면 속성만 PATCH → 'props') 추가.
- `notion_export.body_version`: 본문 버전에서 `score_flash·score_delta·pctile_in_quarter·pri·pri_detail` 제외. 본문의 주가반영도 근거 제목에 '본문 작성 시점 · 최신은 대시보드' 표시.
- `--new-only` 인자와 워크플로 입력 `new_only` 추가. 끝 줄 집계에 '속성만 갱신'·'이미 있음' 추가.

## 실측 수치
- 11/25 19:37 KST days=120 수동 실행(run 45596713756): 45분 제한으로 취소 · 본문 갱신 21 · 변화 없음 6 · 새 행 0 · 실패 0 · 노션 DELETE 3,791회(1건 약 2분).
- 11/24 정시 실행 로그: '분석 0 · 대상 0' — 11/01 ADR50 뒤 분석 생성이 Codex(Pro) 큐로 옮겨졌고 Codex 크레딧 소진으로 새 분석이 없다.
- 테스트: notion_export·workflows 145 통과(새 4건). 전체 1,460 통과 · 실패 3은 KIND 접속 불가(네트워크, 이번 변경과 무관).

## 다음 세션이 알 것
- 백필은 Actions › notion_export › Run workflow: days=120 · new_only=true · dry_run=false.
- 이번 변경으로 본문 버전 계산식이 바뀌어, 매일 실행(days=3)에 걸리는 기존 행은 한 번 더 본문을 다시 쓴다(지금은 최근 3일 분석 0건이라 영향 없음).
