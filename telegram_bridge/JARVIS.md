# JARVIS G·H·I·J절 운영·설치 (2026-10-08)

## N절 최종 분석만 Notion 게시·PPT 직전 승인 (2026-10-11)

새 Telegram/JARVIS 분석은 Codex 전체 분석 파일 → 자동 Claude 검증·공백 보완 → 최종 Notion 전체 저장·재조회 → PPT 선택 순서다. 사용자 최신 결정으로 아래 K절의 Codex Notion·Claude 승인 버튼 규칙을 대체한다. 실행 정본은 `optimization_policy.md` N절이다. 기존 sent 분석/PPT는 그대로 보존한다.

Codex는 실제 양식 전체·기존 분석을 읽고 중간 Notion 없이 원고·표·차트·공식 원문·템플릿 전체 snapshot과 SHA-256을 보존한다. `handoff` 뒤 `complete-codex ID --industry 산업명`으로 인계한다. 부모 요청은 원격 working/stage=claude, 로컬 claude이며 Codex 재접수 대상에서 제외한다. 인계 장애는 기존 collector와 유일 큐 인덱스로 같은 ID에서 복구한다. DB 스키마/RPC 변경과 새 자동화는 없다.

Claude는 모든 gap 검색/분석 시도, 핵심 원문 독립 검증, Codex 최초 판단/Claude 검증/변경·유지 근거 비교 표와 검수 JSON을 남긴다. 실파일·gap-review·comparison-review·실제 Notion page/blocks/ancestors 전체 재조회를 통과한 검증 마커 이후에만 부모 sent를 기록한다. 최종 상태 전환 장애는 마커에서 복구하며 분석을 다시 생성하지 않는다. Telegram에는 자동 접수/시작·사용량 중단/재개·최종 Notion 링크와 PPT 버튼을 알리고, PPT는 버튼 클릭 후에만 만든다. source=jarvis에는 Heimdallr 메시지·awaiting_input 없이 기존 JARVIS 알림과 PPT 선택을 유지한다.

## M절 이벤트 기반 접수 전환 점검 (2026-10-11)

`python -m telegram_bridge.intake_readiness --check`는 실제 구독 사용량과 기존 대화 상태를 읽기만 한다. 모델 호출·turn/start·queue·claim·발송은 하지 않는다. 현재 Windows의 공유 app-server control socket은 OS 10050로 연결 실패했다. 독립 stdio 서버의 사용량 조회는 성공했지만 실행 중인 데스크톱 대화를 notLoaded로 표시하므로 동시 실행 판정에 사용하지 않는다.

`--enable-shadow`는 기존 collector에 실제 pending/working 요청이 있을 때만 10분 간격의 읽기 전용 전환 점검을 연결한다. 빈 큐에서는 app-server 프로세스·계정 조회·모델 호출을 하지 않는다. sending/uncertain/awaiting_input은 대체 실행 대상에서 제외한다. 진단 오류는 collector를 중단시키지 않는다. 설정 해제는 로컬 settings의 intake_readiness_enabled를 0으로 변경한다.

결과는 `state/intake-readiness.json`에 사용량 창·checked_at·request_id·공유 연결 상태만 저장한다. 토큰·원시 프로토콜 오류·대화 본문을 저장하지 않는다. 자동 dispatch는 구현·활성화하지 않았으며 kairos-intake는 ACTIVE, 과거 kairos는 PAUSED를 유지한다. 실제 공유 서버에서 기존 대화의 active/idle 판정, Notion/Drive 도구와 권한 보존, 미열림 대화의 실제 요청 시작·claim 및 사용량 회복 재개를 검증한 뒤에만 heartbeat를 대체한다. 독립 서버 조회 성공이나 queue 종료0을 전환 성공으로 세지 않는다.

## K절 Telegram 후속 버튼 확장 (2026-10-09)

Telegram 직접 요청에도 같은 JARVIS Claude 지침·구독 실행기·자료 장부를 연결한다. 자동 Claude 시작은 하지 않으며 Codex 완료의 🧠 버튼, Claude 완료의 🎤 버튼이 각각 실행 승인이다.
기업·산업 발표자료는 실제 PPTX를 해당 Notion 대상 부모에 저장한다. PDF는 미리보기이며 본문형 슬라이드만으로 성공을 선언하지 않는다.
기존 company-only 검사를 실행기에서 기업/산업으로 확장한다. Telegram 접수는 service_role의 기존 테이블·유일 인덱스를 사용하므로 운영 SQL 변경이 필요 없다. 기존 JARVIS 기업 🎤 RPC·자동 analysis는 그대로 유지된다.
기업 양식과 산업20장 매핑·실제 파일 첨부/재조회 계약은 `telegram_bridge/presentation_workflow.md`다. PPT 성공 JSON에는 같은 요청의 `proof_path`가 필요하다.
기존 완료 코세스893060873의 Telegram145 버튼만 사용자 지시로 수정한다. 수정은 새 분석 접수가 아니다. 버튼을 클릭할 때만 후속 작업을 생성한다.

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
   무인 운영은 선택적으로 `claude setup-token`을 직접 실행해 발급한 구독 토큰을 실제 로드 파일의 `CLAUDE_CODE_OAUTH_TOKEN`에 저장할 수 있다. 토큰을 채팅·로그·Git에 남기지 않는다. [공식 인증 설명](https://code.claude.com/docs/en/authentication)을 따른다.
   환경 OAuth 토큰이 만료됐으면 새 setup-token으로 교체하거나 그 변수를 비운 후 구독 로그인으로 돌아간다. 단순 토큰 존재나 auth status의 loggedIn만으로 실제 호출 성공을 보장하지 않는다.
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
사용량 제한은 pending으로 되돌리고 retry_after 30분, 사용량 소진은 실패 상한을 소모하지 않고 같은 ID로 자동 재개한다.

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
- Telegram 리서치 채널·게시물·첨부·재배포 링크는 분석 소스에서 제외한다(2026-10-07 사용자 결정). 검색·인증을 요구하지 않고 과거 체크포인트·sources의 Telegram 자료도 분석 근거로 사용하지 않는다. 같은 보고서가 필요하면 공시·IR·증권사 등 원 발행기관에서 직접 확보한다.
- 실제 기업/산업 요청부터 Notion·Drive·JARVIS 알림·발표자료까지는 사용자 실제 요청으로 검증한다. 시험 Notion 페이지·시험 운영 분석 요청·유료 생성은 하지 않았다.


## J절: 대화를 열지 않는 자동 접수 (2026-10-07)

- 전용 대화: `Kairos 자동 분석 전용` (`01a11689-cd7f-7fb0-bc8d-af71da3a7d4b`). 과거 대화는 참고용으로 보존하고 trigger를 새 대화로 변경했다.
- 앱 heartbeat `kairos-intake`: ACTIVE, Asia/Seoul 07:00–23:00 매 정각(60분 간격). 과거 사용량 회복용 `kairos`는 PAUSED다.
- configure-trigger의 `--mode heartbeat`는 수집기의 queue 발송·확인 후 재개 queue도 차단한다. 예약 턴만 접수·재개하여 중복 실행을 방지한다.
- poll 한 번 → 빈 큐면 추가 도구 없이 종료. 작업이 있으면 모든 사용량 창 잔여 10% 이상 및 ordinaryUsageAllowed를 확인한다. working 우선, 없으면 가장 오래된 pending 한 건을 claim한다. 사용량 부족은 같은 상태·장부로 다음 실행까지 기다린다.
- 실제 요청은 WORKFLOW와 Kairos 스킬에 따라 Notion 저장·재조회·deliver/fail까지 처리한다. source=jarvis는 Heimdallr 메시지 없이 sent→H절 analysis→JARVIS 알림으로 연결한다. Telegram 리서치는 제외한다.
- PC·앱·로그인·네트워크 유지가 필요하다. 사용자가 전용 대화를 직접 열 필요는 없다. 유휴 heartbeat도 사용량이 발생할 수 있어 1회 실측 20,000 토큰 초과이면 30분으로 조정한다.
- 선택 J3의 파일 status 변경 실험은 하지 않고 앱 API로 등록한 intake를 ACTIVE 유지한다. 앱 내부 SQLite는 수정하지 않는다.

첫 유휴 실측은 캐시포함170,563토큰(캐시165,120·비캐시+출력5,443)이므로 J절 기준에 따라 현재 간격은30분이다. 실제 -1 Codex Notion과 JARVIS 완료 알림은 확인했으며 Claude A1은 구독 재인증이 필요하다. 상세 운영 증거는 docs/sessions/2026-10-07-jarvis-intake.md에 보존한다.


## L절 사용량 최적화·자료 공백·자동 재개 (2026-10-11)

정본은 `optimization_policy.md`이며 기존 상충 규칙보다 우선한다. 새 claim은 handoff-v1 패키지를 만들고 deliver 전에 검사한다. Claude는 모든 gap를 직접 검색·분석 시도하고 gap-review 전체 커버리지 및 Notion 전체 재조회 proof를 검증한다. 산업/기업 모두 전체 하위 폴더에서 최근 달력상 3개월 발행 자료를 쓴다. 산업 PDF 보존 목적지는 기존 bootstrap이다. 사용량은 실패 상한과 분리하여 무기한 대기·동일 ID 자동 재개한다. Codex usage-wait/usage-resume, Claude USAGE pending 및 중단/재개 주기별 Telegram 알림, source=jarvis 무발송을 적용한다. 실제 프로세스가 살아 있거나 종료 확인 불가면 중복 재실행하지 않는다. 새 실행의 worker/CLI PID 종료가 확인되면 기존 세션을 이어서 재시도한다. 미완료 중간 보고 RESULT_MISSING은 기존 세션에서 기술 재시도 상한 안에서 보완한다. 기존 sent는 재접수하지 않는다.
