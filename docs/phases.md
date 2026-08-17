# Heimdallr_Call — Phase별 Claude Code 프롬프트 (PRD v2.1 기준)

> 각 블록을 **하나의 세션**으로 다룬다. 끝나면 `/clear` 후 다음 Phase.
> 한 세션에 두 Phase를 넣지 말 것 — 컨텍스트가 커지면 앞 Phase의 규칙이 뒤에서 조용히 무시된다.
> 모든 세션에서 `CLAUDE.md`와 `docs/PRD.md`의 해당 절을 먼저 읽힌다.

## Phase 개요

| Phase | 산출물 | 검증 게이트 |
|---|---|---|
| P0 | 스캐폴딩 · 스키마 · CLAUDE.md | `python -m src.db.init` 성공 |
| P1 | 유니버스 | 종목 수 원문 대조 · corp_code 매칭률 ≥98% |
| **P2** | **분기 재무 + 누적치 분해 ★급소** | **3사×8분기 DART 원문 100% 일치** |
| P2.5 | 파생지표 (TTM · 2년스택 · 성장률) | 손계산 3건 대조 |
| P3 | 스크리너 (게이트·스코어·PRI·매트릭스) | 단위 테스트 + 정규화 규칙 검증 |
| P4 | 공시 감지 · 잠정실적 파서 | 30일 replay · 오탐 <5% |
| P5 | 컨센서스 사전 스냅샷 | 샘플 50종목 파싱률 보고 |
| P6 | KIS 시세 · PRI | 토큰 캐시 · 스로틀 · **응답 필드명 실측 확정** |
| P7 | LLM 분석 · cost guard | 실호출 1회 $0.05 이하 |
| P8 | 텔레그램 | 실발송 1건 + 중복 차단 |
| P9 | 대시보드 | 브라우저 렌더 확인 |
| P10 | GitHub Actions | 6개 워크플로우 dispatch 성공 |
| P11 | 결과 추적 | 과거 분기 backfill 후 등급별 분포 |

---

## P0 — 스캐폴딩

```
Heimdallr_Call 프로젝트를 시작한다.
docs/PRD.md 전체와 CLAUDE.md를 먼저 읽어라.

이번 세션 범위는 P0(스캐폴딩)뿐이다. 다음을 만들어라.

1. pyproject.toml
   의존성 최소로: httpx, beautifulsoup4, lxml, supabase, python-dotenv, anthropic, tzdata.
   새 서드파티 임포트를 추가할 때는 반드시 여기에 먼저 선언한다(참고 프로젝트에서
   이 누락으로 GitHub Actions만 죽는 사고가 3회 재발했다).

2. src/utils/env.py — require_env / optional_env (내부에서 반드시 .strip()).
   프로젝트 어디에서도 os.environ을 직접 읽지 않는다.

3. src/config/constants.py — PRD 부록 A 그대로. 임계값·배점은 여기 한 곳에만 둔다.

4. src/db/schema.sql — PRD §6 그대로.
   RLS 전 테이블 ENABLE + cost_log 제외 anon SELECT 정책.
   idempotent(IF NOT EXISTS)로 작성.

5. src/db/supabase_client.py, src/db/init.py

6. .env.example — 아래 항목 전부.
   ANTHROPIC_API_KEY / OPENDART_API_KEY / KIS_APP_KEY / KIS_APP_SECRET /
   KIS_PAPER_TRADING / TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID /
   SUPABASE_URL / SUPABASE_SERVICE_KEY / DASHBOARD_BASE_URL /
   MONTHLY_COST_CEILING_USD / DAILY_ANALYSIS_LIMIT / SEASON_MODE /
   NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY
   SUPABASE_URL에는 /rest/v1을 붙이지 않는다(supabase-py가 스스로 붙인다).

7. .gitignore (.env, .cache/, __pycache__, dashboard/.next 등), README.md

8. docs/ 디렉터리: sessions/, decisions/ 생성 (traps.md와 phases.md는 이미 있다)

9. tests/__init__.py, conftest.py

⚠️ 주의
- schema.sql은 Supabase REST로 실행 불가한 DDL이다. 내가 SQL Editor에 직접 붙여넣어
  실행할 것이므로 README에 실행 순서를 명확히 적어라.
- 프로젝트 폴더에 이미 .env.txt가 있고 SUPABASE_URL/SUPABASE_SERVICE_KEY 값이 들어 있는데,
  이건 HermesCall 것일 가능성이 높다. Heimdallr는 신규 Supabase 프로젝트를 쓴다(ADR 8).
  README 체크리스트에 "SUPABASE_URL의 프로젝트 ref가 HermesCall과 다른지 눈으로 대조"를
  반드시 넣어라.

끝나면 내가 무엇을 해야 하는지 체크리스트로 알려줘라.
```

---

## P1 — 유니버스

```
P1: KOSPI/KOSDAQ 유니버스 수집. PRD §3, §5.1(L0)을 읽어라.

참고: C:\Claude\dev\HermesCall\src\universe\krx_listing.py 를 읽고 이식하되
아래를 반드시 유지·추가하라.

[유지 — 실측으로 검증된 것들 (traps.md T5/T6/T7/T8)]
- KIND 상장법인목록에 한해 BeautifulSoup 파서는 "html.parser". "lxml"은 코스닥
  1,839행 중 1,282행에서 예외도 경고도 없이 잘라낸다.
- 원문 <tr> 개수와 파싱 행 수를 대조해 유실을 감지하고 즉시 실패시킨다.
- KIND 응답에 같은 종목코드가 중복되는 행이 있다(실측 36건). code 기준 중복 제거.
- 네이버 시총 페이징은 엄격한 내림차순이 아니다. "그 페이지의 마지막 항목까지 하한
  미만일 때"만 멈춘다.
- PostgREST max-rows 1,000 → 1,300종목 조회는 반드시 range() 페이징.

[신규]
- DART corpCode.xml(ZIP)로 종목코드 → corp_code(8자리) 매핑을 만들어
  krx_universe.corp_code에 저장한다. P2 배치 수집의 키다.
- 상장일(listed_at), 관리종목/투자주의환기(is_admin_issue), 스팩(is_spac) 수집.
- PRD 부록 B의 업종 제외 필터를 적용해 is_excluded / exclude_reason / sector_caveat를
  채운다. 판정 결과를 반드시 DB에 기록해 나중에 검증 가능하게 하라.

[검증 — 이번 세션 안에 실제로 돌려서 수치를 보여줄 것]
1. 시총 1,000억 이상 종목 수 (KOSPI/KOSDAQ 각각) + KIND 원문 행 수와 대조
2. corp_code 매칭 실패 종목 수 — 2% 초과 시 원인 규명
3. 업종 제외로 걸러진 종목 수와 사유별 분포 (금융/지주/리츠/스팩)
4. 삼성전자(005930) · 리노공업(058470) · HPSP(403870)의 corp_code가 DART에서
   실제 조회되는지 확인

tests/test_universe.py에 코스닥 1,700개 이상을 강제하는 회귀 테스트를 넣어라.
```

---

## P2 — 분기 재무 (★ 이 프로젝트의 급소)

```
P2: DART 정기보고서에서 8~10분기 재무를 배치 수집한다.
PRD §5.1(L2), §5.3, traps.md T1/T2/T3/T4를 먼저 읽어라.

여기를 틀리면 이후 전부가 조용히 틀린다. 에러가 나지 않으므로 검증이 유일한 방어선이다.

[1] src/collectors/dart_financials.py
- fnlttMultiAcnt.json 사용. corp_code를 쉼표로 최대 100개까지 묶어 1콜로 처리.
- 1,300종목 ÷ 100 = 13콜 × (연도, 보고서코드) 조합.
- reprt_code: 11013(1Q) / 11012(반기) / 11014(3Q) / 11011(사업보고서)
- fs_div는 CFS 우선, 없으면 OFS. 종목별로 하나를 고정하고 컬럼에 기록한다.
  분기마다 기준이 바뀌면 성장률이 조작된 것처럼 보인다.

[2] src/finance/quarterize.py  ← 이 모듈만 따로 만들고 테스트를 먼저 써라
DART 정기보고서는 보고서마다 누적 기준이 다르다:
  1분기보고서 : thstrm_amount = 3개월 단독
  반기보고서   : 6개월 누적    → Q2 = 반기 − Q1
  3분기보고서  : 3개월 단독 + 9개월 누적 둘 다 존재
  사업보고서   : 12개월 누적   → Q4 = 연간 − 3Q누적
thstrm_amount(당기)와 thstrm_add_amount(당기누적)를 반드시 구분하라.

[3] 재작성(restated) 처리
분할·합병·중단영업·회계기준 변경 시 전년동기가 재작성된다. 공시에 실린 전년동기 값을
우선하고, DB 저장값과 다르면 restated=true로 기록한다.

[검증 게이트 — 통과 전에는 절대 다음 Phase로 넘어가지 마라]
다음 3사 × 최근 8분기의 매출·영업이익을 수집한 뒤,
DART 원문(분기·반기·사업보고서 손익계산서)과 네가 직접 대조해서 표로 보여줘라:
  · 삼성전자   005930 (대형·연결)
  · 리노공업   058470 (중형·코스닥)
  · 에스티아이 039440 (중소형·변동성 큼)
특히 각 사의 2Q와 4Q를 집중 확인하라. 누적치 분해가 틀렸다면 여기서만 드러난다.
불일치가 하나라도 있으면 원인을 찾아 고치고 다시 대조하라.

tests/test_quarterize.py에 반드시 넣을 것:
  1Q / 반기 / 3Q / 사업보고서 4가지 케이스, 전년 데이터 결측 케이스,
  Q1 결측으로 Q2를 계산할 수 없는 케이스(None 반환 확인)
```

---

## P2.5 — 파생지표

```
P2.5: 파생지표 계산. PRD §6(quarterly_fundamentals 컬럼)을 읽어라.

계산할 것:
- 성장률: revenue_yoy, revenue_qoq, op_yoy, op_qoq, np_yoy, eps_yoy
- 마진: opm, opm_yoy_delta, opm_qoq_delta, gpm, npm
- TTM(계절성 제거용): ttm_revenue, ttm_op, ttm_opm, ttm_cfo,
                      ttm_revenue_qoq, ttm_opm_delta
- 2년 스택(기저효과 방어): rev_2y_stack = revenue(t)/revenue(t-8) − 1
- FCF = cfo − capex

[반드시 지킬 것 — traps.md T12]
- 부호가 바뀌는 구간(적자↔흑자)에서 % 계산 금지.
  분모가 0이거나 음수면 None을 반환하고 op_status_label에
  '흑전'|'적전'|'적자축소'|'적자확대' 중 하나를 넣는다.
- TTM은 4개 분기가 전부 있을 때만 계산한다. 하나라도 없으면 None.
  결측을 0으로 채우지 마라 — TTM이 실제보다 낮게 나와 가짜 악화로 보인다.

[검증]
- 삼성전자·리노공업 각 1개 분기씩 손계산으로 대조하고 계산 과정을 주석에 남겨라
- 적자 전환 사례를 실제 데이터에서 하나 찾아 status_label이 제대로 붙는지 확인
- TTM OPM이 분기 OPM보다 변동이 작은지(계절성 제거가 실제로 되는지) 3종목으로 확인
```

---

## P3 — 스크리너

```
P3: 게이트 + 스코어 + PRI + 매트릭스. 전부 순수 함수, 외부 I/O 금지.
PRD §4 전체와 부록 A를 읽어라.

파일: src/screener/gate.py, score.py, pri.py, matrix.py

[반드시 지킬 것]
1. ★ 정규화 규칙 (PRD §4.2) — 이 프로젝트에서 가장 중요한 계산 규칙
   측정 불가능한 축은 0점 처리하지 말고 분모에서 제외한다.
     score_norm = raw / (100 − 미측정축_배점) × 100
   잠정+컨센있음 → 82 분모 / 잠정+컨센없음 → 67 / 확정+컨센있음 → 100 / 확정+컨센없음 → 85
   0점 처리하면 커버리지 편향이 되살아나 시스템의 목적이 무너진다.
   ScreenResult에 has_consensus를 반드시 담아라.

2. 컨센서스는 n_estimates >= 2 일 때만 인정한다. 1개는 컨센서스가 아니다.

3. 기저효과 경고 (PRD §4.1)
   rev_2y 가속 / TTM 매출 최고 / 분기 최고 매출 중 하나도 못 넘기면
   base_effect_warning=true, 매트릭스 등급을 한 단계 낮춘다(★→○, ○→·).

4. 모든 입력은 Optional. 결측이면 그 항목만 건너뛰고 게이트 판정은 None(판정 불가).
   False와 None을 반드시 구분하라.

5. 적자는 게이트 탈락 + turnaround=true 별도 표시. 텔레그램 발송 대상 아님.

6. 4Q는 QoQ 관련 판정을 하지 않는다(traps.md T14).

7. raw_a1 ~ raw_d4(정규화 전 원자료)를 전부 반환하라. screen_results에 저장해
   나중에 가중치를 바꿔 재계산할 수 있어야 한다(ADR — outcome_tracking 연계).

8. 모든 임계값은 src/config/constants.py에서만 읽는다. 하드코딩 금지.

[검증] tests/test_screener.py
- 게이트 5케이스: 통과 / 매출가속 실패 / 적자 / 데이터결측 / 업종제외
- 스코어 손계산 3건 — 내가 검산할 수 있게 계산 과정을 주석에 남겨라
- 컨센서스 유/무가 동일한 종목의 정규화 점수 비교 (커버리지 없는 쪽이
  구조적으로 불리하지 않은지 확인)
- 기저효과 경고가 붙는 케이스와 등급 강등 확인
- PRI 손계산 1건 + 매트릭스 9칸 전부 분기 확인
```

---

## P4 — 공시 감지 · 잠정실적 파서

```
P4: DART 공시 폴링으로 실적 발표를 감지하고 잠정실적 표를 파싱한다.
PRD §5.1(L1, L2'), §5.3을 읽어라.

[1] src/collectors/dart_disclosure.py
- list.json을 corp_code 없이 호출(corp_cls=Y와 K 각각, bgn_de=end_de=오늘, page_count=100)
- report_nm 기준 분류:
    'provisional' : "영업(잠정)실적" 포함
    'pl_change'   : "매출액또는손익구조" 포함
    'periodic'    : "분기보고서"|"반기보고서"|"사업보고서"
- rcept_no를 PK로 하는 멱등 저장. 같은 공시를 두 번 처리하지 않는다.
- krx_universe에 없거나 is_excluded인 종목은 즉시 버린다.

[2] src/collectors/provisional_parser.py
- 잠정실적 공정공시 원문 표를 규칙 기반으로 파싱한다. KRX 표준 양식이라
  "매출액 / 영업이익 / 당기순이익 × 당기실적 / 전년동기실적 / 전기실적" 구조가 대체로 일정하다.
- 단위(원/백만원/억원)를 반드시 읽어 정규화한다.
  ★ 단위를 못 읽으면 추측해서 곱하지 말고 그 항목을 건너뛰어라(traps.md T11).
- 연결/별도 표기를 읽어 fs_div에 반영한다.
- 규칙 파싱 실패 시에만 Haiku 폴백(tool-forced JSON). 폴백 호출 건수를 로그에 남긴다.
- 파싱 결과는 is_estimate=true로 저장하고, 45일 뒤 확정치가 들어오면
  delta_from_preliminary에 변동을 기록한다(traps.md T4).

[검증 — replay]
직전 실적 시즌(2026년 7월 중순~8월 중순) 구간을 replay해서 표로 보고하라:
1. 감지된 실적 공시 건수 (doc_type별)
2. 규칙 파서 성공 / Haiku 폴백 / 실패 건수
3. 오탐(실적이 아닌 공시가 실적으로 분류) 건수 — 5% 초과 시 분류 규칙을 고쳐라
4. 단위 파싱 실패 건수와 그때 무엇을 건너뛰었는지
```

---

## P5 — 컨센서스 사전 스냅샷

```
P5: 분기 컨센서스를 발표 전에 미리 저장한다. PRD §5.1(L3), §6(consensus_snapshots).

★ 이 Phase의 존재 이유: FnGuide/네이버의 분기 컨센서스는 (E) 표기로 나오는데
실적이 발표되면 실적치로 덮여 사라진다. 발표 후에 조회하면 이미 늦다.
시즌 직전부터 주 1회 스냅샷해 쌓아야 한다.

src/collectors/consensus.py
- 소스 후보(우선순위대로 시도, 실패는 예외가 아니라 정상 케이스):
  1) comp.fnguide.com Snapshot(SVD_Main) Financial Highlight의 분기 (E) 컬럼
  2) comp.fnguide.com SVD_Consensus.asp
  3) navercomp.wisereport.co.kr 요약 컨센서스 (연간 스냅샷 — 폴백)
- n_estimates를 반드시 함께 저장한다. 2 미만이면 컨센서스로 취급하지 않는다.
- 실패 시 None 반환. 예외를 올려서 파이프라인을 죽이지 마라.
- 요청 간 간격 ≥1초, User-Agent 설정.
- 대상은 전 종목이 아니라 시총 상위 500 + 직전 분기 게이트 통과 종목으로 좁혀도 된다.

[검증]
시총 구간별 샘플 50종목(대형 15 / 중형 20 / 소형 15)에 대해:
- 파싱 성공 종목 수와 n_estimates 분포를 구간별로 보고하라
- 소형주 구간의 성공률이 낮게 나오는 것은 정상이다(PRD §2 근거).
  그 사실을 수치로 확인하는 것이 이 검증의 목적이다.
```

---

## P6 — KIS 시세 · PRI

```
P6: 한국투자증권 KIS Open API로 시세를 수집하고 PRI를 계산한다.
PRD §5.4, §4.3, traps.md T15를 먼저 읽어라.

.env에 KIS_APP_KEY / KIS_APP_SECRET가 이미 있다(실전계좌, KIS_PAPER_TRADING=false).

[1] src/collectors/kis_client.py
- 접근토큰: POST {KIS_BASE_URL}/oauth2/tokenP
  ★ 토큰을 매 실행마다 새로 받지 마라. 발급 자체에 제한이 있다.
    .cache/kis_token.json에 만료시각과 함께 캐시하고 만료 전까지 재사용한다.
- ★ 유량 제한 실전 초당 20건. 토큰버킷 스로틀러(안전 마진 18/초)를 반드시 구현하라.
  1,300종목 순회 시 스로틀이 없으면 중간에 EGW00201로 죽는다.
- ★ 주문 API 호출 금지. KIS_ALLOWED_PATHS 화이트리스트 밖은 호출하지 않는다.
  화이트리스트 검사를 클라이언트 내부에 강제로 넣어라.

[2] src/collectors/kis_prices.py
- 현재가 시세: GET /uapi/domestic-stock/v1/quotations/inquire-price
  tr_id=FHKST01010100, FID_COND_MRKT_DIV_CODE=J, FID_INPUT_ISCD=종목코드6자리
- 기간별 시세(일봉): /uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice
  tr_id=FHKST03010100, FID_PERIOD_DIV_CODE=D, FID_ORG_ADJ_PRC=0
- ★ 응답 필드명을 추정으로 박지 마라. 삼성전자로 실제 1회 호출해
  응답 JSON 전체를 출력한 뒤 필드명을 확정하고 코드에 넣어라.
  (유력 후보이지만 미확인: stck_prpr, w52_hgpr, w52_lwpr, per, pbr, eps,
   hts_avls(시가총액 억원), acml_tr_pbmn(누적거래대금))
- 폴백: KIS 장애·토큰 문제 시 네이버 시세 API로 자동 전환.
  시세 실패가 스크리닝 전체를 막으면 안 된다 — PRI만 미측정 처리하고 정규화한다.

[3] 지수 스냅샷(KOSPI/KOSDAQ) — 상대수익률 계산에 필요

[4] src/screener/pri.py 완성 — P1(3M 상대수익률) P2(52주 위치)
    P3(PER 3년 밴드 백분위) P4(D+1 반응). P4는 발표 다음 거래일에만 계산.

[검증]
1. 토큰 캐시가 실제로 재사용되는지 (두 번 실행해 발급 호출이 1회인지 확인)
2. 1,300종목 순회 시 스로틀이 걸려 EGW00201이 나지 않는지 (실제로 돌려볼 것)
3. 응답 필드명 확정 결과를 표로 보여줘라
4. 삼성전자·리노공업·HPSP의 3개월 상대수익률을 손계산으로 대조
5. KIS를 강제로 실패시켰을 때 네이버 폴백이 작동하는지
```

---

## P7 — LLM 분석 · cost guard

```
P7: 게이트 통과 ★○ 종목에 대한 Sonnet 해석. PRD §7, §11을 읽어라.

[1] src/analysis/analyze.py + src/analysis/prompts/

★ 비용 설계가 이 Phase의 핵심이다.
- 공시 원문 전체를 넣지 마라. 숫자는 이미 DB에 정확히 있다.
  입력은 PRD §7.1의 7개 블록(구조화 표 + 발췌 2,000자)만, 총 5,000토큰 이내.
- 시스템 프롬프트에 cache_control: ephemeral 적용.
  종목마다 바뀌는 내용을 시스템 프롬프트에 넣으면 캐시가 통째로 깨진다.
- tool-forced JSON, 스키마는 PRD §7.2 그대로.
- max_tokens=8192. stop_reason == "max_tokens"이면 명시적으로 실패 처리하라.
  잘린 JSON을 저장하면 대시보드가 나중에 500을 낸다.

[2] src/utils/cost_guard.py
참고: C:\Claude\dev\HermesCall\src\utils\cost_guard.py 를 이식하되 두 가지를 바꿔라.
  1) 날짜 기준 가격 전환 로직을 제거하라. Sonnet 5는 $2/$10이 정가로 확정됐고
     2026-09-01 인상은 시행되지 않는다.
  2) cost_log에 env 컬럼. check_budget은 env='prod'만 집계한다.
     (참고 프로젝트는 개발 중 테스트 실행이 운영 일일 상한을 잡아먹어
      실제 이벤트가 큐로 밀린 사고가 있었다.)
MONTHLY_COST_CEILING_USD=8, DAILY_ANALYSIS_LIMIT=20
월 실링 도달 시 우선순위 큐로 이월하고 텔레그램으로 통지한다.

[검증] 내 승인을 받은 뒤 실제 1회 호출:
- 비용이 $0.05 이하인가
- JSON 전 필드가 채워지는가 (특히 triggers.within_3m/within_6m,
  scenarios 확률 합이 1.0 근처인가, acceleration_quality.is_genuine이 있는가)
- cost_log에 env='prod'로 기록되는가
- 두 번째 호출에서 cache_read_input_tokens가 잡히는가(캐시가 실제로 먹는지)
```

---

## P8 — 텔레그램

```
P8: 텔레그램 발송. 봇은 @Invest_EarningCallBot (HermesCall과 공유). PRD §8을 읽어라.

★★ 절대 하지 말 것: setWebhook 호출.
텔레그램은 봇당 웹훅을 하나만 허용한다. HermesCall 대시보드가 이미 점유 중이므로
새로 등록하면 HermesCall 봇 명령어(/list /cost /status 등)가 조용히 죽는다.
Heimdallr는 sendMessage 발송 전용이다.

src/notify/telegram.py
- 메시지 프리픽스 🛡️ (HermesCall의 ⚡/🔬와 구분)
- 템플릿: PRD §8.3(즉시 알림) / §8.4(일일 요약) / §8.5(승격 알림)
- 발송 대상은 매트릭스 등급 ★ 와 ○ 만. △와 ·는 대시보드에만.
- 발송 전 notifications의 UNIQUE(code, fy, fq, kind)로 중복 차단.
  텔레그램/Actions 재시도로 같은 알림이 두 번 나가는 건 실제로 자주 있다.
- ★ rate limit: 연속 발송 사이 1초 간격, 429의 retry_after 존중 백오프 3회.
  봇 토큰을 HermesCall과 공유하므로 한도를 나눠 쓴다.
- 메시지 4,096자 제한. 일일 요약이 넘치면 상위 N개로 자르고 "외 M종목" 표기.
- 발송 실패해도 파이프라인 전체를 죽이지 마라. DB에 이미 저장되어 대시보드로 확인 가능하다.

또한 dashboard/app/api/telegram/lookup 엔드포인트를 미리 만들어 둬라(지금은 미사용).
나중에 HermesCall 웹훅에서 "watchlist에서 못 찾으면 Heimdallr로 넘김" 폴백을 붙일 때
HermesCall 쪽 5줄만 고치면 되게 하기 위함이다.

[검증] 샘플 데이터로 실제 발송 1건. 같은 payload로 두 번째 호출 시 차단 확인.
```

---

## P9 — 대시보드

```
P9: Next.js 14(App Router) + Supabase anon + Tailwind + Recharts. PRD §9를 읽어라.
HermesCall dashboard/ 의 lib/ 패턴과 컴포넌트 구조를 참고하되 화면은 새로 만든다.

우선순위대로:
1) /stock/[code]  ← 시스템의 핵심 화면. 먼저 만들어라. (PRD §9.1)
2) /              발굴 목록 (등급·스코어·반영도)
3) /matrix        2축 산점도 (X=스코어, Y=주가반영도, 사분면 색상)
4) /screener  5) /season  6) /outcome  7) /settings

/stock/[code]에서 특히:
- 8분기 이중축 차트에서 ★매출 YoY 성장률 라인이 주인공이다. 가속이 눈으로 보여야 한다.
  막대(매출·영업이익)보다 성장률 라인을 시각적으로 강조하라. TTM은 점선.
- 스코어는 A/B/C/D 스택 바로 분해. 총점만 보여주면 왜 뽑혔는지 모른다.
- PRI도 P1~P4 분해 바로 보여라.
- 경고 배지 필수: 컨센서스 없음(정규화) / 기저효과 경고 / 업종 주의 / 잠정치

[HermesCall에서 실제로 터졌던 것 — 반드시 방어하라 (PRD §9.2)]
1. analyses.payload는 부분적으로만 채워질 수 있다. 상위 객체만 확인하고 하위 필드를
   읽으면 페이지 전체가 500이 난다. 반드시 필드 단위로 확인하라.
2. 새 컬럼을 추가하면 내가 SQL Editor에 적용하기 전까지 공백이 생긴다. 그 사이
   쓰기는 PGRST204, 조회는 42703으로 각각 파이프라인과 페이지를 죽인다.
   누락 컬럼을 감지해 제외하고 재조회하는 루프 패턴을 쓰라(PostgREST는 누락 컬럼을
   한 번에 하나씩만 알려주므로 루프가 필요하다).
3. 1,300종목 조회는 range() 페이징.
4. Vercel Deployment Protection이 기본 켜져 있으면 외부 접근이 401로 막힌다.

[검증] 브라우저로 /stock/[code] 렌더, 8분기 차트, 2축 산점도까지 실제 확인.
```

---

## P10 — GitHub Actions

```
P10: 자동화 배선. PRD §10을 읽어라.

워크플로우 6개:
  universe_daily.yml     0 21 * * *      (06:00 KST) 유니버스+시세+PRI
  disclosure_poll.yml    시즌 */15 0-10 * * 1-5 / 비시즌 0 1,4,7,10 * * 1-5
  daily_digest.yml       30 8 * * 1-5    (17:30 KST)
  quarterly_backfill.yml 0 20 1,15 * *   + workflow_dispatch
  outcome_update.yml     0 22 * * 1-5
  promotion_check.yml    0 22 * * 1      (월요일 승격 확인)

[비용]
- repo를 public으로 둘 것을 권한다. private은 Actions 무료 2,000분/월인데
  시즌 폴링만으로 38회/일 × 2분 × 20영업일 = 1,520분/월이라 위험하게 근접한다.
  public은 무제한 무료다. 시크릿은 GitHub Secrets에 있고 Supabase anon key는
  원래 공개 전제 + RLS로 방어되므로 코드 공개가 문제되지 않는다.
- SEASON_MODE 리포지토리 변수로 폴링 빈도를 전환하라.
- ★ 잡 안에서 sleep 루프를 쓰지 마라. sleep도 과금된다. 짧은 잡을 여러 번 띄우는
  편이 싸다. 잡당 timeout 15분.

[주의]
- 새 서드파티 임포트는 반드시 pyproject.toml에 선언하라. 로컬 venv에 수동 설치돼
  있으면 로컬은 전부 통과하고 Actions의 깨끗한 `pip install -e .` 환경에서만 죽는다.
  검증: python -m venv /tmp/x && /tmp/x/bin/pip install -e . 후 실제 경로 1회 실행.
- KIS 토큰 캐시는 Actions 러너에서 매번 초기화된다. actions/cache로 .cache/를
  보존하거나 Supabase에 저장하라. 안 하면 매 실행마다 토큰을 새로 받아 곧 막힌다.

[검증] workflow_dispatch로 6개를 각 1회씩 수동 실행해 end-to-end 성공 확인.
```

---

## P11 — 결과 추적

```
P11: outcome_tracking 배선. PRD §2 검토⑥, §6을 읽어라.

★ 이 Phase의 존재 이유: 스코어 배점(14/10/6…)에는 현재 이론적 근거가 없다.
나중에 데이터로 조정할 수 있는 구조를 지금 만들어 두지 않으면 이 시스템은
영구히 검증 불가능한 자의적 룰로 남는다.

src/analysis/outcome.py
- 발표일 D 기준 D+1 / D+5 / D+20 / D+60 종가 수익률
- 동일 기간 소속 지수(KOSPI/KOSDAQ) 수익률 대비 초과수익
- 발표 시점의 grade / score / pri를 함께 스냅샷 (사후 재계산 방지)
- 거래정지·상장폐지 종목 처리(수익률 None, 사유 기록)

dashboard/app/outcome
- 등급별(★○△·) D+20 / D+60 초과수익 분포 (박스플롯 또는 히스토그램)
- 스코어 축별(A/B/C/D) 정보계수(IC) — raw 값과 초과수익의 순위상관
- has_consensus 유/무 그룹 비교 (SC6 검증)
- base_effect_warning 유/무 그룹 비교 (SC8 검증)

[검증]
직전 분기(2026 2Q) 하나를 backfill해서:
1. 등급별 종목 수와 D+20 초과수익 중앙값을 표로 출력
2. ★ 그룹의 초과수익 중앙값이 · 그룹보다 높은지 확인
   (표본이 작아 통계적 유의성은 없다 — 그래도 방향은 봐야 한다)
3. 축별 IC를 계산해 어느 축이 실제로 작동하는지 보여줘라
```

---

## 세션 종료 프로토콜 (매 Phase 공통)

```
이번 세션을 마무리하자.
1. docs/sessions/2026-MM-DD.md 에 상세 기록을 써라
   (한 일 / 실측으로 확인한 수치 / 막힌 것 / 다음 세션이 알아야 할 것)
2. 실측으로 새로 발견한 함정이 있으면 docs/traps.md 에 추가하라.
   "무엇이 어떻게 조용히 틀리는가"를 반드시 포함할 것.
3. CLAUDE.md 세션 진행 상황에 3줄 이내 요약만 추가하고,
   250줄이 넘으면 가장 오래된 항목을 지워라.
4. 되돌리면 안 되는 설계 결정을 내렸다면 docs/decisions/NNN-제목.md 로 남겨라.
```

## "완료" 선언을 받았을 때 되물을 것

> 실제로 돌려서 확인한 수치를 보여줘. 테스트가 통과했다는 말 말고,
> 실제 데이터로 뭐가 나왔는지.

참고 프로젝트에서 가장 값비쌌던 실수(lxml 30% 유실, 단위 혼용, PostgREST 1,000행 절단,
Finnhub 1500건 상한)는 전부 **에러 없이 조용히 품질만 나빠지는** 종류였다.
