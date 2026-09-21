# Heimdallr Telegram → Kairos → Notion

Windows의 `HeimdallrTelegramListener`만 Telegram `getUpdates`를 1분마다 호출한다. 인증된 개인 채팅에서 종목명 또는 6자리 코드를 단독으로 입력하면 접수·예상 시간 메시지를 보내고 `kairos_requests`에 Telegram update ID로 심층 분석 요청을 기록한다. 짧은 종목 요약은 보내지 않는다. 수정·전달·그룹·봇 경유 메시지와 문장형 질의는 심층 분석 요청이 아니다. `/status`는 최근 요청 상태만 조회한다.

Windows의 `HeimdallrKairosCollector`는 Supabase의 `pending` 요청을 읽어 이 저장소의 로컬 SQLite 큐로 복사하고, `codex queue`로 지정 Codex 작업을 깨운다. claim이 없으면 5분 뒤 다시 깨운다. 이 수집기는 Telegram API를 폴링하지 않는다. 기존 `C:\Codex\Kairos` 봇·큐·미처리 작업은 건드리지 않는다.

## 설치

1. Heimdallr Supabase SQL Editor에서 `docs/migrations/kairos_requests.sql`을 적용한다. `python -m src.db.init`으로 service 읽기와 anon 비공개를 확인한다.
2. GitHub Actions `telegram_listen`을 비활성화하고 이 변경을 배포한다. 수신 작업을 설치하기 전에 DB 테이블을 먼저 적용한다. 두 수신기를 동시에 켜지 않는다.
3. 로컬 `.env.txt`에 Heimdallr 전용 봇 토큰(ID `8933940541`), 허용 개인 chat ID, Supabase URL과 service key가 설정됐는지 확인한다. 토큰 값은 출력하지 않는다. `.venv`에서 `pip install -e ".[dev]"`를 실행한다.
4. `python -m telegram_bridge.bridge configure-trigger --thread <이 Codex 작업 ID>`로 기존 작업을 등록한다.
5. `powershell -NoProfile -File telegram_bridge/install_listener.ps1`로 전용 봇 1분 수신 작업을 설치하고, `powershell -NoProfile -File telegram_bridge/install_collector.ps1`로 창 없는 1분 수집 작업을 설치한다. `telegram_bridge/state/listener_last.json`, `python -m telegram_bridge.bridge status`, `python -m telegram_bridge.bridge ingest`로 상태를 확인한다. 테스트 기업명을 보내거나 Notion 시험 페이지를 만들지 않는다.

## Codex 작업 처리

`codex queue`로 전달된 ID를 `python -m telegram_bridge.bridge poll`에서 확인한다. 실제 원문과 update ID가 있고 공식 자료로 기업이 식별되면 `claim ID` 후 `$kairos` 스킬을 실행한다. 일반 질문·인사는 `reject ID`로 제외한다. `claim`은 `telegram_bridge/state/checkpoints/ID.md` 재개 장부를 한 번 생성하며 기존 장부를 덮어쓰지 않는다. 조사·원고·Notion 저장 단계마다 이 파일에 출처, 주요 수치, 원고 경로, 페이지 ID/URL, 이미 검증한 항목과 다음 행동을 기록한다. 지정 양식의 부모와 전체 본문을 재조회한 후에만 `deliver ID --notion URL --industry 산업명`으로 개인 채팅에 버튼과 링크를 보낸다.

`claim` 직후 접수 메시지는 산업 조사 중으로 바뀐다. 이후 `python -m telegram_bridge.bridge progress ID --stage company|notion|verify`로 검증·작성·저장 확인 단계를 표시한다. 사용량이 소진되면 `--stage usage`를 기록한다. `/status`에는 마지막 단계·갱신 시각을 보여 주고, 15분 넘게 갱신되지 않으면 확인 필요를 표시한다. 완료 시 접수 메시지를 완료로 바꾼 뒤 Notion 링크를 새 메시지로 보낸다.

분석은 해당 기업의 **산업 구조·규모·성장률·기술·수급·경쟁·밸류체인**을 먼저 조사하고, 기업의 매출·마진·현금흐름·가치평가와 연결한다. [산업분석 Drive 폴더](https://drive.google.com/drive/folders/1JchyHt19WRQacnLIDO1daQd3HLvfb15s)에서 해당 산업을, [기업분석 Drive 폴더](https://drive.google.com/drive/folders/1vnIBkOaoPcL3pC1n-V-LNUNJJhIm6hyd)에서 해당 기업을 찾아 분석일 기준 **최근 3개월 안의 가장 최신 자료**를 우선 확인한다. 매 요청마다 [DOC_POOL](https://t.me/DOC_POOL)과 [sunstudy1234](https://t.me/sunstudy1234)에 각각 실제 접근·기업명/티커/산업명 검색을 시도한다. 접근이 막힌 채널은 더 이상 시도하거나 다른 로그인 경로를 찾지 않는다. 실패 범위를 장부에 남기고 공개 증권사 리서치센터·보고서 배포처·공시·회사 IR·산업 통계 등 다른 자료로 분석을 완성한다. 채널 제목만 보거나 게시물 원문을 못 열었으면 열람 성공으로 기록하지 않는다. 공시·회사 IR로 핵심 수치를 교차 검증한다. 채널 접근 실패만으로 Notion 최종본 게시나 Telegram 링크 발송을 보류하지 않는다.

Notion 표·그래프의 제목, 열 이름, 지표, 단위, 범례와 설명은 한국어로 쓴다. 본문 상단 목차 블록은 넣지 않는다. 문장이 마침표로 끝나면 다음 문장은 새 줄·블록으로 시작하고 표 셀 안에서는 `<br>`로 나눈다. 네이버 증권의 기준일 종가와 주요 과거 상승·하락 구간을 그래프로 보여 주고, 날짜가 확인된 공시·실적·뉴스를 연결해 해석하되 원인으로 단정할 수 없는 부분을 밝힌다. Heimdallr `/stock/{code}`·네이버 증권·StockEasy 종목 직접 링크를 넣는다. Notion 저장 뒤 표 1개 이상의 한글 표기, 그래프 표시, 주가 기준·출처, 세 링크와 목차 생략을 재조회한다.

`claim` 성공 직후 현재 Codex 작업에 연결된 기존 heartbeat `kairos`를 `ACTIVE`로 전환한다. 이 확인 작업은 `working` 동안만 반복된다. `sent` 이후 다른 `working`이 없으면 다음 확인 실행에서 스스로 `PAUSED`로 전환한다. 새 요청이 없을 때는 모델 사용량을 쓰지 않는다. 새 heartbeat를 요청마다 만들지 않는다.

사용량 제한으로 중단되면 `working`을 유지하고 장부에 중단 지점, 미완료 작업, 사용량 창의 재설정 시각을 남긴다. 이 Codex 작업에 연결된 반복 확인은 로컬 `poll`에서 `working`이 있을 때만 사용량을 확인한다. 사용 가능량이 돌아오면 **같은 ID와 장부**에서 이어서 수행한다. 장부가 없으면 `checkpoint ID`로 먼저 복구하고 이전 대화·Notion을 대조한다. 이미 만든 Notion 페이지가 있으면 재조회·수정하며 새 페이지를 중복 생성하지 않는다. `sending` 또는 `uncertain`은 발송 성공 여부를 확인하기 전 자동 재전송하지 않는다. `sent`는 재처리하지 않는다. 대기 작업이 없을 때 반복 확인은 조용히 종료한다. 로컬 컴퓨터와 Codex 앱이 실행 중이어야 심층 분석이 시작된다.

## 운영 확인

- `status`는 봇 ID와 로컬 큐 상태를 출력하며 토큰을 노출하지 않는다.
- `poll`은 로컬 큐만 읽고 Telegram·Supabase 네트워크를 쓰지 않는다.
- `checkpoint ID`는 `working` 작업의 장부만 만들며 기존 내용을 보존한다. `telegram_bridge/state/`는 Git에서 제외된다.
- Supabase `kairos_requests`는 service key만 접근한다. anon에 대한 SELECT 정책은 없다.
- Notion 완료 링크는 검증된 실제 페이지 URL이어야 한다.
