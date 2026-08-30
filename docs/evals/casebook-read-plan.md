# 실제 투자판단 사례집 read-only 준비 계획

상태: **Stage A·B 완료 · Provider 호출 미승인/미실행**
기준 분기: **2026.2Q**
기존 실제 사례: HJ중공업(097230) — `★/컨센서스 없음`, 비턴어라운드 가속화,
토목 건설업

## 목표 횡단면

추가할 셀은 정확히 세 개다.

1. `★/컨센서스 있음`
2. `○/컨센서스 있음`
3. `○/컨센서스 없음`

세 종목을 더했을 때 전체 4종목이 최소 3개 업종과 `turnaround=true/false`를 모두
포함해야 한다. 점수가 가장 높은 종목만 고르지 않고, 위 대표성 조건을 먼저 만족한 조합에서
`score_flash`가 높고 PRI가 낮은 조합을 결정론적으로 선택한다. 입력 행 순서에는 의존하지 않는다.

## Stage A — 후보 메타데이터 선정 read

이 단계만 먼저 승인받아 실행한다. Supabase/PostgREST 읽기 외 외부 시스템은 호출하지 않는다.

| 순서 | 메서드·endpoint | 필터·선택 필드 | 예상 HTTP |
|---:|---|---|---:|
| 1 | `GET {SUPABASE_URL}/rest/v1/screen_results` | `fiscal_year=eq.2026`, `fiscal_quarter=eq.2`, `gate_passed=eq.true`, `grade=in.(★,○)` · `code,fiscal_year,fiscal_quarter,gate_passed,turnaround,score_flash,has_consensus,pri,grade` | 1 |
| 2 | `GET {SUPABASE_URL}/rest/v1/krx_universe` | 1번의 code만 `in.(...)` · `code,industry` | 1 |

- 예상 호출: **2 GET**. 2026-08-26 실측 발송등급은 88종목이라 각 응답은 1,000행 미만이다.
- 안전 상한: **4 GET**. 어느 응답이 1,000행이면 `range(0,999)`, `range(1000,1999)`로만
  한 페이지 더 읽는다. 두 번째 페이지도 1,000행이면 중단하고 추가 승인을 받는다.
- 비용: **$0**. Supabase 읽기 외 과금 API가 없다.
- 외부 상태 변화: **0행**, webhook/offset/캐시/DB 변경 **0건**.
- 로컬 산출물: 선택된 code·셀·업종·turnaround·score·PRI와 탈락 사유를 담은 JSON 1개.

성공 수치:

- 선택 종목 3개, 중복 code 0개
- 기존 HJ중공업과 합쳐 네 grade/consensus 셀 4/4
- 업종 최소 3개
- turnaround 상태 2/2
- 누락·`None` boolean을 후보로 사용한 건수 0개

행 수나 셀 분포가 예상과 다르면 종목을 추측해 채우지 않고 실제 부족 셀을 보고한다.

### Stage A 실제 결과 — 2026-08-28

- HTTP GET **2회**: `screen_results` 1페이지 + `krx_universe` 1페이지
- 후보 **81행**, universe 결합 **81/81**
- 셀 분포: `○/false` 42 · `○/true` 13 · `★/false` 21 · `★/true` 5
- 선택:
  - `290650` — `○/false`, turnaround, 의약품 제조업, score 67.6279, PRI 20.3093
  - `004000` — `○/true`, 비턴어라운드, 기초 화학물질 제조업, score 97.5610, PRI 48.3716
  - `272210` — `★/true`, 비턴어라운드, 전자부품 제조업, score 88.3794, PRI 8.3552
- 기존 HJ중공업과 합친 결과: 셀 **4/4**, 업종 **4개**, turnaround 상태 **2/2**
- 외부 쓰기·DART·Provider·Stage B 호출 **0건**

원 출력은 `results/casebook-stage-a-2026q2.json`에 보존했다.

## Stage B — 선택된 3종목 replay 준비 read

Stage A의 실제 code를 보고한 뒤 별도 승인받는다. **아직 승인되지 않았다.**
각 종목은 기존 `build_input(..., allow_fetch=False)` 경로의 필터 조회 9개만 사용한다.

| # | endpoint | 서버 필터 |
|---:|---|---|
| 1 | `/rest/v1/krx_universe` | `code=eq.<code>` |
| 2 | `/rest/v1/quarterly_fundamentals` | `code=eq.<code>` |
| 3 | `/rest/v1/screen_results` | `code`, `fiscal_year=2026`, `fiscal_quarter=2` |
| 4 | `/rest/v1/consensus_snapshots` | `code`, `fiscal_year=2026`, `fiscal_quarter=2` |
| 5 | `/rest/v1/price_snapshots` | `code=eq.<code>` |
| 6 | `/rest/v1/consensus_snapshots` | `code`, `fiscal_quarter=0` |
| 7 | `/rest/v1/disclosure_excerpts` | `code=eq.<code>` |
| 8 | `/rest/v1/quarter_prices` | `code=eq.<code>` |
| 9 | `/rest/v1/earnings_disclosures` | `code=eq.<code>` |

- 예상 호출: 종목당 **9 GET**, 총 **27 GET**. 기존 `select_all`은 code 필터 결과가 정확히
  1,000행이면 다음 range를 읽으므로, Stage B 승인 artifact를 만들 때 **예상 27 · 안전 상한
  30 GET**으로 고정한다. 30회를 넘기기 전 중단·보고하고 재승인받는다.
- DART 폴백: **0회** (`allow_fetch=False`).
- OpenAI/Anthropic/Gemini: **0회**, 비용 **$0**.
- DB 쓰기·`cost_log`·텔레그램·배포: **0건**.
- 로컬 산출물: `docs/evals/replays/<code>-2026q2.json` 최대 3개.

종목별 replay 성공 수치:

- 요청 분기로 끝나는 재무 5~8분기, 미래 분기 0행
- `gate.passed=true`, 선택한 grade/consensus 셀과 replay가 일치
- 최신 `snapshot_at` 컨센서스 사용; API 반환 순서 의존 0건
- 같은 분기 발췌 존재, `as_of` 존재, 최종 `pri.pri` 존재
- canonical current price 충돌 0건
- 시크릿 패턴 0건

한 종목이라도 필수 입력이 없거나 셀이 달라지면 그 종목은 저장 대상에서 제외하고 즉시
보고한다. 같은 셀의 다음 종목을 자동으로 읽지 않는다.

## 실패 복구

모든 외부 동작이 SELECT라 외부 복구는 필요 없다. 로컬 JSON은 임시 경로에 먼저 만들고
모든 검증을 통과한 파일만 `docs/evals/replays/`로 옮긴다. 실패한 임시 파일은 삭제할 수 있으며,
기존 HJ replay와 Provider 결과는 변경하지 않는다.

## 절대 금지

- Supabase insert/update/upsert/delete/RPC
- DART·KIS·네이버·텔레그램 호출
- OpenAI token-count 또는 유료 생성
- `setWebhook`, `getUpdates`, 배포, 커밋

Stage A와 Stage B는 승인 범위가 다르다. Stage A 승인으로 Stage B나 Provider 호출을 실행하지 않는다.

### Stage B 실제 결과 — 2026-08-28

- HTTP GET **27/30회**, 종목당 정확히 9회, 두 번째 페이지 0회
- 유효 replay **3/3**, 실패 0
- 엘앤씨바이오(290650): 8분기 · 발췌 2,555자 · 현재가 53,200원 · PRI 20.3093
- 롯데정밀화학(004000): 8분기 · 발췌 2,550자 · 현재가 48,000원 · PRI 48.3716 ·
  컨센서스 snapshot 2026-08-13
- 한화시스템(272210): 8분기 · 발췌 2,556자 · 현재가 75,000원 · PRI 8.3552 ·
  컨센서스 snapshot 2026-08-16
- 세 파일 모두 최신 분기 2026.2Q, 기준일 2026-08-28, 시크릿 0건
- DB 쓰기·DART·Provider·텔레그램 0건

결과는 `results/casebook-stage-b-2026q2.json`, replay는 `replays/<code>-2026q2.json`에 있다.
Provider 호출은 이 read 완료로 승인된 것이 아니다.
