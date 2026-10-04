# Heimdallr Telegram → Kairos → Notion

## 최신 필수 출처 정책 (2026-10-04)

기업·산업 모두 [SOURCE_POLICY.md](SOURCE_POLICY.md)를 조사 전과 재개 시 반드시 읽는다. Notion 모니터링·추가 자료 두 곳과 Hermes Call·Heimdallr Call·SAGE 세 사이트를 기존 출처에 추가한다. **모든 활용자료는 분석 실행일 기준 최근 3개월로 제한**하며, 아래 종전 설명의 오래된 이전 분석 비교·웹 배경 자료 예외는 폐지한다. 접근·자료일을 검증하지 못한 자료는 근거로 사용하지 않고 조회 결과와 원문 링크를 장부·보고서에 남긴다.

Windows의 `HeimdallrTelegramListener`만 Telegram `getUpdates`를 1분마다 호출한다. 인증된 개인 채팅에서 종목명·6자리 코드 또는 산업명을 단독으로 입력하면 접수·예상 시간 메시지를 보내고 `kairos_requests`에 Telegram update ID, `request_kind`, `target_name`으로 심층 분석 요청을 기록한다. 짧은 종목 요약은 보내지 않는다. 수정·전달·그룹·봇 경유 메시지와 문장형 질의는 심층 분석 요청이 아니다. `/status`는 최근 요청의 대상 유형·단계·실패 원인을 조회한다.

Windows의 `HeimdallrKairosCollector`는 Supabase의 `pending` 요청을 읽어 이 저장소의 로컬 SQLite 큐로 복사하고, `codex queue`로 지정 Codex 작업을 깨운다. claim이 없으면 5분 뒤 다시 깨운다. 이 수집기는 Telegram API를 폴링하지 않는다. 기존 `C:\Codex\Kairos` 봇·큐·미처리 작업은 건드리지 않는다.

산업 Drive 폴더는 분석 작업이 `ask-folder ID --json-stdin`으로 기록하고, `folder_name`·`folder_url`은 하나의 JSON 객체로 표준입력에 전달한다. Drive에서 읽은 폴더명을 shell 명령문에 직접 삽입하지 않는다. 숫자 접두어·공백·밑줄·하이픈만 제외한 정규화 이름이 요청 산업명과 같으면 바로 계속한다. 이름이 다르면 `awaiting_input`으로 멈추고 해당 Telegram 확인 메시지에 `예` 또는 `아니오`로 답장받는다. `예`는 같은 ID의 원고·체크포인트를 재개하고, `아니오`는 요청을 거절하며 이유를 회신한다. 확인 대기 중에는 다른 작업을 시작하지 않는다.

## 설치

1. Heimdallr Supabase SQL Editor에서 최초 설치는 `docs/migrations/kairos_requests.sql`, 기존 설치는 `docs/migrations/kairos_drive_confirmation.sql`을 적용한다. `python -m src.db.init`으로 service 읽기와 anon 비공개를 확인한다.
2. GitHub Actions `telegram_listen`을 비활성화하고 이 변경을 배포한다. 수신 작업을 설치하기 전에 DB 테이블을 먼저 적용한다. 두 수신기를 동시에 켜지 않는다.
3. 로컬 `.env.txt`에 Heimdallr 전용 봇 토큰(ID `8933940541`), 허용 개인 chat ID, Supabase URL과 service key가 설정됐는지 확인한다. 토큰 값은 출력하지 않는다. `.venv`에서 `pip install -e ".[dev]"`를 실행한다.
4. `python -m telegram_bridge.bridge configure-trigger --thread <이 Codex 작업 ID>`로 실제 분석을 수행할 활성 작업을 등록한다. 다른 작업으로 바꾸면 아직 `pending`인 요청의 깨우기 기록은 즉시 초기화되어 새 작업으로 재전송된다. `poll`의 `trigger_thread`·`trigger_thread_updated_at`을 현재 작업 ID·설정 시각과 대조한다.
5. `powershell -NoProfile -File telegram_bridge/install_listener.ps1`로 전용 봇 1분 수신 작업을 설치하고, `powershell -NoProfile -File telegram_bridge/install_collector.ps1`로 창 없는 1분 수집 작업을 설치한다. `telegram_bridge/state/listener_last.json`, `python -m telegram_bridge.bridge status`, `python -m telegram_bridge.bridge ingest`로 상태를 확인한다. 테스트 기업명을 보내거나 Notion 시험 페이지를 만들지 않는다.

## 실행에 필요한 운영 조건

- 현재 Windows 예약 작업은 `Interactive only`이다. **PC가 켜져 있고, `user` 계정이 로그인된 채 절전이 아니어야** 1분 수신기·수집기가 돈다. 잠금 화면은 로그아웃이 아니므로 괜찮지만, 로그아웃·절전·종료 중에는 멈춘다.
- 현재 전원 설정은 `No Start On Batteries`·`Stop On Battery Mode`이다. 노트북이면 **AC 전원에 연결**한다.
- 로컬 프로젝트와 동일한 대화 문맥을 사용하므로 **Codex 데스크톱 앱을 실행하고 ChatGPT 계정에 로그인**해 둔다. 공식 문서도 로컬 프로젝트 예약 작업은 PC와 데스크톱 앱이 실행 중이어야 한다고 명시한다: https://learn.chatgpt.com/docs/automations.md
- Telegram·Supabase·Codex·Google Drive·Notion·웹 원문에 닿을 **인터넷 연결**이 필요하다. `.env.txt`의 전용 Heimdallr 봇 토큰·허용 chat ID·Supabase 키가 유효해야 하며 Drive·Notion 커넥터도 인증 상태여야 한다.
- PC가 끌 동안 Telegram 업데이트는 서버에 일시 보관되지만 **24시간을 넘지 않는다**. 장기 종료 중에 입력한 요청은 유실될 수 있다: https://core.telegram.org/bots/api#getting-updates
- 사용량이 부족하면 `working`·체크포인트를 유지하고 30분 heartbeat가 재개를 확인한다. 대기 작업이 없을 때 heartbeat가 `PAUSED`인 것은 정상이다.

입력은 허용된 Telegram **1:1 채팅**에서 사용자가 직접 보낸 한 줄이어야 한다. 기업은 정식 기업명·6자리 코드, 산업은 산업 카탈로그의 정확한 명칭만 받는다. `삼성전자`, `005930`, `반도체`는 유효하지만 `삼성전자 분석해줘`, 그룹 채팅, 전달 메시지, 일반 Codex 채팅 입력은 요청으로 접수하지 않는다.

## Codex 작업 처리

`codex queue`로 전달된 ID를 `python -m telegram_bridge.bridge poll`에서 확인한다. 실제 원문·update ID·`request_kind`가 있고 공식 자료로 대상이 식별되면 `claim ID` 후 `$kairos` 스킬을 실행한다. 일반 질문·인사·모호한 대상은 `reject ID`로 제외한다. `claim`은 `telegram_bridge/state/checkpoints/ID.md` 재개 장부를 한 번 생성하며 기존 장부를 덮어쓰지 않는다. 조사·원고·Notion 저장 단계마다 이 파일에 최근 3개월 Drive/Notion 선택 기록, 기존 분석 비교, 웹 출처, 주요 수치, 원고 경로, 페이지 ID/URL, 이미 검증한 항목과 다음 행동을 기록한다. 지정 양식의 부모와 전체 본문을 재조회한 후에만 `deliver ID --notion URL --industry 산업명`으로 개인 채팅에 버튼과 링크를 보낸다. 분석을 완료할 수 없으면 `fail ID --reason TARGET_AMBIGUOUS|SOURCE_ACCESS|WEB_RESEARCH|NOTION_WRITE|NOTION_VERIFY|UNEXPECTED`로 사용자에게 원인과 복구 방향을 표시한다.

`claim` 직후 접수 메시지는 최근 자료 선별 중으로 바뀐다. 이후 `python -m telegram_bridge.bridge progress ID --stage sources|industry|company|web|history|notion|verify`로 실제 단계와 진척률을 표시한다. 산업 요청에서는 불필요한 `company` 단계를 생략한다. 사용량이 소진되면 `--stage usage`를 기록한다. Telegram 편집 실패가 나도 로컬 단계 장부는 보존하고 다음 단계에서 다시 편집한다. `/status`에는 마지막 단계·갱신 시각을 보여 주고, 15분 넘게 갱신되지 않으면 확인 필요를 표시한다. 완료 시 접수 메시지를 완료로 바꾼 뒤 Notion 링크를 새 메시지로 보낸다.

분석은 **산업 구조·규모·성장률·현재 사이클·기술·수급·경쟁·밸류체인·시장의 기대 시점**부터 조사한다. 기업 요청은 이어서 기업의 매출·마진·현금흐름·가치평가와 연결하고, 산업 요청은 국내외 Peer·투자 가능한 가치사슬 단계·선행지표·시나리오를 연결한다. [산업분석 Drive 폴더](https://drive.google.com/drive/folders/1JchyHt19WRQacnLIDO1daQd3HLvfb15s)와 [기업분석 Drive 폴더](https://drive.google.com/drive/folders/17Kwbq5u7jiFb7jH14ddV0tI8zfyGcCsk)에서 분석일 기준 **최근 3개월 안의 자료만 현재 판단 근거로** 사용한다. Notion은 [SnowBall Heritage](https://app.notion.com/p/3d29c770aa61804783f2db8f1c9ddf4a), [1. 기업 투자 분석](https://app.notion.com/p/3d29c770aa6180469edceca9fb363529), [2. 산업 투자 분석](https://app.notion.com/p/3e69c770aa61808aa0e8e136d62dc59a)를 모두 참고 루트로 조회한다. 기업 요청은 동일 기업과 관련 산업, 산업 요청은 동일 산업과 실제 비교·추천할 기업의 완성 분석을 읽는다. 최근 3개월 본문은 현재 판단에, 오래된 직전 완성본은 변화 비교에만 쓰며 최신 원문으로 재검증한다. 작성 중·실패·이번 실행 페이지는 이전 분석으로 선택하지 않고 변경사항과 원본 링크를 보고서에 남긴다. `python -m src.collectors.telegram_sources search`의 읽기 전용 사용자 세션으로 [SungwooInsight](https://t.me/SungwooInsight)는 최근 72시간 전체를, [DOC_POOL](https://t.me/DOC_POOL)과 [sunstudy1234](https://t.me/sunstudy1234)는 최근 3개월을 대상명·티커·산업 별칭으로 검색한다. 채널 홈이 아니라 개별 게시물 영구링크와 실제 본문·첨부 파일을 원소스로 남기고, 첨부 보고서 수치는 다시 공식 원문과 교차 검증한다. 인증·권한이 없거나 관련 글이 없으면 각각 `⚠️ 직접 확인 필요` 또는 `관련 게시물 미확인`으로 기록하되 분석은 다른 신뢰 원문으로 완성한다. 중요 PDF 근거는 페이지·짧은 근거 문구를 장부에 저장하고 `src.analysis.source_evidence`로 원본을 덮어쓰지 않는 색상 강조 사본·페이지 이미지를 만든다. 보고서 링크는 검증된 페이지 딥링크를 우선하고 미지원 문서는 원문 링크+페이지 번호+강조 사본을 함께 둔다. 네이버 블로그 등 공개 투자자 글도 정확한 글 링크·작성일과 함께 조사하되 관점·반대논거에만 활용하고 핵심 수치는 1차 자료로 재검증한다. 프로젝트가 관련성을 확인했지만 본문·이미지·영상·문맥을 파악하지 못한 블로그·뉴스·Telegram은 누락하지 않고 `⚠️ 직접 확인 필요` 표에 이유와 직접 링크를 남긴다. 채널 제목만 보거나 게시물 원문을 못 열었으면 열람 성공으로 기록하지 않는다. 채널 접근 실패만으로 Notion 최종본 게시나 Telegram 링크 발송을 보류하지 않는다.

기업 보고서는 [1. 기업 투자 분석](https://app.notion.com/p/3d29c770aa6180469edceca9fb363529) 아래 `기업명 (코드·시장)` 페이지를 재사용하고 그 아래 날짜별 분석을 만든다. 기업 보고서는 [1_1. 기업 투자 분석 양식](https://app.notion.com/p/3d39c770aa6180b3b438d1fabe9db676), 산업 보고서는 [2_2. 산업 투자 분석 양식](https://app.notion.com/p/3e79c770aa6180e69466da9dd3d4abff)의 실행 시점 전체 본문을 읽고 순서·항목을 유지한다. 산업 결과는 [2. 산업 투자 분석](https://app.notion.com/p/3e69c770aa61808aa0e8e136d62dc59a) 아래 `🏭 산업명` 페이지를 재사용하고 그 아래 날짜별 분석을 만든다. 동일 대상의 기존 페이지는 중복 생성하지 않는다. 모든 대상에 반복 적용할 새 필수 항목이 확인되면 과거 보고서를 덮어쓰지 않고 해당 기본 양식과 Kairos 검증 규칙을 함께 갱신하며, 일회성 대상 특화 항목은 보고서에만 추가한다.

Notion 표·그래프의 제목, 열 이름, 지표, 단위, 범례와 설명은 한국어로 쓴다. 본문 상단 목차 블록은 넣지 않는다. 문장이 마침표로 끝나면 다음 문장은 새 줄·블록으로 시작하고 표 셀 안에서는 `<br>`로 나눈다. 네이버 증권의 기준일 종가와 주요 과거 상승·하락 구간을 그래프로 보여 주고, 날짜가 확인된 공시·실적·뉴스를 연결해 해석하되 원인으로 단정할 수 없는 부분을 밝힌다. Heimdallr `/stock/{code}`·네이버 증권·StockEasy 종목 직접 링크를 넣는다. Notion 저장 뒤 표 1개 이상의 한글 표기, 그래프 표시, 주가 기준·출처, 세 링크와 목차 생략을 재조회한다.

Peer Group 표와 본문에 실제로 언급된 모든 상장사는 종목명 셀·첫 언급에 네이버증권 종목 상세 링크를 연결한다. 국내 종목은 검증된 6자리 코드의 `https://finance.naver.com/item/main.naver?code={code}`를 쓰고 중복 제거한 `종목 바로가기` 표를 제공한다. 해외 종목은 네이버증권의 실제 상세 페이지를 확인한 경우만 연결하며, 코드·시장이 모호하면 추측하지 않고 확인 필요로 표시한다.

투자 판단, 시장 규모·성장률, 실적·가이던스·컨센서스, 계약·고객, 주가·밸류에이션, 촉매·위험·정책과 핵심 표·그래프에는 같은 문장·행 또는 바로 아래 `📎 원문`으로 실제 읽은 공시 본문·IR 자료·공식 통계표·보고서 직접 링크를 둔다. 검색 결과·기관 홈페이지·재배포 목록은 원문으로 세지 않는다. 접근 제한 자료는 제한 범위와 대체 공개 원문을 표시하며, 저장 후 핵심 링크가 해당 문서로 열리는지 확인한다.

`claim` 성공 직후 현재 Codex 작업에 연결된 기존 heartbeat `kairos`를 `ACTIVE`로 전환한다. 이 확인 작업은 `working` 동안만 반복된다. `sent` 이후 다른 `working`이 없으면 다음 확인 실행에서 스스로 `PAUSED`로 전환한다. 새 요청이 없을 때는 모델 사용량을 쓰지 않는다. 새 heartbeat를 요청마다 만들지 않는다.

사용량 제한으로 중단되면 `working`을 유지하고 장부에 중단 지점, 미완료 작업, 사용량 창의 재설정 시각을 남긴다. 이 Codex 작업에 연결된 반복 확인은 로컬 `poll`에서 `working`이 있을 때만 사용량을 확인한다. 사용 가능량이 돌아오면 **같은 ID와 장부**에서 이어서 수행한다. 장부가 없으면 `checkpoint ID`로 먼저 복구하고 이전 대화·Notion을 대조한다. 이미 만든 Notion 페이지가 있으면 재조회·수정하며 새 페이지를 중복 생성하지 않는다. `sending` 또는 `uncertain`은 발송 성공 여부를 확인하기 전 자동 재전송하지 않는다. `sent`는 재처리하지 않는다. 대기 작업이 없을 때 반복 확인은 조용히 종료한다. 로컬 컴퓨터와 Codex 앱이 실행 중이어야 심층 분석이 시작된다.

## 운영 확인

- `status`는 봇 ID와 로컬 큐 상태를 출력하며 토큰을 노출하지 않는다.
- `poll`은 로컬 큐만 읽고 Telegram·Supabase 네트워크를 쓰지 않는다.
- `checkpoint ID`는 `working` 작업의 장부만 만들며 기존 내용을 보존한다. `telegram_bridge/state/`는 Git에서 제외된다.
- Supabase `kairos_requests`는 service key만 접근한다. anon에 대한 SELECT 정책은 없다.
- Notion 완료 링크는 검증된 실제 페이지 URL이어야 한다.
