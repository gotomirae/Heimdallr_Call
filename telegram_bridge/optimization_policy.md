# 최신 실행 지시 — ADR50 (2026-11-01)

아래 과거 Claude/구독별 지시보다 ADR50이 우선한다. 신규작업은 Pro Codex 작성→같은구독 Codex 검수→검증된 최종 Notion 게시다. Claude CLI·Anthropic/OpenAI API·Batch API·추가크레딧 자동구매를 호출하지 않는다. complete-codex는 기존 영속 후속큐를 Codex 검수 실행기로 연결한다. 전체양식/자료범위/gap검색/비교검수/실제Notion전체재조회/파일해시 계약은 보존한다. PPT는 사용자버튼 요청시에만 만든다. 빈큐/한도대기는Python만 검사하고원고/세션을보존해재개한다.

# PRD Ref: §8.7 L · 사용자 2026-10-11

Codex·Claude는 이 파일을 필수로 읽는다. 기존 양식·전체 분석 항목·품질 검수는 보존한다.

## N절 파일 전달·최종본 단일 게시 (2026-10-11, 사용자 최신 결정)

새 요청은 Codex 전체 분석→파일 handoff→자동 Claude 심층 검증·보완→최종 Notion 게시·전체 재조회→🎤 PPT 선택 버튼 순서다. 이 결정은 이전 Codex Notion 필수·Telegram Claude 선택 버튼 규칙보다 우선한다. 완료된 과거 분석/PPT는 재처리하지 않는다.

Codex는 실제 기업/산업 Notion 양식 전체와 지정 부모·기존 완료 분석을 읽되 중간 Notion 페이지는 작성하지 않는다. 전체 양식의 분석 원고 Markdown과 표·차트·공식 원문·자료 선택 장부를 `state/checkpoints/ID/` 또는 `state/sources/ID/`에 저장한다. 원고·템플릿 snapshot·artifacts 각각의 절대 경로와 SHA-256을 기록하여 인계 때 실파일과 대조한다. Codex 원고·출처는 Claude가 덮어쓰지 않고 자신의 작업 폴더에서 보완한다. 저장된 원고는 Claude 중단에도 남아 수동 열람·같은 요청 재개에 사용한다.

handoff-v1 기본 facts/gaps/thesis/artifacts에 다음을 추가한다: `pipeline: "file-first-v1"`, `draft: {path,sha256}`, `template: {path,sha256,section_titles:[실제 조회 양식의 전체 큰 제목 순서]}`, `artifacts: [{path,sha256,kind}]`. 템플릿 snapshot은 실제 Notion 전체 재조회 결과이며 임의로 축소하지 않는다. 원고에 모든 제목이 있어야 한다. facts·gaps·thesis는 요약이 아닌 검증된 전체 원고에 연결되는 색인이다. 최근3개월 자료·미열람·미확보·단위·기간·원문 위치·기존 분석 변화 비교를 보존한다.

`bridge handoff ID --json-stdin` 저장 후 `bridge complete-codex ID --industry 산업명`으로 자동 Claude를 접수한다. `deliver --notion`은 새 Codex 요청에서 사용하지 않는다. 로컬은 claude 상태로 Codex intake 대상에서 제외하지만 원격 요청은 working/stage=claude이며 최종 결과처럼 sent 처리하지 않는다. 인계 중 장애는 collector가 같은 ID로 복구하며 큐의 기존 유일 인덱스로 중복을 막는다. 원고/출처를 보존하고 사용량 부족은 기존 USAGE 대기/동일 세션 재개 정책을 따른다.

Claude는 Codex 전체 원고·원문·표·차트와 모든 gap를 직접 읽고 핵심 주장 독립 검증·반대 논거·고객/TAM·현금 전환·Peer·6개월 촉매·반증 조건을 검토한다. 최종 Notion에 `Codex 최초 판단 | Claude 검증 결과 | 변경/유지 이유 | 원문` 비교 표를 남긴다. `A번호-comparison.json`의 request_id와 comparisons:[{topic,codex_view,claude_view,reason,source_urls}]를 저장하고 결과 comparison_review_path로 반환한다. 표에 핵심 투자 판단과 중요한 수치 변경을 포함하며 변경이 없으면 독립 검증 근거와 유지 이유를 명시한다.

최종 Notion은 기존 지정 부모·전체 양식 순서·색상·박스·이미지·PER/F.PER·주가 보조지표 등 모든 사용자 품질 기준을 유지한다. 원고/파일·모든 gap 검색·분석 시도·비교 검수·실제 page/blocks/ancestors 전체 재조회가 통과한 후에만 부모 요청과 Claude를 완료 처리한다. 결과 검증 마커를 먼저 보존하고 최종 상태 전환이 중단되면 재실행 없이 같은 마커에서 복구한다. 새 Telegram 요청은 이때 Notion 링크와 🎤 PPT 발표자료 만들기 버튼만 제공한다. 자동 PPT·중간 Claude 선택 버튼은 없다. JARVIS source는 Heimdallr Telegram을 발송하지 않는다. 기존 완료 메시지/버튼은 보존한다.

1. 공통 자료 패키지 `state/checkpoints/ID-handoff.json`을 만든다. `request_id`, `facts`(id, statement, value, unit, period, published_at, source_url, location, verification), `gaps`(id, topic, reason, attempted_queries), `thesis`(근거/반대/훼손조건), `artifacts`(실제 파일 경로)를 포함한다. facts·gaps는 빈 배열도 명시하되 실제 미확보를 숨기지 않는다. 같은 숫자를 모델이 다시 계산하지 않고 검증한 구조화 표·공통 계산 결과를 사용한다. 원본·해시는 유지하고 필요한 절·표·페이지를 먼저 읽는다. 기간·단위·실제/예상·가격 기준일이 다르면 재사용하지 않는다.
2. Codex는 기존 공시 수집·재무 계산·차트·업로드 도구를 재사용하고 새 해석·자료 공백 조사에 집중한다. 원고를 저장한 후 `python -m telegram_bridge.bridge handoff ID --json-stdin`으로 패키지를 검증·저장한다. 새 claim 장부에는 패키지 필수 표시가 있다. deliver 전 패키지를 검사한다.
3. Claude analysis는 핵심 투자 주장·고객/TAM·이익/현금 전환·가격에 반영된 기대·Peer 기회비용·6개월 촉매·반증 조건을 독립 검토한다. Codex 미검색/미열람/미분석을 모두 gaps에 포함하고 **각 항목을 반드시 직접 검색 및 분석 시도**한다. Codex가 실패했다는 이유만으로 건너뛰지 않는다. 공시·IR·공공 통계·신뢰 가능한 공개 원문을 시도하며 접근 권한을 우회하지 않는다. 실패해도 실제 검색어·열람 시도 URL·안전한 실패 사유·분석 시도 결과를 남기고 `(확보 필요)`로 표시한다. gap가 없는 기존 장부도 원고·확인 필요 표를 대조해 공백을 복구한다. 같은 자료의 무의미한 재검색은 피하되 중요 수치는 원문으로 독립 재검증한다.
4. Claude는 `STATE/A번호-gap-review.json`에 `request_id: A번호`, `gaps: [{id, searches:[{query,outcome}], analysis_attempt, status: resolved|unresolved, source_urls:[]}]`를 저장하고 결과 JSON의 `gap_review_path`에 절대 경로를 넣는다. handoff의 모든 gap를 포함해야 한다. 빈 gap도 빈 목록으로 검수 증거를 남긴다. 정본 handoff 없으면 `gap_inventory_checked: true`와 원고·장부 공백 대조 결과를 남긴다.
5. Notion 작성은 검증된 최종 원고를 기존 게시 도구로 변환하고 실제 전체 재조회한다. PPT는 성공 Claude 원고·공통 표·차트를 기존 양식에 매핑한다. PPT 때문에 전체 산업/기업 조사를 반복하지 않는다. 주가 최신화 시 PER/F.PER·목표가·상승여력·손익비를 같은 기준으로 갱신한다. 전 슬라이드 렌더 검수·실제 첨부·해시 재조회는 생략하지 않는다.
6. 각 실행은 `STATE/A번호-attempts/` 또는 `D번호-attempts/`에 CLI 응답·usage·소요시간을 보존한다. 캐시 읽기·캐시 생성·입력·출력을 따로 기록하며 구독 현금 청구액으로 환산하지 않는다. 모델은 임의로 낮추거나 provider를 바꾸지 않는다. 실패 범위만 이어서 보완한다.
7. 사용량 소진은 실패가 아니다. Claude는 같은 작업을 pending/USAGE로 저장하고 reset 시각 또는 기본 30분 후 기존 1분 실행기가 재개한다. 사용량 대기는 attempts를 소모하지 않는다. Codex는 같은 pending/working을 보존하며 부족 시 `bridge usage-wait ID`, 회복 시 `bridge usage-resume ID`를 호출하고 같은 체크포인트에서 진행한다. 알림은 각 중단/재개 주기마다 1회이며 불확실 전송을 반복하지 않는다. source=jarvis에는 Heimdallr Telegram을 발송하지 않는다.
8. 기업·산업 Drive는 전체 하위 폴더를 조회해 분석일 기준 최근 달력상 3개월 이내 **발행 자료 전체**를 읽는다. 표지/본문 발행일 우선, 명확한 파일명 날짜 보조. 폴더 날짜·업로드/수정일만으로 발행일을 만들지 않는다. 발행일 미확인은 확인 필요 목록으로 넘긴다. 산업 PDF 복사 목적지는 bootstrap industry_pdf_destination이며 입력 자료 선별 범위와 분리한다.
