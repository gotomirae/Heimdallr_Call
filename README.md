# Heimdallr_Call 🛡️

KOSPI/KOSDAQ 시가총액 1,000억원 이상 약 1,300종목을 대상으로,
**분기실적이 실제로 가속되고 있으면서 그 사실이 아직 주가에 반영되지 않은 종목**을
매 분기 자동 발굴해 전용 텔레그램 봇(🛡️ 아이언맨의 Heimdallr)과 대시보드로 전달한다.

- 설계 문서: [`docs/PRD.md`](docs/PRD.md) — **구현 전에 해당 절을 읽는다**
- 함정 목록: [`docs/traps.md`](docs/traps.md) — **새 모듈 만들기 전 필독**
- 현재 작업 지침: [`AGENTS.md`](AGENTS.md) · 과거 Phase 기록: [`docs/phases.md`](docs/phases.md)

현재 상태: **P0~P11 및 대시보드 운영 구현 완료**. 2026-08-27에 기존 UI와 분석 payload를
유지한 채 Anthropic/OpenAI Provider Adapter를 추가했다. 운영 기본 Provider는 동일 replay와
canary 검증 전까지 Anthropic이다. 2026-08-28에는 저장된 Provider 결과를 같은 입력으로
채점하는 offline replay 평가기와 **무쓰기 단건 canary 가드**를 추가했다. exact request
snapshot을 남긴 Terra Attempt 3은 실측 **$0.092068 · 90/100**이었지만, 공시 숫자를
`26,737백만원 → 267억원`으로 모델이 환산해 factual hard failure가 났다(T114).
이후 운영·canary 저장 경계에 같은 숫자 grounding gate를 연결해, 같은 문제가 재발하면
비용과 raw payload는 기록하되 분석 DB에는 저장하지 않는다. 미래 시나리오 임계값은 허용한다.
투자판단 영역별 재평가에서는 **92.14/100**이지만 이는 rubric 변경 결과이며 모델 개선 비교가
아니다. 개선 원인 100% · 지속성 66.7% · 주가 미반영 66.7% · catalyst 100% · risk 100%였고,
근거 없는 `267억원` 때문에 여전히 품질 실패다. 2026-08-29에는 실제 4종목의 evidence anchor를
사람이 대조해 사례집 대표성(4업종·4개 등급/컨센서스 셀·turnaround 양쪽)을 `ready=true`로
확정했다. 동일 replay의 OpenAI와 Anthropic 후보를 각각 4건 실행했지만 양쪽 모두 품질 통과
0건이라 Provider 전환 근거는 없다.
Attempt 3은 전체 request snapshot과 request/input SHA-256을 저장했다. 기존 Attempt 2는 이
기능 전 결과라 exact replay가 아니며, 최신 prompt/schema로 소급 생성하지 않는다(T111).
LLM 서술용 매출·영업이익 YoY/QoQ 절대 증감은 Python이 계산하며, 과거 replay의 분기 표는
요청 분기를 끝점으로 고정해 이후 분기 데이터가 섞이지 않게 한다(T110·T112).
새 canary는 request와 단가·상한을 `plan_sha256`으로 먼저 고정하며, 승인 뒤 계약이 달라지면
Provider token-count 호출 전 차단한다(T113). 같은 기준일의 현재가가 두 입력 경로에서 40원 어긋난
T115는 LLM 입력에서 `price_snapshots`를 canonical 현재가로 쓰고, 더 최신인 다른 Source가
있으면 분석을 차단하는 계약으로 해결했다. 사례집 확대 전에는 컨센서스 이력도
`snapshot_at` 최신 행으로 고정해 replay가 API 반환 순서에 따라 바뀌지 않게 했다(T117).
후보 메타데이터 read와 종목 replay read는 별도 승인 단계로 분리한다. DB·대시보드 UI는
변경하지 않았다. Stage A metadata read는 실제 GET **2회**로 완료돼 `290650`, `004000`,
`272210`을 골랐고 셀 4/4·업종 4개·turnaround 양쪽을 충족했다. Stage B replay read와
Provider 호출은 분리했다. Stage B는 승인 후 GET **27회**로 엘앤씨바이오·롯데정밀화학·
한화시스템 replay를 3/3 준비했고 DB 쓰기·DART·Provider 호출은 0건이다.
세 종목의 OpenAI canary 계획도 외부 호출 없이 고정했다. 종목당 token-count 1회와 생성 1회,
재시도 0회, 웹 검색 OFF, 최대 $0.15로 승인 후 실행했다. 신규 3건 비용은 **$0.232626**였고
모두 공시 표의 단위를 모델이 환산해 저장 gate에서 차단됐다. HJ를 포함한 실제 4건 평균은
**84.64점**이지만 품질 통과는 **0/4**라 OpenAI Primary 전환은 보류한다.
같은 4 replay의 Anthropic Sonnet 5도 plan v2로 실행했다. token-count 4회와 생성 4회,
재시도 0회, 웹 검색 OFF, 실제 비용 **$0.263351**이며 분석 DB 쓰기는 0건이다. HJ·롯데·한화는
계산·반올림·단위 환산 숫자로, 엘앤씨바이오는 canary 출력 상한 9,100토큰으로 차단됐다.
정상 동일 단위 표시 반올림 오탐을 제거한 오프라인 평균은 Anthropic **46.07**, OpenAI
**84.64**지만 모두 품질 0/4이고 HJ 요청 계약도
Provider 간 달라 `comparison_ready=false`; 승자를 선언하지 않는다.
실패 후속으로 숫자 자체감사 문단을 롯데정밀화학 1건에 시험했지만 점수 65.00→63.57,
근거 커버리지 50.00%→42.86%, unsupported 6→8로 악화돼 폐기했다. 운영 프롬프트와 현재
request/plan hash는 실험 전 값 `86a2b371…`/`a2f5e930…`으로 정확히 복구했다.
2026-08-30에는 다음 구조적 경계를 canary 실험으로 구현했다. 과거·현재 사실 숫자는
`[[F001:+595.1억원]]`처럼 표시한다. 모델이 전체 표식을 그대로 복사하거나 `[[F001]]`을
반환하면 프로그램이 저장 전에 원문 숫자로 복원한 뒤 기존 grounding gate를 다시 적용한다
(ADR 10). 첫 롯데정밀화학 Anthropic canary는 입력 **15,655토큰**, 비용 **$0.0901735**였고
분석 DB 쓰기는 0건이었다. 모델은 정확한 전체 표식을 68회 복사했으며, 유일한 실제 미근거
계산값 `+4.2%p`는 Python의 결정론적 OPM QoQ 변화 입력으로 옮겼다. 보정 전 오프라인 평가는
**83.57점 · evidence coverage 42.86%**였다. 수정 후 전체 안전 회귀는
**728 passed · 1 skipped · network 3 deselected**, Dashboard build 9/9 성공이다. 두 번째 동일
canary는 입력 **15,782토큰 · $0.048175**로 숫자 오류 **0건**이었지만 핵심 필드 11곳을
`placeholder`로 채우고 트리거를 비워 **26.43점**에 그쳤다. 재귀 schema+filler 검증을 운영
저장과 평가에 공통 적용했고 최종 회귀는 **731 passed · 1 skipped · 3 deselected**다.
분석 DB 쓰기는 0건이며 Provider 전환·사례집 확대는 계속 보류한다.
세 번째 `medium` canary는 filler 없이 **63.57점**까지 회복했지만 참조 75개 중 전체 표식
3개의 값을 단위 환산해 바꾸고 unsupported 숫자 5건을 만들었다(비용 **$0.094465**).
세 번 모두 quality=false라 fact-ref는 운영 기본 요청에서 격리했으며, 기존 직접 숫자 입력과
저장 전 grounding gate를 유지한다. 세 실험 합계는 **$0.2328135**, 분석 DB 쓰기는 0건이다.

---

## 셋업 순서

### 1. 의존성 설치

```bash
python -m venv .venv && .venv\Scripts\activate && pip install -e ".[dev]"
```

### 2. 환경변수

```bash
copy .env.example .env
```

`.env`를 채운다. 이 폴더에 이미 있는 `.env.txt`에서 값을 옮겨도 되지만,
**Supabase 값은 반드시 아래 3번 체크리스트로 검증한 뒤에 쓴다.**

> `src/utils/env.py`가 `.env`를 먼저 찾고, 없으면 `.env.txt`를 읽는다.
> 둘 다 `.gitignore`에 있다.

### 3. Supabase 스키마 적용 — ★ 여기가 P0의 본체다

`src/db/schema.sql`은 **REST로 실행할 수 없는 DDL**이다. 직접 붙여넣어야 한다.

1. Supabase 대시보드에서 **Heimdallr 전용 신규 프로젝트**를 연다
   (HermesCall 프로젝트가 아닌지 확인 — 아래 체크리스트)
2. 좌측 **SQL Editor** → **New query**
3. `src/db/schema.sql` 전문을 붙여넣고 **Run**
4. `Success. No rows returned` 확인

파일은 idempotent(`IF NOT EXISTS`)라 여러 번 실행해도 안전하다.
이후 Phase에서 컬럼이 추가되면 파일 하단 "증분 마이그레이션" 절에
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`로 덧붙인 뒤 통째로 다시 실행한다.

### 4. 검증

```bash
python -m src.db.init
```

11개 테이블 존재 + anon SELECT 동작 + `cost_log` 차단을 확인한다.
**여기서 통과해야 P1로 넘어간다.**

```bash
python -m pytest tests/
```

---

## ⚠️ 적용 전 체크리스트 (직접 확인할 것)

- [ ] **`SUPABASE_URL`의 프로젝트 ref가 HermesCall과 다른가?**
      `https://<ref>.supabase.co`의 `<ref>`를 눈으로 대조한다.
      Heimdallr는 신규 Supabase 프로젝트를 쓴다(ADR 8 · traps.md T16).
      **같은 값이면 HermesCall DB에 Heimdallr 테이블이 생성되어 분리 이유가 통째로 무너진다.**
      - HermesCall ref: `tioefbkuzidqecovbyku`
      - 현재 `.env.txt`의 Heimdallr ref: `drpxciqkbjlruximqbox` → **다름 (확인 완료 2026-08-13)**
- [ ] `SUPABASE_URL`에 `/rest/v1`이 붙어 있지 않은가? (supabase-py가 스스로 붙인다)
- [ ] `SUPABASE_SERVICE_KEY`에 **secret 키**(`sb_secret_...`),
      `NEXT_PUBLIC_SUPABASE_ANON_KEY`에 **publishable 키**(`sb_publishable_...`)가 들어갔는가?
      ⚠️ `sb_secret_...`를 `NEXT_PUBLIC_*`에 넣으면 RLS를 우회해 전체 데이터가 열린다.
- [ ] Supabase Free는 조직당 활성 프로젝트 2개다. HermesCall이 1개를 쓰므로 여유가 1개뿐 —
      다른 프로젝트가 슬롯을 먹고 있지 않은지 확인.
- [ ] `.env` / `.env.txt`가 git에 올라가지 않는지 (`git status`로 확인)

---

## 절대 금지 (요약 — 전문은 CLAUDE.md)

- **`setWebhook` 호출 금지.** 봇당 웹훅 1개만 허용되고 조용히 덮어써진다.
  HermesCall 대시보드가 점유 중이다. Heimdallr는 `sendMessage` 발송 전용.
- **KIS 주문 API 호출 금지.** `KIS_ALLOWED_PATHS` 화이트리스트 밖은 호출하지 않는다.
- **`os.environ` 직접 읽기 금지.** 반드시 `src/utils/env.py`.
- **KIND 상장법인목록을 `lxml`로 파싱 금지.** 코스닥 1,839행 중 1,282행에서
  예외도 경고도 없이 잘라낸다. 이 소스만 `html.parser`.
- **PostgREST 1,000행 초과 조회는 `range()` 페이징.** `src/db/supabase_client.py`의
  `select_all()`을 쓴다.
- **새 서드파티 임포트는 `pyproject.toml`에 먼저 선언.**

---

## 디렉터리

```
src/
  config/constants.py     임계값·배점의 단 하나의 출처 (PRD 부록 A)
  utils/env.py            환경변수 단일 창구 (.strip() 강제)
  db/schema.sql           PRD §6 — SQL Editor에 붙여넣어 실행
  db/supabase_client.py   range() 페이징 강제, URL 검증
  db/init.py              P0 검증 게이트
  collectors/             P1·P2·P4·P5·P6 — 외부 데이터 수집
  finance/                P2 quarterize.py ★급소 · P2.5 파생지표
  screener/               P3 순수 함수 (외부 I/O 금지)
  analysis/               P7 LLM 해석 · cost guard · offline replay eval · canary
  llm/                    Provider 중립 계약 · Anthropic/OpenAI Adapter
  notify/                 P8 텔레그램 (발송 전용)
  universe/               P1 유니버스
tests/
docs/  PRD.md · traps.md · phases.md · decisions/ · sessions/
```

저장된 LLM 결과의 replay suite는 외부 호출 없이 다음처럼 평가한다.

```bash
python -m src.analysis.eval_run tests/fixtures/llm_eval/representative_turnaround.json
```

내장 fixture는 평가기 검사용 synthetic 데이터다. 실제 Anthropic/OpenAI 비교 결과가 아니다.
승인된 OpenAI canary는 `docs/evals/openai-canary-plan.md`의 준비·호출 분리 절차를 따른다.
