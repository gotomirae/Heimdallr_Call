# OpenAI 단건 canary 실행 계획

> 작성일: 2026-08-28
> 상태: **Attempt 3 실행·offline 평가 완료 · 품질 게이트 실패로 Primary 전환 보류**

## 목적과 범위

OpenAI Provider가 Heimdallr의 기존 Canonical 입력·JSON Schema를 바꾸지 않고 실제 분석을
완주하는지 대표 종목 1건으로 확인한다. Provider 우열이나 운영 Primary 전환은 이 1건으로
결정하지 않는다. UI·payload·DB schema는 변경하지 않는다.

- 대표 사례: **HJ중공업(097230), 2026.2Q**
- 선정 이유: 고성장·수익성 가속, 13분기 주가 궤적, 최근 공시, 수주 관련 발췌를 함께
  요구해 T92·T93·T99·T100·T101 회귀를 한 번에 관찰할 수 있다. 실제 2026.2Q
  `turnaround=false`이므로 턴어라운드 사례라고 부르지 않는다.
- 모델: `gpt-5.6-terra`
- reasoning effort: `low`
- 웹 검색: OFF
- OpenAI 응답 저장: `store=false`
- Heimdallr 분석 DB 저장: 없음
- 텔레그램·DART·KIS·배포: 호출 없음

## 모델과 공식 단가

2026-08-28 OpenAI 공식 문서 기준이다.

| 항목 | 값 |
|---|---:|
| 모델 ID | `gpt-5.6-terra` |
| 입력 | $2.00 / 1M tokens |
| 캐시 입력 | $0.20 / 1M tokens |
| 캐시 쓰기 | $2.50 / 1M tokens |
| 출력(추론 토큰 포함) | $12.00 / 1M tokens |
| Context | 1.05M tokens |
| 모델 최대 출력 | 128K tokens |

공식 근거:

- [GPT-5.6 Terra 모델 및 가격](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
- [Responses API 생성](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
- [Responses 입력 토큰 계산](https://developers.openai.com/api/reference/cli/resources/responses/subresources/input_tokens)

공식 모델 목록에는 현재 날짜가 고정된 Terra snapshot이 보이지 않고 alias만 있다. 따라서
이 canary는 정확한 요청 모델 ID를 기록하되, 미래 재현 시 alias가 같은 가중치를 가리킨다고
가정하지 않는다. 응답이 돌려준 실제 `response.model`도 결과 파일에 함께 기록한다.

## 외부 시스템·엔드포인트·상태 변화

실행은 두 구간으로 나눈다. 데이터 준비는 OpenAI 호출 전에 끝내고, 동일한 로컬 replay
파일을 token-count와 생성 양쪽에 사용한다.

### A. 대표 입력 준비

| 시스템 | 엔드포인트 | 종류 | 예상 호출 | 외부 상태 변화 |
|---|---|---|---:|---:|
| Heimdallr Supabase | `GET {SUPABASE_URL}/rest/v1/krx_universe` | 읽기 | 1 | 0 |
| Heimdallr Supabase | `GET {SUPABASE_URL}/rest/v1/quarterly_fundamentals` | 읽기 | 1 | 0 |
| Heimdallr Supabase | `GET {SUPABASE_URL}/rest/v1/screen_results` | 읽기 | 1 | 0 |
| Heimdallr Supabase | `GET {SUPABASE_URL}/rest/v1/consensus_snapshots` | 읽기 | 2 | 0 |
| Heimdallr Supabase | `GET {SUPABASE_URL}/rest/v1/price_snapshots` | 읽기 | 1 | 0 |
| Heimdallr Supabase | `GET {SUPABASE_URL}/rest/v1/disclosure_excerpts` | 읽기 | 1 | 0 |
| Heimdallr Supabase | `GET {SUPABASE_URL}/rest/v1/quarter_prices` | 읽기 | 1 | 0 |
| Heimdallr Supabase | `GET {SUPABASE_URL}/rest/v1/earnings_disclosures` | 읽기 | 1 | 0 |

합계 **9회 read, 0회 write**다. 모든 조회는 `code=eq.097230`과 필요한 기간 조건을 서버에
걸고 1,000행 미만임을 확인한다. 현재 `build_input()`처럼 테이블 전체를 읽은 뒤 필터링하는
경로는 정확한 호출 수를 보장할 수 없으므로 canary 준비에 사용하지 않는다. 저장된 발췌가
없으면 OpenDART로 폴백하지 않고 실행을 중단한다(`allow_fetch=false`).

로컬 replay 파일에는 API 키·Supabase URL·service key를 넣지 않는다. 생성 전 `git diff`와
시크릿 패턴 검사를 통과해야 하며, 실제 Provider 결과 비교용이므로 `synthetic=false`로 둔다.

### B. OpenAI canary

| 시스템 | 엔드포인트 | 종류 | 예상 호출 | 외부 상태 변화 |
|---|---|---|---:|---:|
| OpenAI | `POST https://api.openai.com/v1/responses/input_tokens` | 입력 토큰 계산 | 1 | 0 |
| OpenAI | `POST https://api.openai.com/v1/responses` | 유료 생성 | 1 | 응답 1건 생성, 저장 OFF |

OpenAI 외부 요청은 합계 **2회**, 그중 유료 생성은 **1회**다. 재시도는 자동으로 하지 않는다.
타임아웃·429·5xx·schema 오류가 나도 같은 요청을 다시 결제하지 않고 실패로 종료한다.
Supabase `analyses`·`cost_log`를 포함한 DB 쓰기, 텔레그램, 배포는 모두 0건이다.

`store=false`는 생성 응답을 이후 API 검색용으로 저장하지 않도록 요청하는 설정이다. 전송 데이터의
보존 정책 전체를 뜻하는 표현으로 확대 해석하지 않는다.

## 비용 계산과 하드캡

현재 입력 예산 16,000토큰, 최근 실측 입력 최대 13,768토큰, 최근 출력 중앙 4,989토큰을 쓴다.

| 시나리오 | 계산 | 비용 |
|---|---|---:|
| 최근 관측치 | 13,768 × $2/M + 4,989 × $12/M | **$0.087404** |
| 입력 예산 + 출력 중앙 | 16,000 × $2/M + 4,989 × $12/M | **$0.091868** |
| 현재 공통 상한 그대로 | 16,000 × $2.50/M + 16,384 × $12/M | **$0.236608** |
| canary 출력 9,100 상한 | 16,000 × $2.50/M + 9,100 × $12/M | **$0.149200** |

따라서 `LLM_MAX_TOKENS=16384`를 그대로 쓰면 `$0.15`는 하드캡이 아니다. 이번 canary만
`max_output_tokens=9100`으로 제한해야 입력이 16,000토큰 모두 cache-write로 청구돼도
이론상 최대 $0.1492로 막힌다. 9,100은 최근 출력 중앙의 1.82배지만, 긴 분석이 잘릴 위험은 남는다. 잘리면 실패로
기록하고 상한을 올려 재호출하지 않는다.

캐시 쓰기 토큰이 별도 청구되는 응답이면 최악비용 계산을 호출 전에 다시 한다. 공식 token-count가
16,000을 넘거나 계산된 최악비용이 $0.15를 넘으면 생성 호출은 0건으로 중단한다.

## 호출 전 최소 수정 상태

2026-08-28 로컬 구현과 mock 검증을 완료한 뒤 승인된 단건 호출까지 마쳤다.

1. `OpenAIProvider`가 token-count와 생성 양쪽에 `reasoning={"effort": "low"}`를 전달한다.
2. `run_canary()`가 생성 전에 가장 비싼 입력 분류로 최악비용을 계산해 초과 요청을 막는다.
3. canary는 일반 `analyze()`를 쓰지 않아 `analyses`와 `cost_log`를 모두 쓰지 않는다.
4. canary 전용 출력 상한 9,100을 Canonical 요청에 명시적으로 주입한다.
5. `build_input()`의 9개 조회 모두 `code`를 서버 필터로 보내고 replay 준비 시 DART 폴백을 막는다.
6. OpenAI SDK 자동 재시도는 canary에서 `max_retries=0`으로 끈다.
7. `pri_detail`과 최종 `pri`를 함께 싣고, 최종값이 없는 replay는 호출 전에 거부한다(T107).

로컬 검증: 관련 검사 **62 passed**, 전체 Python **651 passed · 1 skipped · network 3 deselected**,
Dashboard production build 성공. 비용 가드에서 cache-write 단가 선택을 잠시 제거하면 전용
회귀 검사 **1건이 실패**했고, 원복 후 다시 통과했다.
유료 생성 뒤 payload 검증이 실패해도 response ID·실측 usage·비용·원 payload를 로컬 실패
결과에 남기는 회귀 검사도 포함한다.

준비·승인 계획·호출 명령은 분리한다. `plan`은 현재 prompt/schema/모델/단가/상한을
`plan_sha256` 하나로 고정하며 외부 호출을 하지 않는다. `call`은 사용자가 승인한 동일 hash를
명시해야 token-count 단계로 넘어간다(T113).

```bash
python -m src.analysis.canary_run prepare --code 097230 --quarter 2026.2 --output replay.json
python -m src.analysis.canary_run plan --input replay.json --output openai-plan.json
python -m src.analysis.canary_run call --input replay.json --output openai-result.json \
  --approved-plan-sha256 <승인한-plan-sha256> --execute-approved-canary
```

2026-08-28 수정본 replay 준비는 완료했다.

- 파일: `docs/evals/replays/hj-097230-2026q2.json` · **13,393 bytes**
- 8분기(2024.3Q~2026.2Q) · 공시 발췌 2,555자 · 분기말 주가 13행 · 공시 1행
- 기준일 2026-08-27 · 최종 PRI **7.6241389208** · raw 4.9556902985 / 분모 65
- `load_replay` 통과 · 시크릿 패턴 0건 · replay 준비 시점 OpenAI 호출 0건

로컬 `.env`에는 OpenAI API key만 있고 모델·네 단가 설정은 없다. 승인 호출에서는 파일을
수정하지 않고 해당 프로세스에만 `gpt-5.6-terra`, 2/12/2.5/0.2를 주입했다.

## 성공·실패·복구 기준

성공은 아래를 모두 만족할 때뿐이다.

- 공식 token-count ≤ 16,000
- 실측 비용 ≤ $0.15
- 응답 상태 `completed`, refusal·incomplete·parse 오류 0건
- Canonical JSON Schema 오류 0건
- offline eval 80점 이상
- 핵심 근거 coverage 75% 이상
- 입력에 없는 사실 숫자 0건
- 과거 또는 3/6개월 범위 밖 트리거 0건
- Supabase·텔레그램·DART·KIS·배포 쓰기 0건
- 동일 replay의 기존 Anthropic 결과와 사람이 숫자·공시 근거를 대조

실패 시 외부 상태 복구 작업은 없다. 로컬 결과 파일만 실패 이유와 실측 usage를 기록한다.
이미 발생한 OpenAI 비용은 복구할 수 없으며 자동 재시도하지 않는다. 실패 결과로 모델이나
프롬프트를 바꿀 때는 별도 작업과 별도 승인을 받는다.

## 승인 요청 범위

추천 범위는 다음 두 단계다.

1. 외부 호출 없는 최소 가드 구현과 mock 회귀 검증 — 완료.
2. Supabase read-only replay 준비와 입력 검증 — 완료.
3. 별도 승인 뒤 OpenAI token-count 1회 + 유료 생성 1회, 총비용 하드캡 $0.15 실행.

### Attempt 1 결과 — 2026-08-28

- input-token count 요청 1회: 통과해 preflight를 넘겼다.
- 생성 요청 1회: HTTP 429 `insufficient_quota / credit_balance_exhausted`로 거부됐다.
- SDK 자동 재시도: 0회. response ID·usage·실측 비용은 반환되지 않아 모두 `null`이다.
- DB·텔레그램·DART 쓰기: 0건. Provider 결과 비교는 성립하지 않는다.
- T108 수정 전이라 성공한 count 수치가 생성 예외 전에 파일로 보존되지 않았다. 그 수치를
  복구하려고 추가 요청하지 않는다. 시도 기록은 `results/*-attempt-1.json`에 남겼다.
- T108 수정 후 Provider HTTP 오류도 count·최악비용·오류 코드를 로컬 결과에 보존한다.

Primary Provider 전환, 운영 설정 변경, 반복 canary, DB 저장은 이번 승인 범위가 아니다.

### Attempt 2 결과 — 2026-08-28

- 승인 범위대로 input-token count **1회**, 생성 **1회**, SDK 재시도 **0회**를 실행했다.
- `status=completed`, 모델 `gpt-5.6-terra`, schema 오류 0건이다.
- 공식 count **11,925 tokens**, 사전 최악비용 **$0.1390125**로 두 가드 모두 통과했다.
- usage: input 3 · cache write 11,922 · cache read 0 · output 4,751 tokens.
- 실측 비용 **$0.086823**으로 $0.15 하드캡을 통과했다.
- 정정된 offline eval은 **75.83/100**, evidence coverage **91.67%**다. schema·비용·
  actionability는 통과했지만 quality 기준 80점에는 미달했다.
- 실제 품질 실패: 입력에 없는 차액 **2,221억·1,885억·596억**을 모델이 계산했고,
  `within_6m`에 기준월 +7개월인 `2027-03`을 넣었으며 최신 공시일 앵커 1개를 놓쳤다.
- 같은 replay의 Anthropic 후보가 없어 `comparison_ready=false`, `winner=null`이다.
- 평가기 자체의 한국식 복합 단위·표시 반올림 오탐(T109)을 먼저 고친 뒤 위 점수를 확정했다.
  프롬프트에는 파생 숫자 금지, Python 계산 3/6개월 상한, 최신 공시일 인용을 추가했다(T110).
- Attempt 2는 호출 당시 exact request snapshot을 저장하기 전 결과다. 75.83점은 당시 builder와
  대조한 참고 기준으로 유지하되 `request_replay_exact=false`다. 최신 prompt/schema로 소급
  snapshot을 만들지 않으며, 향후 canary는 전체 request snapshot과 request/input SHA-256을
  성공·유료 실패·Provider 오류 모두에 저장한다(T111).
- DB·DART·KIS·텔레그램·배포·커밋은 0건이다. 결과와 평가는 `docs/evals/results/`에 보존한다.

OpenAI Primary 전환은 보류한다. 새 프롬프트의 품질을 확인하는 추가 유료 호출은 별도 승인
대상이며, 같은 replay의 Anthropic 결과 없이 Provider 우열을 선언하지 않는다.

### Attempt 3 승인 계획 — 2026-08-28

- 계획 파일: `plans/hj-097230-2026q2-openai-terra-attempt-3.json` · **37,850 bytes**.
- `plan_sha256`: `1aee2e7549f54c381163e3f9d190a31c92d56da750fb29bf60fa8d632f7b4f8c`.
- `request_sha256`: `8c2733a75cd67c9392277c5e55f910e0006362a6a0f2aa51f6e3d63772c9ebdb`.
- `input_sha256`: `114854642515309753aa540c767fb2ea2b3a6ffd8e4ef7972539a2da32c6f850`.
- user message **5,864자**, 입력 예산 16,000, 출력 상한 9,100, 비용 하드캡 $0.15.
- 공식 단가를 반영한 예산 기준 최악비용은 **$0.149200**, 잔여 폭은 **$0.000800**이다.
- exact 입력 토큰은 현재 **미측정(`null`)**이다. Attempt 2의 11,925는 다른 prompt/request이므로
  재사용하지 않는다. 승인 실행의 `POST /v1/responses/input_tokens` 1회가 새 count를 고정한다.
- 계획 생성 시 OpenAI·Supabase·DART·KIS·텔레그램 호출과 외부 쓰기는 모두 **0건**이다.
- 실행 직전 공식 가격을 다시 확인하고 같은 네 단가를 프로세스 환경에 넣어야 한다. 단가나
  prompt/schema/effort/web/output cap 중 하나라도 바뀌면 plan hash가 달라져 count 호출 전 차단된다.

승인 범위는 token-count **1회**, 유료 생성 **1회**, SDK 재시도 **0회**, DB 쓰기
**0건**, 최대 **$0.15**였다. 사용자가 이 exact plan hash를 승인한 뒤 아래와 같이 실행했다.

### Attempt 3 결과 — 2026-08-28

- 실행 직전 plan을 오프라인 재계산해 승인 hash와 **일치**함을 확인했다.
- 샌드박스 소켓 차단 1회는 OpenAI에 도달하기 전에 실패해 외부 호출·과금이 없었다.
  네트워크 권한을 받은 동일 프로세스에서 실제 token-count **1회**, 생성 **1회**를 실행했다.
- 상태 `completed`, 응답 모델 `gpt-5.6-terra`, SDK 재시도 **0회**.
- 공식 count **12,367 tokens**, 사전 최악비용 **$0.1401175**.
- usage: uncached input **3** · cache write **12,364** · cache read **0** · output
  **5,096 tokens**.
- 실측 비용 **$0.092068**, 하드캡 $0.15 대비 **$0.057932 잔여**.
- request/input/plan SHA-256이 승인 artifact와 모두 일치하고 `request_replay_exact=true`다.
- schema·트리거 시점·actionability는 통과했으나 offline eval은 **90/100**에서
  `quality_pass=false`, `canary_eligible=false`였다. 공시의 `26,737백만원`을 모델이
  `267억원`으로 새로 환산한 1건이 factual hard failure다(T114).
- evidence coverage는 정확히 **75%**였고, 필수 anchor 12개 중 3개
  (`latest_operating_profit`, `price_peak_to_current`, `disclosure_timing`)를 놓쳤다.
- 입력 자체도 같은 2026-08-27 현재가를 `price_snapshots=17,160원`,
  `quarter_prices=17,120원`으로 동시에 제공했고 응답이 두 값을 모두 인용했다(T115).
- 동일 replay의 Anthropic 후보가 없어 `comparison_ready=false`, `winner=null`이다.
- OpenAI Primary 전환, DB 저장, 텔레그램, DART/KIS, 배포, 커밋은 하지 않았다.

결과는 `results/hj-097230-2026q2-openai-terra-attempt-3.json`, 평가는
`results/hj-097230-2026q2-openai-terra-attempt-3-eval.json`에 보존한다. Provider payload는
사람이 고치지 않았다. 다음 유료 재호출은 이번 승인에 포함되지 않는다.

#### T115 후속 — current-price 입력 정합성

Attempt 3 결과 자체는 감사 증거이므로 수정하지 않았다. 이후 LLM 요청 조립은
`price_snapshots`를 current-price canonical source로 사용하고 같은 달력분기의
`quarter_prices` 행을 대체한다. 실제 HJ replay 재조립에서 `17,120원`은 **0건**,
`17,160원`은 시세 JSON·시계열 각 **1건**, 최근 구간 수익률은 **-14.8%**였다.
다른 Source가 더 최신이면 유료 호출 전에 실패한다. 이 후속 작업의 외부 호출은 0건이다.

#### T114 후속 — factual-number 저장 gate

Attempt 3 결과와 90점 평가는 감사 증거로 그대로 유지했다. 당시 raw payload와 exact request를
새 공통 validator에 넣으면 unsupported는 **`267억` 1건**이다. 이후 운영 분석과 canary는
과거/현재 사실 필드에 request와 같은 단위로 없는 숫자가 있으면 DB 저장 전에 실패한다.
원문 `26,737백만원` 반복 인용은 허용하지만 LLM의 `267억원` 환산은 허용하지 않는다.
미래 시나리오 임계값은 차단하지 않는다. 추가 OpenAI 호출·비용은 0건이다.
