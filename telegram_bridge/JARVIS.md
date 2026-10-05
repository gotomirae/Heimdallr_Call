# JARVIS G·H·I절 운영·설치 (2026-10-06)

PRD Ref: §8.7 G·H·I · 사용자 D59·D60·D61. 시험용 Notion 페이지는 만들지 않는다.

## 구현 파일

- DB: `docs/migrations/kairos_jarvis.sql`, `src/db/schema.sql`, `src/db/init.py`.
- 큐·수신: `telegram_bridge/bridge.py`, `src/notify/kairos_requests.py`, `src/notify/listen.py`.
- 자료: `src/collectors/drive_bootstrap.py`, `src/collectors/sec_edgar.py`, `telegram_bridge/jarvis_registry.py`.
- 설정: `config/industry_folders.yaml`, `config/us_company_aliases.yaml`, `src/config/constants.py`, `.env.example`, `pyproject.toml`.
- 발표자료·검증: `telegram_bridge/deck_runner.py`, `telegram_bridge/notion_readback.py`, `src/utils/env.py`, `telegram_bridge/install_jarvis.ps1`.
- 회귀: `tests/test_jarvis_kairos.py`, `tests/verification/jarvis_rpc.mjs`.
- 검증 임시물 제외: `.gitignore`.
- 규약·기록: `docs/PRD.md`, `docs/decisions/030-jarvis-kairos-us-deck.md`, `docs/traps.md`, `docs/sessions/2026-10-05-jarvis-g.md`, `AGENTS.md`, `telegram_bridge/WORKFLOW.md`.

## 사용자가 직접 할 일 — 순서대로

1. **Heimdallr Supabase SQL Editor**에서 `docs/migrations/kairos_jarvis.sql` 전체를 실행한다.
   기존 Kairos 테이블·Drive 확인 마이그레이션이 없는 새 설치만 먼저 `kairos_requests.sql`, `kairos_drive_confirmation.sql`을 실행한다.
   신규 설치는 G 다음 `docs/migrations/kairos_claude.sql`(H)을 적용한다. 기존 G 운영 업데이트는 H만 적용한다.
   H까지 적용한 뒤 G만 재실행하면 mode 유일 인덱스·RPC가 구형으로 되돌아가므로 전체 재적용은 반드시 G→H 순서다. Vault `heimdallr_jarvis_token`은 그대로 사용한다.
   Heimdallr 로컬에 JARVIS 토큰을 복사하거나 추가 환경변수로 넣을 필요가 없다.
   JARVIS Vercel의 기존 `HEIMDALLR_JARVIS_TOKEN`도 변경하지 않는다.
2. 프로젝트의 실제 로드 파일(`.env`가 있으면 그 파일, 없으면 `.env.txt`)에 다음 한 줄을 추가한다.
   `SEC_USER_AGENT=Heimdallr/1.0 (본인의 실제 이메일)`
   OpenDART·Supabase 기존 환경변수는 그대로 사용한다. 미국 SEC 명부·자료 수집에만 새 설정이 필요하다.
3. 이 PC의 일반 Windows 사용자 로그인 세션에서 Google Drive for Desktop을 실행하고
   `G:\내 드라이브\1. 주식 자본\2. 아이언맨의 투자 분석`을 열 수 있는지 확인한다.
   Claude Code에 `claude auth login`으로 **구독 로그인**한다. API 키는 사용하지 않는다.
   PowerPoint 데스크톱과 기존 `%USERPROFILE%\.claude\skills\kairos-deck\SKILL.md`를 확인한다.
4. PowerShell에서 아래 명령을 순서대로 실행한다.

```powershell
Set-Location C:\Codex\Heimdallr_Call_Codex
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& .\.venv\Scripts\python.exe -X utf8 -m src.db.init
& .\.venv\Scripts\python.exe -X utf8 -m telegram_bridge.jarvis_registry
powershell -NoProfile -ExecutionPolicy Bypass -File .\telegram_bridge\install_jarvis.ps1
```

설치기는 DB·Drive·SEC 명부·Claude 구독 로그인·PowerPoint를 확인한 뒤 기존
`HeimdallrKairosCollector`를 갱신하고 `HeimdallrKairosDeckRunner`를 1분 간격으로 설치한다.
발표자료 작업은 창 없이 실행하며, 로그인한 사용자 세션에서만 돌고, 겹친 실행은 무시한다.
기존 Telegram listener는 유지한다. PC가 켜져 있고 로그인·절전 해제 상태여야 한다.
기존 collector의 `configure-trigger --thread` 설정은 유지된다.
`bridge poll`의 `trigger_configured=true`를 확인하고, false일 때만 실제 Kairos 채팅 ID로 설정한다.

5. **실제 JARVIS 추천의 🏢 또는 🏭 버튼**으로 검증한다.
   같은 대상을 두 번 누르면 같은 요청 ID의 진행 상태를 사용한다.
   Codex Notion 완료 후 자동 🧠 진행·완료 알림과 같은 기업/산업 부모의 Claude Notion 및 Drive MD를 확인한다.
   기업은 🧠 완료 뒤 JARVIS의 🎤 버튼으로 발표자료를 요청한다. 산업은 🧠 top_pick의 🏢 기업 분석 버튼을 확인한다.
   기업 Drive 폴더의 PPTX·PDF·MD 3개, 기존 기업 Notion 페이지의 첨부,
   DB `sent`와 JARVIS 30분 상태 알림을 확인한다.
   이 단계에서는 실제 요청만 사용하고 시험용 페이지를 만들지 않는다.

잘못된 토큰 검사는 SQL Editor에서 다음 **읽기 RPC**로 가능하다. 기대 결과는 `unauthorized`다.
`select public.jarvis_analysis_status('deliberately-wrong', array[]::bigint[]);`
실제 Vault 값은 출력하지 않는다.

## 요청 계약과 재사용

JARVIS의 세 RPC 이름·입력·반환은 G절 계약을 따른다.
음수 ID·`source=jarvis`·`chat_id=user_id=0`이 모두 맞는 요청만 로컬에 복사한다.
Telegram 출처에는 기존 개인 채팅 인증을 유지한다.
`market=US`는 `code=NULL`·SEC 확인 `ticker`를 사용한다.

동일 대상 진행 요청을 먼저 반환한다. 완료본은 30일과 입력 `reuse_after` 중 더 엄격한 경계를 사용한다.
기업은 그 이후 국내 실적 공시 또는 미국 SEC 실적 공시가 있으면 재사용하지 않는다.
공시일만 있는 자료는 그 날 종료 시각을 기준으로 보수적으로 재사용을 막는다.
미국 명부는 하루 캐시, 실제 요청된 미국 종목의 실적 이력도 매일 확인하고 claim에서도 확인한다.
Drive 자료를 재사용한 첫 요청도 즉시 다음 완료본 재사용을 판단할 수 있도록 SEC 실적 확인 시각을 기록한다.
명부가 2일 이상 오래됐거나 실적 확인이 하루 이상 오래됐으면 미국 재사용을 막는다.
열린 JARVIS 요청 6건 제한·중복 검사는 같은 트랜잭션 잠금 안에서 실행한다.

산업은 YAML의 명시 매핑과 숫자·공백·밑줄·하이픈 정규화를 우선한다.
의료기기·OLED·네트워크·의류는 기업 DB 업종/섹터의 명시 토큰으로만 세부 매핑한다.
미매핑 산업은 실제 최대 번호 다음 폴더와 날짜 폴더를 만들고 YAML·체크포인트에 남긴다.
매핑을 수정하면 `telegram_bridge.jarvis_registry`를 실행해 RPC에도 반영한다.
JARVIS 요청은 DB 제약으로도 `awaiting_input`이 금지된다.
이 결정은 ADR 21의 사용자 확인 규칙을 **명시 매핑·자동 신규 생성 범위에서** 대체한다.

## Kairos 실행 지침 (Codex 큐가 읽는 정본)

이 문서는 G절 사용자 지시를 코드와 함께 보존한다. 기존 Kairos의 Telegram-only 시작 규칙보다
이번 사용자의 직접 지시가 우선한다. `source=jarvis`는 Vault 토큰으로 인증된 실제 사용자 버튼 요청이다.
큐 원문을 대조하고 claim 성공 후 실행한다. 일반 Codex 예시·설정 요청으로 분석을 시작하지 않는다.

- `claim` 직후 Drive bootstrap 장부(`ID.drive.json`)를 읽는다.
  준비·다운로드 실패는 출처 한계로 기록하고 웹·공시로 보완한다.
  파일명에 발행일이 없는 자료는 수정일로 최근자료라고 판정하지 않는다. 실제 본문 날짜 확인 전에는 자동 재사용을 막는다.
  자동 산업 공통 수집은 하지 않는다. 실제 읽은 산업 PDF만 지정 날짜 폴더에 복사하고 URL·발행일·해시를 기록한다.
- 산업→기업 조사, 기존 Notion 양식·부모·직전 분석 비교는 기존 Kairos 규칙을 따른다.
  미국 기업 제목은 `기업명 (TICKER·NASDAQ|NYSE)`이며 SEC 시장을 사용한다.
  미국의 네이버 링크는 실제 확인한 것만 넣고 국내 `/stock/{code}`를 티커로 만들지 않는다.
- `progress`는 JARVIS의 `stage/stage_updated_at`을 원격 DB에 먼저 기록한다.
  `fail`은 오류 코드를 기록한다. Heimdallr 봇 접수·진행·완료·실패 메시지를 보내지 않는다.
- Notion 저장 후 **실제 connector로** 페이지·모든 본문 블록·상위 페이지를 재조회한다.
  저장된 응답과 확인 결과를 `telegram_bridge/state/checkpoints/ID-notion.json`에 기록하고 `deliver`한다.
  다음 형식은 증빙의 형태만 보이는 예시이며 페이지 생성 지시가 아니다.

```json
{
  "request_id": -1,
  "checked_at": "재조회한 실제 UTC ISO 시각",
  "page": { "id": "재조회 결과의 실제 페이지 ID", "archived": false, "in_trash": false },
  "blocks": { "results": ["실제 재조회 블록 객체 전체"], "has_more": false },
  "ancestors": [{"id": "상위 기업/산업 페이지 ID"}, {"id": "지정 기업/산업 루트 ID"}],
  "template_verified": true,
  "sources_verified": true,
  "target_verified": true
}
```

여러 블록 페이지는 끝까지 읽어 `results`를 합친다.
기업 루트는 `3d29c770aa6180469edceca9fb363529`, 산업 루트는 `3e69c770aa61808aa0e8e136d62dc59a`.
이 파일은 connector 재조회 기록을 검증하는 로컬 증빙이며 별도 Notion API 키를 요구하지 않는다.
15분이 지나면 다시 재조회한다. JARVIS `deliver`는 증빙과 URL/ID/부모/본문을 대조한 뒤 `sent`만 저장한다.
중간 확인이나 Telegram 발송은 없다.

## 발표자료 장부와 복구

DB 원자 claim과 단일 working 인덱스로 동시에 1건만 실행한다.
Claude는 API 키·외부 LLM endpoint 변수를 상속받지 않고 저장된 구독 로그인으로 실행한다.
120분 제한, 출력 JSON 래퍼의 result 안에 있는 최종 JSON도 지원한다.
fallback 파일은 이번 실행 이후이고 `request_id=D<id>`가 같은 `result.json`만 인정한다.
성공은 Notion URL·Drive 디렉터리·PPTX/PDF/MD 실파일 존재를 대조한다.
사용량 제한은 pending으로 되돌리고 retry_after 30분, 4번째 한도 실패는 USAGE로 종료한다.

`telegram_bridge/state/decks/D<id>.json`은 DB 기록 전에 결과를 보존한다.
최근 worker 상태/설정 실패는 `telegram_bridge/state/decks/worker.json`에 남긴다.
PC 종료·프로세스 장애로 working이 남으면 자동 재실행하지 않는다.
기존 Claude 프로세스가 끝났는지와 실제 파일·Notion 첨부를 먼저 확인한 뒤 해당 요청만 복구한다.
Windows 시간 초과에서 프로세스 트리 종료를 확인하지 못하면 working/TIMEOUT_TREE_UNCERTAIN을 유지해
중복 발표자료 실행을 막는다.

## 검증 기록과 한계

- 기존·신규/기준 스키마 집중 회귀 최종 105개 통과; 전체 오프라인 1,251 passed·2 skipped·3 network deselected.
- 임시 PostgreSQL(PGlite)에서 SQL 2회 적용·22/22 계약 검사 성공.
  Vault는 fixture-only 가짜 값으로 대체했으며 운영 토큰을 읽지 않았다.
- 실제 OpenDART 한화에어로스페이스 최근 4기간 PDF: 4/4, 7,858,602바이트, 2,048페이지, 실패 0.
  임시 .cache에만 저장했다. 실제 IR 첨부 미확인은 결측으로 유지했다.
- 운영 DB 읽기: source/market 컬럼 오류 42703 → G SQL 미적용.
- SEC_USER_AGENT 미설정 → 미국 라이브 다운로드 미검증.
- Claude 구독 로그인 조회: loggedIn=false → 실제 발표자료 생성 미검증.
- 별도 KIND 실제 연결 검사 3/3 통과, 깨끗한 production 설치와 새 모듈 실제 import 성공, PowerShell 구문 오류 0.
- Codex 샌드박스에서는 G 드라이브 접근 거부. 운영 Drive 저장·실제 JARVIS 버튼→Notion→PPT 종단 검증은
  위 설치 이후 실제 요청으로 확인해야 한다. 시험용 Notion·분석 요청·유료 생성 0건.

SQL 검증을 재현하려면 아래는 **임시 테스트 의존성**으로만 사용한다.

```powershell
npm.cmd install --prefix .cache/pg-jarvis @electric-sql/pglite --no-audit --no-fund
node tests/verification/jarvis_rpc.mjs
```

SEC 명부·submissions 경로와 속도 정책은
[SEC API 문서](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)와
[공식 개발자 자료](https://www.sec.gov/about/developer-resources)를 확인했다.


## 2026-10-05 Windows 설치 확인

Windows PowerShell 5.1을 위해 install_jarvis.ps1의 UTF-8 BOM을 유지한다. 로그인 검사는 claude_login.py 파일로 실행한다. 두 1분 예약 작업을 실제 등록하고 collector 성공 및 deck worker idle을 확인했다. 설치 복구 실측은 docs/sessions/2026-10-05-jarvis-install.md에 기록했다.


## H·I 적용 결과 (2026-10-06)

- H 운영 SQL 적용 성공. 카탈로그 14/14, 잘못된 토큰 차단 6/6, DB 19개 테이블·새 3컬럼 확인.
- Claude 자동 큐는 JARVIS의 새로운 sent 전환에만 생성한다. 기존 sent를 소급 접수하지 않는다. 기존 Telegram 요청은 Codex 분석만 한다.
- 분석 90분/발표자료 120분, 동일 요청 analysis 우선, 전체 Claude 작업 단일 실행. 최신 성공 MD와 Claude Notion을 deck에 전달한다.
- 로컬 체크포인트·Drive bootstrap 장부·sources는 kairos_requests.update_id와 같은 로컬 ID로 찾는다. Claude 큐의 A/D 일련번호와 혼동하지 않는다.
- 기존 1분 예약 작업이 수정된 실행기를 사용하므로 재설치할 필요 없다. 실제 Claude 작업 0건·실행기 idle·최근 종료 코드 0 확인.
- I 규칙은 사용자 Kairos SKILL.md·references/source-policy.md와 WORKFLOW.md·PRD.md에 반영했다. 2_1·Invest_WiKi 내용 날짜(날짜 속성→유효 제목 날짜→생성일), 최근 달력상 3개월, 허브 항목별 판정과 출처 장부를 적용한다.
- Telegram 리서치 세션은 not_configured. 사용자가 실제 .env.txt에 TELEGRAM_RESEARCH_API_ID/HASH를 설정한 후 `.venv\Scripts\python.exe -X utf8 -m src.collectors.telegram_sources auth` 1회로 인증한다. 비밀 값은 채팅에 보내지 않는다.
- 실제 기업/산업 요청부터 Notion·Drive·JARVIS 알림·발표자료까지는 사용자 실제 요청으로 검증한다. 시험 Notion 페이지·시험 운영 분석 요청·유료 생성은 하지 않았다.
