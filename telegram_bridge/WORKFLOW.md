# Heimdallr Telegram → Kairos → Notion

Heimdallr의 기존 GitHub Actions 수신기만 Telegram `getUpdates`를 호출한다. 인증된 개인 채팅에서 종목명 또는 6자리 코드를 단독으로 입력하면 기존 짧은 실적 리포트를 보내고 `kairos_requests`에 Telegram update ID로 심층 분석 요청을 기록한다. 수정·전달·그룹·봇 경유 메시지와 문장형 질의는 심층 분석 요청이 아니다.

Windows의 `HeimdallrKairosCollector`는 Supabase의 `pending` 요청을 읽어 이 저장소의 로컬 SQLite 큐로 복사하고, `codex queue`로 지정 Codex 작업을 한 번 깨운다. 이 수집기는 Telegram API를 폴링하지 않는다. 기존 `C:\Codex\Kairos` 봇·큐·미처리 작업은 건드리지 않는다.

## 설치

1. Heimdallr Supabase SQL Editor에서 `docs/migrations/kairos_requests.sql`을 적용한다. `python -m src.db.init`으로 service 읽기와 anon 비공개를 확인한다.
2. 이 변경을 배포해 `.github/workflows/telegram_listen.yml`이 새 수신 코드를 실행하도록 한다. 수신 작업을 배포하기 전에 DB 테이블을 먼저 적용한다.
3. 로컬 `.env.txt`에 Heimdallr 전용 봇 토큰(ID `8933940541`), 허용 개인 chat ID, Supabase URL과 service key가 설정됐는지 확인한다. 토큰 값은 출력하지 않는다. `.venv`에서 `pip install -e ".[dev]"`를 실행한다.
4. `python -m telegram_bridge.bridge configure-trigger --thread <이 Codex 작업 ID>`로 기존 작업을 등록한다.
5. `powershell -NoProfile -File telegram_bridge/install_collector.ps1`로 창 없는 1분 수집 작업을 설치한다. `python -m telegram_bridge.bridge status`와 `python -m telegram_bridge.bridge ingest`로 상태를 확인한다. 테스트 기업명을 보내거나 Notion 시험 페이지를 만들지 않는다.

## Codex 작업 처리

`codex queue`로 전달된 ID를 `python -m telegram_bridge.bridge poll`에서 확인한다. 실제 원문과 update ID가 있고 공식 자료로 기업이 식별되면 `claim ID` 후 `$kairos` 스킬을 실행한다. 일반 질문·인사는 `reject ID`로 제외한다. 원고·출처·Notion 페이지 ID·검증 단계를 작업 장부에 보존하고, 지정 양식의 부모와 전체 본문을 재조회한다. 저장 검증 후에만 `deliver ID --notion URL --industry 산업명`으로 개인 채팅에 버튼과 링크를 보낸다.

`working` 작업은 동일 장부에서 재개한다. `sending` 또는 `uncertain`은 발송 성공 여부를 확인하기 전 자동 재전송하지 않는다. `sent`는 재처리하지 않는다. 로컬 컴퓨터와 Codex 앱이 실행 중이어야 심층 분석이 시작된다.

## 운영 확인

- `status`는 봇 ID와 로컬 큐 상태를 출력하며 토큰을 노출하지 않는다.
- `poll`은 로컬 큐만 읽고 Telegram·Supabase 네트워크를 쓰지 않는다.
- Supabase `kairos_requests`는 service key만 접근한다. anon에 대한 SELECT 정책은 없다.
- Notion 완료 링크는 검증된 실제 페이지 URL이어야 한다.
