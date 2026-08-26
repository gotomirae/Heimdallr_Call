# Heimdallr_Call — PRD v2.1 (Final)

> **이 문서 하나만으로 구현이 가능해야 한다.** Claude Code 세션 시작 시 이 파일을 먼저 읽힌다.
> 버전: v2.1 · 작성일: 2026-08-13
> 참고 프로젝트: `C:\Claude\dev\HermesCall` (코드 패턴 참고, 인프라·스키마는 완전 분리)
> 변경 이력: v1.0(게이트+스코어 3축) → v2.0(설계 검토 반영 — §2) → **v2.1(KIS Open API를 시세 1차 소스로 채택 — §5.4)**

---

## 목차

1. 목적과 성공 기준
2. **v1 설계 검토 결과 — 무엇을 왜 바꿨는가** ← 먼저 읽을 것
3. 유니버스
4. 발굴 로직 (게이트 · 스코어 · 주가반영도 · 2축 매트릭스)
5. 데이터 아키텍처
6. DB 스키마
7. LLM 분석
8. 텔레그램
9. 대시보드
10. 자동화 · 운영
11. 비용 설계
12. 함정 목록 (조용히 틀리는 것들)
13. Phase 계획 · 검증 게이트
14. 리스크
- 부록 A: 상수 테이블
- 부록 B: 업종 예외 처리

---

## 1. 목적과 성공 기준

### 1.1 목적

KOSPI/KOSDAQ 시가총액 1,000억원 이상 약 1,300종목을 대상으로, **분기실적이 실제로 가속되고 있으면서 그 사실이 아직 주가에 충분히 반영되지 않은 종목**을 매 분기 자동 발굴하고, 텔레그램(🛡️ @Invest_EarningCallBot)으로 알리며, 전용 대시보드에서 투자 판단에 필요한 근거를 한 화면에서 확인하게 한다.

> **목적문에서 "아직 주가에 반영되지 않은"이 v2의 핵심 추가다.** v1은 "가속 종목 발굴"까지였다. 발굴만으로는 "최적의 투자 판단"에 도달하지 못한다 — 좋은 기업과 좋은 투자는 다르다.

### 1.2 성공 기준 (측정 가능)

| # | 기준 | 측정 방법 | 목표 |
|---|---|---|---|
| SC1 | 유니버스 누락 0건 | KIND 원문 `<tr>` 수 대조 + 네이버 전수 스캔 교차 | 100% |
| SC2 | 분기 수치 정확도 | 대형·중형·소형 3사 × 8분기를 DART 원문과 수동 대조 | 100% 일치 |
| SC3 | 감지 → 알림 지연 | `disclosed_at` vs `notifications.sent_at` | 30분 이내 |
| SC4 | 중복 알림 | `notifications` UNIQUE 제약 위반 건수 | 0건 |
| SC5 | 월 LLM 비용 | `cost_log` where env='prod' | $8 이하 |
| SC6 | **커버리지 편향 부재** | 분기 상위 20종목 중 `has_consensus=false` 비율 | ≥ 30% |
| SC7 | **발굴 유효성** | ★등급 종목의 D+20 지수대비 초과수익 중앙값 | > 0% (시즌 2회 후 평가) |
| SC8 | **기저효과 오탐** | `base_effect_warning=true`인데 ★로 분류된 비율 | < 10% |

> SC6·SC7·SC8이 v2 신설이다. SC6은 시스템의 존재 이유를, SC7은 실제로 맞았는지를, SC8은 가짜 가속을 거르는지를 잰다.

---

## 2. v1 설계 검토 결과 — 무엇을 왜 바꿨는가

v1 구조(게이트 = 매출 YoY 가속 + 영업이익 흑자·성장 / 스코어 A40·B35·C15·D10)를 목적 달성 관점에서 검토한 결과, **구조 자체는 옳으나 6개 지점에서 조용히 오작동할 수 있다.** 각각을 어떻게 고쳤는지 아래에 정리한다.

### 검토 ① 기저효과가 "가짜 가속"으로 잡힌다 — **가장 큰 결함**

`rev_yoy(t) > rev_yoy(t-1)`은 분자(당기)뿐 아니라 **분모(전년동기)에도 좌우된다.** 전전년 동기(t-5)가 비정상적으로 높았으면 `rev_yoy(t-1)`이 낮게 나오고, 그 결과 t가 자동으로 "가속"으로 잡힌다. 매출이 실제로는 정체 중인데도 그렇다.

**대응 — 2년 스택 성장률(2-year stacked growth)을 보조 지표로 도입:**
```
rev_2y(t) = revenue(t) / revenue(t-8) - 1
```
기저효과가 중화된다. 게이트는 통과시키되 다음 중 어느 것도 만족하지 못하면 `base_effect_warning = true`를 붙이고 알림 등급을 한 단계 내린다.
- `rev_2y(t) > rev_2y(t-1)` (2년 스택도 가속) — t-9까지 필요
- `TTM_revenue(t)`가 8분기 중 최고
- `revenue(t) > max(revenue(t-1..t-4))` (분기 최고 매출 경신)

### 검토 ② QoQ 지표가 계절성에 통째로 오염된다

한국 기업 상당수가 강한 계절성을 갖는다(4Q 비용 몰아넣기, 1Q 저조, 반도체·화학의 성수기 편중). v1의 A3(매출 QoQ)와 B2(OPM QoQ)는 계절성을 그대로 점수로 환산한다. **계절적으로 좋은 분기에 발표하는 기업이 구조적으로 유리해진다.**

**대응 — QoQ를 TTM(4분기 누적) 추세로 교체:**
- A3: `TTM_revenue(t) > TTM_revenue(t-1)` 및 증가율 (계절성 자동 제거)
- B2: `TTM_OPM(t) - TTM_OPM(t-1)` (%p)

TTM은 4분기를 다 담으므로 계절 요인이 상쇄된다. QoQ 원자료는 계속 저장·표시하되 **점수에는 쓰지 않는다.**

### 검토 ③ 일회성 이익과 회계 품질을 거르지 못한다 — v1의 D축이 너무 약했다

영업이익에는 충당금 환입, 보험금 수령, 재고평가손 환입 같은 일회성이 섞일 수 있다. 이익은 늘었는데 현금은 안 들어오는 경우(accrual anomaly)도 흔하다. 코스닥 소형주는 유상증자·전환사채로 **주식 수가 늘어 주주 몫은 그대로**인 경우가 특히 잦다.

**대응 — D축을 10점 → 18점으로 강화하고 항목을 재구성:**
- D1 현금흐름 정합성: `TTM CFO > 0` **AND** `TTM CFO / TTM 영업이익 ≥ 0.5` (6점)
- D2 **주식수 희석**: 발행주식총수 YoY < +5% (4점) — DART `stockTotqySttus.json`으로 무료 조회
- D3 운전자본: `(매출채권+재고) YoY < 매출 YoY` (4점) — 밀어내기·부실채권 방어
- D4 유동성: 20일 평균 거래대금 ≥ 10억원 (4점)

### 검토 ④ "이미 주가에 반영되었는가"라는 축이 스코어와 분리만 되어 있었다 — **목적 달성의 급소**

v1은 밸류에이션을 LLM 해석과 대시보드 표시로만 두었다. 그러나 실적 가속 종목의 상당수는 **발표 전 3개월간 이미 올라 있다.** 발굴은 됐는데 "지금 사도 되는가"에는 답하지 못하는 시스템이 된다.

**대응 — 주가반영도 지수(PRI, Price Reflection Index)를 별도 축으로 신설하고 2축 매트릭스로 분류한다.**

> **스코어에 합산하지 않는다.** 펀더멘털 강도와 주가 반영도는 서로 다른 축이고, 하나의 숫자로 뭉개면 둘 다 못 읽는다. 반드시 **2축으로 병기**한다.

### 검토 ⑤ 잠정실적 시점에는 D축 데이터가 아예 없다

잠정실적 공정공시는 매출·영업이익·순이익 3개만 준다. FCF·CFO·운전자본·주식수는 45일 뒤 정기보고서에서 온다. v1은 이 시차를 설계에 반영하지 않아, 잠정 시점 스코어가 D축 0점으로 계산되어 **모든 종목이 부당하게 낮게 나온다.**

**대응 — 2단계 스코어:**
- `score_flash` — 잠정실적 시점. A+B+C(82점 만점)를 100점으로 정규화. 발송·알림은 이 값 기준.
- `score_final` — 정기보고서 확정 후. A+B+C+D(100점 만점).
- 둘의 차이(`score_delta`)를 대시보드에 표시. **확정치가 잠정보다 나빠졌으면 그 자체가 경고 신호다.**

### 검토 ⑥ 발굴이 맞았는지 검증할 방법이 없다 — 지금 안 넣으면 영원히 못 넣는다

배점(14점/10점/6점…)에는 현재 이론적 근거가 없다. 초기에는 불가피하지만, **나중에 데이터로 조정할 수 있는 구조**를 지금 만들어 두지 않으면 이 시스템은 영구히 검증 불가능한 자의적 룰로 남는다.

**대응 — `outcome_tracking` 테이블 신설.** 발표일 D 기준 D+1 / D+5 / D+20 / D+60의 주가 수익률과 동일 기간 지수(KOSPI/KOSDAQ) 대비 초과수익을 자동 기록한다. 시즌 2회(6개월) 뒤 각 스코어 축의 정보계수(IC)를 계산해 가중치를 조정한다. **`screen_results`에 정규화 전 raw 값을 전부 저장**해 두어야 사후 재계산이 가능하다.

### 검토 ⑦ (추가) 업종에 따라 지표가 무의미해진다

- **금융업**(은행·보험·증권·여신): 매출액 개념이 다르고 영업이익률이 의미 없음
- **지주회사**: 연결 매출이 자회사 합산이라 가속 판정이 왜곡
- **부동산·리츠·스팩**: 분기 실적 개념 부적합
- **건설·조선·플랜트**: 진행기준 매출이라 분기 변동이 크고 수주잔고 병행 필요

**대응 — 게이트 G3에 업종 제외 필터 신설**(부록 B). 건설·조선·바이오는 제외하지 않되 `sector_caveat` 플래그로 화면에 주의를 표시한다.

### 검토 결과 종합 — v1 → v2 변경 요약

| 항목 | v1 | v2 | 이유 |
|---|---|---|---|
| 게이트 | G0·G1·G2 | + **G3 업종 제외**, G1에 **기저효과 경고** | 검토 ①⑦ |
| A 성장 가속 | 40 (QoQ 포함) | **35** (QoQ → **TTM 추세**) | 검토 ② |
| B 수익성 | 35 (QoQ 포함) | **32** (QoQ → **TTM 추세**) | 검토 ② |
| C 서프라이즈 | 15 | 15 (변경 없음) | — |
| D 질 | 10 | **18** (CFO 정합성·주식수 희석 신설) | 검토 ③ |
| 주가 반영 | LLM 해석에만 | **PRI 별도 축 + 2축 매트릭스** | 검토 ④ |
| 스코어 시점 | 단일 | **flash / final 2단계** | 검토 ⑤ |
| 결과 검증 | 없음 | **outcome_tracking** | 검토 ⑥ |

> **바꾸지 않은 것과 그 이유**: 게이트를 "실적 가속"으로 두고 서프라이즈를 C축 가점으로 내린 v1의 핵심 판단은 그대로다. 코스닥 1,819사 중 1,089사(59.9%)가 최근 1년 증권사 리포트 0건이라는 사실(에프앤가이드, 2026-06)이 바뀌지 않았기 때문이다. 컨센서스 없는 종목의 C축을 **0점이 아니라 분모 제외 정규화**로 처리하는 규칙도 그대로다 — 이것이 이 시스템의 존재 이유를 지키는 단 하나의 규칙이다.

---

## 3. 유니버스

### 3.1 범위
- KOSPI + KOSDAQ 전 상장사 중 **시가총액 1,000억원 이상**
- 참고 실측: 2026-08-09 기준 1,311종목 (HermesCall)
- 우선주·ETF·ETN·리츠는 KIND 상장법인목록(법인 기준) 조인에서 자연 제외

### 3.2 제외 (게이트 G3)
- 관리종목 · 투자주의환기종목 · 거래정지
- 스팩(SPAC)
- 업종 제외 리스트 (부록 B)
- 신규 상장 후 5개 분기 미만 (별도 "신규 상장 관찰" 리스트로 분리)

### 3.3 갱신
하루 1회 06:00 KST. KIND 상장법인목록 + 네이버 시가총액 API + DART `corpCode.xml`을 조인.

---

## 4. 발굴 로직

### 4.1 게이트 (전부 AND — 하나라도 실패하면 알림 대상 아님)

| ID | 조건 | 실패 시 |
|---|---|---|
| **G0** | `t`, `t-1`, `t-4`의 매출·영업이익이 모두 존재 | 판정 불가 (None) — False와 구분할 것 |
| **G1** | `rev_yoy(t) > rev_yoy(t-1)` **AND** `rev_yoy(t) > 0` | 탈락 |
| **G2** | `op(t) > 0` **AND** `op_yoy(t) > op_yoy(t-1)` **AND** `op_yoy(t) > 0` | 탈락 (단, 흑자전환은 `turnaround=true`로 별도 리스트) |
| **G3** | 업종 제외 리스트 · 관리종목 · 스팩 · 히스토리 부족에 해당하지 않음 | 탈락 |
| **G4** | `opm_yoy_delta(t) > 0` (영업이익률이 전년 동기보다 상승) | 탈락 · 결측이면 판정 불가 (None) |

**G4 — OPM YoY 상승** (2026-08-22 추가)
매출과 영업이익이 둘 다 가속해도 **이익률이 전년보다 낮아졌다면** 그것은 '싸게 많이 판 것'이다.
G1·G2가 성장의 *속도*를 본다면 G4는 *질*을 본다. 화면 문구가
"매출 YoY 가속 + 영업이익 YoY 가속 + OPM YoY 상승"이라고 말하려면 게이트가 실제로 셋을 봐야 한다.
**크기가 아니라 방향만 묻는다**(`G4_OPM_DELTA_MIN_PP = 0.0`) — 얼마나 올랐는지는 스코어 B1이 점수로 잰다.

**G1 보조 판정 — 기저효과 경고**
다음 3개 중 **하나도** 충족하지 못하면 `base_effect_warning = true`:
- `rev_2y(t) > rev_2y(t-1)` where `rev_2y(t) = revenue(t)/revenue(t-8) - 1`
- `TTM_revenue(t)`가 최근 8분기 TTM 중 최고
- `revenue(t) > max(revenue(t-1), revenue(t-2), revenue(t-3), revenue(t-4))`

경고가 붙으면 **2축 매트릭스 등급을 한 단계 낮춘다**(★→○, ○→·).

**적자 기업 취급**
- `op(t) ≤ 0` → 게이트 탈락. 단 `op(t-4) ≤ 0 < op(t)`(흑자전환) 또는 적자 축소는 `turnaround=true`로 대시보드에만 표시하고 텔레그램 발송은 하지 않는다.
- **부호가 바뀌는 구간에서 성장률 %는 계산하지 말 것.** `'흑전' | '적전' | '적자축소' | '적자확대'` 상태 라벨을 쓴다.

### 4.2 스코어 (100점)

#### A. 성장 가속 — 35점

| ID | 항목 | 배점 | 산식 |
|---|---|---|---|
| A1 | 매출 YoY 델타 | 10 | `Δ = rev_yoy(t) − rev_yoy(t−1)` · Δ≤0→0 · Δ≥20%p→10 · 선형 |
| A2 | **영업이익 YoY 델타** | 15 | 동일 방식 · Δ≥40%p→15 |
| A3 | **TTM 영업이익 상승** | 4 | `TTM_op(t) > TTM_op(t−1)`→2 · 증가율 ≥5%→+2 |
| A4 | 2분기 연속 가속 | 6 | 2분기 연속 G1 충족→6 |

**2026-08-22 개정** (사용자 지시): A축 35점을 재분배했다 — 합계는 그대로다(바뀌면 정규화 분모
82/67/100/85가 전부 어긋난다). A2를 A축 최대 배점으로 올렸고, A3는 대상을 **TTM 매출 → TTM
영업이익**으로 바꿨다. 그 결과 A축은 매출 1항목 · 이익 3항목이 된다.
A3의 증가율 보너스는 `TTM_op(t−1) > 0`일 때만 준다 — 적자 구간에서 %를 만들면 적자 축소가
수백 %의 '성장'으로 둔갑한다.

#### B. 수익성 — 32점

| ID | 항목 | 배점 | 산식 |
|---|---|---|---|
| B1 | OPM YoY %p | 14 | +1%p→5 · +3%p→10 · +5%p 이상→14 (선형 보간) |
| B2 | **TTM OPM 추세 %p** | 7 | `TTM_OPM(t) − TTM_OPM(t−1)` · +0.5%p→3 · +2%p 이상→7 |
| B3 | 영업레버리지 | 6 | `op_yoy(t) > rev_yoy(t)`→6 |
| B4 | 업종 대비 OPM | 5 | 동일 KRX 업종 중앙값 대비 상위 50%→3 · 상위 25%→5 |

#### C. 서프라이즈 — 15점 (컨센서스 보유 종목만)

| ID | 항목 | 배점 | 산식 |
|---|---|---|---|
| C1 | 영업이익 서프라이즈 | 9 | `(op − op_est)/\|op_est\|` · +3%→3 · +10%→6 · +20% 이상→9 |
| C2 | 매출 서프라이즈 | 6 | +2%→2 · +5%→4 · +10% 이상→6 |

> **추정기관 수 `n_estimates` ≥ 2**일 때만 컨센서스로 인정한다. 1개는 컨센서스가 아니다.

#### D. 회계 품질 — 18점 (정기보고서 확정 후에만 측정 가능)

| ID | 항목 | 배점 | 산식 |
|---|---|---|---|
| D1 | 현금흐름 정합성 | 6 | `TTM CFO > 0`→3 · `TTM CFO / TTM OP ≥ 0.5`→+3 |
| D2 | 주식수 희석 | 4 | 발행주식총수 YoY < +2%→4 · < +5%→2 · 그 이상→0 |
| D3 | 운전자본 | 4 | `(매출채권+재고) YoY < 매출 YoY`→4 |
| D4 | 유동성 | 4 | 20일 평균 거래대금 ≥ 10억원→4 · ≥ 5억원→2 |

#### 정규화 규칙 (★ 이 프로젝트에서 가장 중요한 계산 규칙)

측정 불가능한 축은 **0점 처리하지 않고 분모에서 제외한다.**

```python
score_norm = raw_sum / (100 - sum(미측정축_배점)) * 100
```

| 상황 | 측정 축 | 분모 | 비고 |
|---|---|---|---|
| 잠정실적 + 컨센서스 있음 | A+B+C | 82 | `score_flash` |
| 잠정실적 + 컨센서스 없음 | A+B | 67 | `score_flash`, 배지 표시 |
| 확정 + 컨센서스 있음 | A+B+C+D | 100 | `score_final` |
| 확정 + 컨센서스 없음 | A+B+D | 85 | `score_final`, 배지 표시 |

> **왜 0점 처리하면 안 되는가**: 코스닥의 60%는 애널리스트 커버리지가 없다. C축을 0점 처리하면 커버리지 없는 종목이 구조적으로 15점 손해를 보고 상위에서 밀려난다. 그러면 이 시스템은 결국 대형주만 뽑게 되고 — **존재 이유가 사라진다.** SC6(상위 20 중 커버리지 없는 종목 ≥30%)으로 이 규칙이 지켜지는지 상시 감시한다.

### 4.3 주가반영도 지수 PRI (0~100, 낮을수록 미반영)

**스코어와 합산하지 않는다. 별도 축으로 병기한다.**

| ID | 항목 | 배점 | 산식 |
|---|---|---|---|
| P1 | 발표 전 3개월 상대수익률 | 40 | vs 소속 지수(KOSPI/KOSDAQ) 초과수익 · −10%p 이하→0 · 0%p→20 · +30%p 이상→40 |
| P2 | 52주 위치 | 25 | `(close − low52)/(high52 − low52)` × 25 |
| P3 | Fwd PER 밴드 위치 | 20 | 3년 PER 밴드 내 백분위 × 20 (컨센서스 없으면 **미측정 → 정규화**) |
| P4 | 발표 반응 | 15 | D+1 지수대비 초과수익 · 0% 이하→0 · +10% 이상→15 |

> P4는 발표 다음 거래일에만 계산 가능하다. 즉시 알림(⚡) 시점에는 P1~P3(85점 만점 정규화)만 쓰고, 다음날 갱신한다.

### 4.4 2축 매트릭스 — 최종 분류 (알림·판단의 결론)

|  | **PRI < 40 (미반영)** | **PRI 40~65 (부분반영)** | **PRI > 65 (선반영/과열)** |
|---|---|---|---|
| **스코어 ≥ 75** | ★ **최우선** | ○ **관심** | △ **추격 주의** |
| **스코어 60~75** | ○ **관심** | · 관찰 | · 관찰 |
| **스코어 < 60** | · 관찰 | · 관찰 | ✕ 제외 |

- **텔레그램 ⚡ 즉시 알림: ★ 와 ○ 만.** △와 ·는 대시보드에만 표시한다.
- `base_effect_warning = true`면 등급을 한 단계 낮춘다 (★→○, ○→·).
- `sector_caveat = true`(건설·조선·바이오 등)면 등급은 유지하되 알림 본문에 주의 문구를 붙인다.
- **LLM 분석 대상: ★ 와 ○ 전체** (분기 최대 40종목, 일일 상한 20건)

> **△(고스코어·고반영) 종목을 버리지 않는 이유**: 실적이 계속 가속 중인데 이미 오른 종목은 "지금 사면 안 되는 종목"이 아니라 **"조정 시 담을 종목"**이다. 대시보드에 남겨 두고 PRI가 떨어지면 자동으로 ○/★로 승격되게 한다. 이것이 이 시스템을 시즌 이후에도 계속 쓰게 만드는 부분이다.

### 4.5 예상 통과량 (설계 검산)

| 단계 | 추정 | 근거 |
|---|---|---|
| 유니버스 | 1,300종목 | 실측 1,311 |
| 실적 데이터 확보 | ~1,200 | 결측·업종 제외 |
| 게이트 통과 | **~130종목 (약 10%)** | 매출 가속 ~30% × 이익 성장 ~35% |
| 스코어 ≥ 60 | ~70종목 | |
| ★ + ○ | **~30종목/분기** | LLM 분석 대상 |
| ★ | ~10종목/분기 | 최우선 |

시즌 4~5주에 분산되므로 **하루 평균 1~2건 알림**. 피크일에도 상위 15건으로 컷.

---

## 5. 데이터 아키텍처

### 5.1 계층

| 계층 | 소스 | 주기 | LLM | 비용 |
|---|---|---|---|---|
| L0 유니버스 | KIND 상장법인목록 + 네이버 시총 + DART `corpCode.xml` | 1일 1회 | ✗ | $0 |
| L1 이벤트 감지 | DART `list.json` (`corp_cls=Y/K`, corp_code 없이 전체) | 15분(시즌) | ✗ | $0 |
| L2 확정 재무 | DART `fnlttMultiAcnt.json` (**최대 100 corp_code/콜**) | 분기 배치 | ✗ | $0 |
| L2' 잠정 재무 | 잠정실적 공정공시 표 → 규칙 파서, 실패 시 Haiku | 이벤트 시 | 폴백만 | ~$0.012/건 |
| **L2″ 정밀 재무** | DART `fnlttSinglAcntAll.json` (CF 포함) + `stockTotqySttus.json` | **게이트 통과 종목만** | ✗ | $0 |
| L3 컨센서스 | FnGuide/네이버 **사전 스냅샷** | 주 1회(시즌 전~중) | ✗ | $0 |
| L4 시세 | **한국투자증권 KIS Open API** (1차) / 네이버 시세 API (폴백) + 지수 | 1일 1회 | ✗ | $0 |
| L5 스크리닝 | 순수 함수 (게이트·스코어·PRI·매트릭스) | 이벤트 시 | ✗ | **$0** |
| L6 해석 | Anthropic Sonnet 5, **구조화 입력만** | ★○ 종목만 | ✓ | ~$0.042/종목 |
| L7 결과 추적 | 네이버 시세 (D+1/5/20/60) | 1일 1회 | ✗ | $0 |

**설계 원칙 3개**
1. **선별에 LLM을 쓰지 않는다.** DART가 구조화 재무를 무료로 준다. LLM은 해석 전용.
2. **정밀 데이터는 게이트 통과 후에만 수집한다.** 전체 재무제표(종목당 1콜)를 1,300종목에 돌리면 1,300콜이지만, 게이트 통과 130종목만 받으면 130콜이다. 10배 차이.
3. **LLM 입력에 공시 원문 전체를 넣지 않는다.** 숫자는 이미 정확히 DB에 있다.

### 5.2 DART API 사용량 검산

| 작업 | 콜 수 | 비고 |
|---|---|---|
| `corpCode.xml` | 1회/주 | 전체 고유번호 ZIP |
| 최초 10분기 백필 (`fnlttMultiAcnt`) | 13 × 10 = **130콜** | 1,300÷100=13 |
| 분기 갱신 | **13콜/분기** | |
| 정밀 재무 (게이트 통과분) | 130 × 2 = **260콜/분기** | 전체재무제표 + 주식총수 |
| 공시 폴링 | 15분 × 09:00~18:30(38회) × 3페이지 = **114콜/일** | |
| 문서 원문 다운로드 | 피크일 150~200콜 | |
| **피크일 합계** | **약 350콜/일** | |

OpenDART 일일 한도(널리 인용되는 값 **20,000건/일** — *운영 전 공식 안내 재확인 필요, 추정*) 대비 **2% 미만**.

### 5.3 주요 엔드포인트 (검증 완료)

| 용도 | 엔드포인트 | 핵심 파라미터 |
|---|---|---|
| 공시 검색 | `https://opendart.fss.or.kr/api/list.json` | `corp_cls`(Y/K), `bgn_de`, `end_de`, `page_count`(최대 100). corp_code 미입력 시 조회기간 3개월 제한 |
| 다중회사 주요계정 | `https://opendart.fss.or.kr/api/fnlttMultiAcnt.json` | `corp_code`(쉼표 **최대 100개**), `bsns_year`, `reprt_code` |
| 단일회사 전체 재무제표 | `https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json` | `corp_code`, `bsns_year`, `reprt_code`, `fs_div`(CFS/OFS). `sj_div`로 BS/IS/CIS/**CF** 구분 |
| 주식의 총수 현황 | `https://opendart.fss.or.kr/api/stockTotqySttus.json` | `corp_code`, `bsns_year`, `reprt_code` → `istc_totqy`(발행주식 총수) |
| 문서 원문 | `https://opendart.fss.or.kr/api/document.xml` | `rcept_no` (ZIP 반환) |

`reprt_code`: 11013(1Q) · 11012(반기) · 11014(3Q) · 11011(사업보고서)

### 5.4 시세 소스 — 한국투자증권 KIS Open API를 1차로 쓴다

프로젝트 `.env`에 **KIS Open API 실전계좌 키(`KIS_APP_KEY` / `KIS_APP_SECRET`, `KIS_PAPER_TRADING=false`)가 이미 준비되어 있다.** 공식 API이므로 네이버 스크래핑보다 안정적이고, PRI 계산에 필요한 값(52주 고저·PER·PBR·거래대금)을 한 번에 준다.

| 용도 | 엔드포인트 | `tr_id` |
|---|---|---|
| 접근토큰 발급 | `POST https://openapi.koreainvestment.com:9443/oauth2/tokenP` | — |
| 주식현재가 시세 | `GET /uapi/domestic-stock/v1/quotations/inquire-price` | `FHKST01010100` |
| 기간별 시세(일봉) | `GET /uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice` | `FHKST03010100` |

- 요청 파라미터: `FID_COND_MRKT_DIV_CODE=J`(주식), `FID_INPUT_ISCD`=종목코드 6자리. 일봉은 `FID_INPUT_DATE_1/2`(YYYYMMDD), `FID_PERIOD_DIV_CODE=D`, `FID_ORG_ADJ_PRC=0`(수정주가).
- **유량 제한 실전계좌 초당 20건**(모의계좌는 훨씬 낮음). 1,300종목 × 1콜 = 65초 이상 — **반드시 초당 토큰버킷 스로틀러를 구현**할 것. 1건이라도 초과하면 `EGW00201` 오류가 난다.
- **접근토큰은 유효기간이 있고 재발급 호출 자체에도 제한이 있다.** 발급받은 토큰을 파일/DB에 캐시하고 만료 전까지 재사용할 것. 매 실행마다 새로 받으면 곧 발급이 막힌다.
- ⚠️ **응답 필드명은 반드시 실제 호출 1회로 확인한 뒤 코드에 박을 것.** 유력 후보: `stck_prpr`(현재가) · `prdy_ctrt`(전일대비율) · `w52_hgpr`/`w52_lwpr`(52주 최고/최저) · `per` · `pbr` · `eps` · `hts_avls`(시가총액, 억원 단위) · `acml_tr_pbmn`(누적거래대금). **추정이므로 실측 전에는 신뢰하지 말 것.**
- **폴백**: KIS 장애·토큰 문제 시 네이버 시세 API로 자동 전환. 시세 실패가 스크리닝 파이프라인 전체를 막으면 안 된다(PRI만 미측정 처리하고 정규화).
- 지수(KOSPI/KOSDAQ)도 KIS의 업종/지수 시세 API로 받되, 없으면 네이버로 폴백.

> KIS 계좌 정보(`CANO` 등)는 **주문 API에만 필요**하다. 시세 조회는 앱키/시크릿만으로 된다. 이 프로젝트는 **주문 API를 절대 호출하지 않는다** — 시세 조회 엔드포인트 화이트리스트를 코드에 두고 그 밖은 호출 금지.

---

## 6. DB 스키마 (Supabase 신규 프로젝트)

> HermesCall과의 근본 차이: **`watchlist` 개념이 없다.** 모든 테이블의 앵커는 `code`(6자리 종목코드)이며 FK로 감시목록에 묶이지 않는다. 대상이 "등록된 종목"이 아니라 "시총 하한을 넘는 전 종목"이기 때문이다.

```sql
-- ═══ L0: 유니버스 ═══
CREATE TABLE krx_universe (
  code TEXT PRIMARY KEY,                    -- '005930'
  symbol TEXT NOT NULL,                     -- '005930.KS' / '196170.KQ'
  name TEXT NOT NULL,
  board TEXT NOT NULL,                      -- 'KOSPI' | 'KOSDAQ'
  industry TEXT,                            -- KRX 업종명
  industry_code TEXT,                       -- 업종 코드 (제외 필터용)
  products TEXT,
  market_cap_krw BIGINT,
  corp_code TEXT,                           -- DART 고유번호 8자리 ★ 배치 수집 키
  listed_at DATE,                           -- 상장일 (히스토리 부족 판정)
  is_admin_issue BOOLEAN DEFAULT false,     -- 관리종목/투자주의환기
  is_spac BOOLEAN DEFAULT false,
  is_excluded BOOLEAN DEFAULT false,        -- G3 업종 제외 결과 (캐시)
  exclude_reason TEXT,
  sector_caveat BOOLEAN DEFAULT false,      -- 건설/조선/바이오 등 주의 업종
  refreshed_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON krx_universe (corp_code);
CREATE INDEX ON krx_universe (market_cap_krw DESC);

-- ═══ L2: 분기 재무 (핵심) ═══
CREATE TABLE quarterly_fundamentals (
  code TEXT NOT NULL,
  fiscal_year INT NOT NULL,
  fiscal_quarter INT NOT NULL,              -- 1~4 (회계분기)
  fs_div TEXT NOT NULL,                     -- 'CFS' | 'OFS'
  -- 손익
  revenue NUMERIC, gross_profit NUMERIC, op NUMERIC,
  np NUMERIC, np_ctrl NUMERIC, eps NUMERIC,
  -- 성장률 (부호 전환 시 NULL + status_label)
  revenue_yoy NUMERIC, revenue_qoq NUMERIC,
  op_yoy NUMERIC, op_qoq NUMERIC, np_yoy NUMERIC, eps_yoy NUMERIC,
  op_status_label TEXT,                     -- '흑전'|'적전'|'적자축소'|'적자확대'|NULL
  -- 마진
  opm NUMERIC, opm_yoy_delta NUMERIC, opm_qoq_delta NUMERIC,
  gpm NUMERIC, npm NUMERIC,
  -- TTM (계절성 제거용) ★ v2 신설
  ttm_revenue NUMERIC, ttm_op NUMERIC, ttm_opm NUMERIC, ttm_cfo NUMERIC,
  ttm_revenue_qoq NUMERIC, ttm_opm_delta NUMERIC,
  -- 2년 스택 (기저효과 방어) ★ v2 신설
  rev_2y_stack NUMERIC,
  -- 현금흐름·재무상태 (L2″ — 게이트 통과 종목만)
  cfo NUMERIC, capex NUMERIC, fcf NUMERIC,
  receivables NUMERIC, inventory NUMERIC,
  equity NUMERIC, assets NUMERIC, liabilities NUMERIC,
  shares_outstanding BIGINT, shares_yoy NUMERIC,   -- ★ v2 신설
  -- 메타
  source TEXT,                              -- 'dart_periodic'|'dart_provisional'
  is_estimate BOOLEAN DEFAULT false,
  restated BOOLEAN DEFAULT false,
  delta_from_preliminary JSONB,
  disclosed_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (code, fiscal_year, fiscal_quarter, fs_div)
);

-- ═══ L3: 컨센서스 사전 스냅샷 ═══
-- 발표 후에는 (E)가 실적치로 덮여 사라지므로 미리 저장해야 한다
CREATE TABLE consensus_snapshots (
  code TEXT NOT NULL,
  fiscal_year INT NOT NULL, fiscal_quarter INT NOT NULL,
  revenue_est NUMERIC, op_est NUMERIC, np_est NUMERIC, eps_est NUMERIC,
  n_estimates INT,                          -- < 2면 컨센서스로 인정하지 않음
  source TEXT,                              -- 'fnguide' | 'naver'
  snapshot_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (code, fiscal_year, fiscal_quarter, snapshot_at)
);

-- ═══ L1: 공시 이벤트 ═══
CREATE TABLE earnings_disclosures (
  rcept_no TEXT PRIMARY KEY,                -- DART 접수번호 (자연 멱등키)
  code TEXT NOT NULL, corp_code TEXT,
  report_nm TEXT,
  doc_type TEXT,                            -- 'provisional'|'periodic'|'pl_change'
  fiscal_year INT, fiscal_quarter INT,
  disclosed_at TIMESTAMPTZ,
  detected_at TIMESTAMPTZ DEFAULT now(),
  parse_status TEXT,                        -- 'ok'|'llm_fallback'|'failed'
  processed BOOLEAN DEFAULT false
);
CREATE INDEX ON earnings_disclosures (code, disclosed_at DESC);

-- ═══ L4: 시세 스냅샷 ═══
CREATE TABLE price_snapshots (
  code TEXT NOT NULL, snap_date DATE NOT NULL,
  close NUMERIC, chg_pct NUMERIC,
  high_52w NUMERIC, low_52w NUMERIC, pos_52w NUMERIC,
  ret_1m NUMERIC, ret_3m NUMERIC, ret_6m NUMERIC, ret_12m NUMERIC,
  rel_ret_3m NUMERIC,                       -- 소속 지수 대비 초과수익 ★ PRI P1
  market_cap_krw BIGINT, per NUMERIC, pbr NUMERIC, fwd_per NUMERIC,
  per_pctile_3y NUMERIC,                    -- 3년 PER 밴드 백분위 ★ PRI P3
  avg_value_20d NUMERIC,
  PRIMARY KEY (code, snap_date)
);

CREATE TABLE index_snapshots (               -- 상대수익률 계산용
  index_name TEXT NOT NULL,                  -- 'KOSPI' | 'KOSDAQ'
  snap_date DATE NOT NULL, close NUMERIC,
  PRIMARY KEY (index_name, snap_date)
);

-- ═══ L5: 스크리닝 결과 ═══
CREATE TABLE screen_results (
  code TEXT NOT NULL, fiscal_year INT NOT NULL, fiscal_quarter INT NOT NULL,
  -- 게이트
  gate_passed BOOLEAN, gate_detail JSONB,   -- {g0,g1,g2,g3 + 각 근거 수치}
  base_effect_warning BOOLEAN DEFAULT false,
  turnaround BOOLEAN DEFAULT false,
  -- 스코어 (raw = 정규화 전, 사후 가중치 재계산용으로 반드시 저장)
  raw_a1 NUMERIC, raw_a2 NUMERIC, raw_a3 NUMERIC, raw_a4 NUMERIC,
  raw_b1 NUMERIC, raw_b2 NUMERIC, raw_b3 NUMERIC, raw_b4 NUMERIC,
  raw_c1 NUMERIC, raw_c2 NUMERIC,
  raw_d1 NUMERIC, raw_d2 NUMERIC, raw_d3 NUMERIC, raw_d4 NUMERIC,
  score_a NUMERIC, score_b NUMERIC, score_c NUMERIC, score_d NUMERIC,
  score_flash NUMERIC,                      -- 잠정 시점 (A+B+C 정규화)
  score_final NUMERIC,                      -- 확정 후 (A+B+C+D 정규화)
  score_delta NUMERIC,                      -- final − flash
  has_consensus BOOLEAN,
  pctile_in_quarter NUMERIC,                -- 분기 내 백분위
  -- 주가반영도
  pri NUMERIC, pri_detail JSONB,
  -- 최종 분류
  grade TEXT,                               -- '★'|'○'|'△'|'·'|'✕'
  computed_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (code, fiscal_year, fiscal_quarter)
);
CREATE INDEX ON screen_results (fiscal_year DESC, fiscal_quarter DESC, score_flash DESC);

-- ═══ L6: LLM 분석 ═══
CREATE TABLE analyses (
  id BIGSERIAL PRIMARY KEY,
  code TEXT NOT NULL, fiscal_year INT, fiscal_quarter INT,
  model TEXT, cost_usd NUMERIC,
  payload JSONB,                            -- §7.2 스키마
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (code, fiscal_year, fiscal_quarter)
);

-- ═══ L7: 결과 추적 ★ v2 신설 — 이게 없으면 시스템을 검증할 수 없다 ═══
CREATE TABLE outcome_tracking (
  code TEXT NOT NULL, fiscal_year INT NOT NULL, fiscal_quarter INT NOT NULL,
  announce_date DATE,
  grade_at_announce TEXT, score_at_announce NUMERIC, pri_at_announce NUMERIC,
  ret_d1 NUMERIC, ret_d5 NUMERIC, ret_d20 NUMERIC, ret_d60 NUMERIC,
  excess_d1 NUMERIC, excess_d5 NUMERIC, excess_d20 NUMERIC, excess_d60 NUMERIC,
  updated_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (code, fiscal_year, fiscal_quarter)
);

-- ═══ 운영 ═══
CREATE TABLE notifications (
  id BIGSERIAL PRIMARY KEY,
  code TEXT, kind TEXT,                     -- 'flash'|'daily'|'budget'|'upgrade'
  fiscal_year INT, fiscal_quarter INT,
  sent_at TIMESTAMPTZ DEFAULT now(), payload JSONB,
  UNIQUE (code, fiscal_year, fiscal_quarter, kind)   -- ★ 중복 발송 차단
);

CREATE TABLE cost_log (
  id BIGSERIAL PRIMARY KEY, model TEXT,
  input_tokens INT, cache_write_tokens INT, cached_tokens INT, output_tokens INT,
  cost_usd NUMERIC,
  env TEXT DEFAULT 'prod',                  -- ★ 개발 실행이 운영 상한을 먹지 않도록
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ═══ RLS (HermesCall과 동일 원칙) ═══
-- 전 테이블 ENABLE, cost_log 제외 anon SELECT 정책. 쓰기는 service_role 서버사이드만.
```

**HermesCall의 미해결 과제 3개를 스키마에 미리 반영했다**
1. `notifications`의 `UNIQUE(code, fy, fq, kind)` — 재시도 중복 발송 차단
2. `cost_log.env` — 개발 실행이 운영 일일 상한을 잡아먹던 문제 (HermesCall CLAUDE.md에 "아직 미구현"으로 남아 있음)
3. `rcept_no` PK — NULL 섞인 복합 UNIQUE가 멱등성을 깨던 문제 회피

---

## 7. LLM 분석

### 7.1 입력

상한은 `LLM_INPUT_TOKEN_BUDGET` — 값은 §7.3 가드레일을 보라(여기에 숫자를 적지 마라 · T82).
아래 토막 수치는 **실측 근사치**이고, `analyze()`가 실제로 강제하는 것은 그 상수뿐이다.

> ⚠ 2026-08-23까지 이 제목은 "총 5,000토큰 이내"였는데 **아무 데서도 검사되지 않았고**
> 실제 입력은 발췌 없이도 10,300토큰이었다 — 문서와 현실이 2배 어긋난 채였다(T97).

```
[시스템 프롬프트 — cache_control: ephemeral] ~5,600토큰
  분석 프레임 · 출력 JSON 스키마 · 한국 시장 맥락 · 판단 기준
  ★ 종목마다 바뀌는 내용을 절대 넣지 말 것 (캐시가 통째로 깨진다)

[유저 메시지] ~4,000토큰
  0) 데이터 기준일  이 날짜 이후의 사건은 입력에 없다고 모델에게 명시 (T101)
  1) 기본정보    종목명·코드·업종·주요제품·시총·상장일
  2) 8분기 표    매출/YoY/QoQ · 영업이익/YoY · OPM/YoY%p · EPS · TTM 매출·OPM · FCF
  3) 판정 결과   게이트 통과 여부 + A/B/C/D 축별 점수와 근거 수치
                 + base_effect_warning + sector_caveat
  4) 컨센서스    매출/영업이익/EPS 추정치와 서프라이즈 % (없으면 "커버리지 없음" 명시)
  5) 주가        현재가·52주 위치·3/6/12M 수익률·지수 대비 초과수익·PER·PBR·PRI 분해
                 + **분기말 종가 추이**(등락률을 우리가 계산해 준다 — 모델에게
                 산수를 시키면 틀린 값이 본문에 인용된다 · T101)
  6) 공시 발췌   매출·수주 / 원재료·설비 / 주요제품 / 주요계약·연구개발 4개 절
                 길이 상한은 §7.3 가드레일을 보라 (여기에 숫자를 적지 마라 — T82)
                 맨 앞에 [출처: YYYY년 N분기 정기보고서] 라벨을 붙인다 (T99)
 6-1) 최근 공시  공시명 + 접수일 (발췌가 '내용'이면 이건 '무엇이 언제 나왔는가'다).
                 트리거의 expected_date를 잡는 기준이 된다 (T101)
  7) 업종 비교   동일 KRX 업종 상위 5개사 매출YoY·OPM·PER·스코어
```

> **공시 원문 전체를 넣지 마라.** 숫자는 이미 우리가 정확히 갖고 있다. LLM에게 숫자를 다시 읽히면 비용과 오류가 함께 늘어난다. LLM의 역할은 **"이 숫자 패턴이 무엇을 의미하고, 다음 1~4개 분기에 무엇이 숫자로 확인되어야 하는가"**다.

### 7.2 출력 스키마 (tool-forced JSON)

```jsonc
{
  "one_line_thesis": "왜 지금 이 종목을 봐야 하는지 한 문장",
  "why_now": "2~3문장",
  "growth_engine": {
    "drivers": ["가격 인상"|"물량 증가"|"신규 고객"|"신제품"|"지역 확장"|"CAPA 확대"],
    "structural_or_temporary": "structural" | "temporary",
    "evidence": "실적으로 확인되고 있는 근거 (숫자 포함)"
  },
  "acceleration_quality": {
    "is_genuine": true,
    "base_effect_assessment": "전년동기 기저가 정상인지에 대한 판단",
    "sustainability_quarters": 3          // 가속이 이어질 것으로 보는 분기 수
  },
  "triggers": {
    "within_3m": [{"event": "...", "verifiable_metric": "...", "expected_date": "2026-11"}],
    "within_6m": [ ... ]
  },
  "price_position": {
    "verdict": "매력적" | "적정" | "부담" | "과열",
    "reason": "...",
    "priced_in": ["이미 반영된 것 2개"],
    "not_priced_in": ["아직 반영 안 된 것 2개"]
  },
  "scenarios": {
    "bull": {"probability": 0.25, "condition": "...", "implication": "..."},
    "base": {"probability": 0.55, "condition": "...", "implication": "..."},
    "bear": {"probability": 0.20, "condition": "...", "implication": "..."}
  },
  "risks": [
    {"risk": "...", "likelihood": "높음|중간|낮음", "impact": "큼|중간|작음", "watch_metric": "..."}
  ],
  "next_data_to_watch": ["다음 분기에 반드시 확인할 지표 3개"],
  "how_i_could_be_wrong": "이 판단이 틀릴 수 있는 이유"
}
```

> 사용자의 15단 분석 프레임 중 **정량 부분(분기 실적·경쟁사 비교·밸류에이션)은 DB에서 이미 계산되어 대시보드에 그대로 표시**되고, LLM은 정성 해석(투자 아이디어·트리거·주가 위치·시나리오·리스크)만 담당한다. 비용과 신뢰도를 동시에 잡는 방법이다.

### 7.3 가드레일

```
MONTHLY_COST_CEILING_USD = 27     # 2026-08-26 개정 (24 → 27 · 발송등급 88종목 완주)
DAILY_ANALYSIS_LIMIT     = 120    # 2026-08-26 개정 (80 → 120 · 88종목 당일 완주)
max_tokens               = 16384  # 2026-08-24 개정 (12288 → 16384 · 출력 중앙 4,989)
EXCERPT_BUDGET_CHARS = 2400       # 수집기 예산
EXCERPT_MAX_CHARS = 2600          # 2026-08-24 개정 (2000 → 2600 · T100)
LLM_INPUT_TOKEN_BUDGET = 16000    # 2026-08-24 개정 (14000 → 16000 · 실측 최대 13,768)
```

**2026-08-24 개정 근거 (실측)** — 수집기 2,400자 / 분석기 2,000자로 **두 값이 어긋나
있어** 저장된 발췌 453건 중 **428건(94%)이 평균 432자씩 버려지고 있었다.** 잘려나간
것은 언제나 마지막 절 `주요계약 및 연구개발활동` — 수주계약·국책과제가 적힌,
발췌를 도입한 이유 그 자체인 절이다. 두 값을 `constants.py` 한 곳에서 유도하고
`tests/test_excerpt_budget.py`가 `분석기 상한 > 수집기 예산` 부등식을 지킨다.

**2026-08-17 개정 근거 (실측)** — 세 값을 함께 고쳤다. `src/config/constants.py`가
유일한 출처이고 `tests/test_cost_guard.py`가 이 문서와 대조한다.

- **실링 8 → 12**: 분석 범위를 게이트 통과 **전부**(238종목)로 넓혔다(A′+B).
  실측 단가 캐시히트 $0.0315 · 미스 $0.0363 → 분기 $7.51.
  실링 $8이면 94%로 빠듯해 텔레그램 재질의가 겹치면 월중에 막힌다. $12면 63%다.
  ※ 전체 1,112종목은 $35(292%)이고 탈락 782종목 해석의 효용이 낮아 **보류**했다.
- **일 상한 20 → 80**: 20이면 배치가 며칠로 쪼개져 **매일 첫 건이 캐시 미스**가 된다.
  실제 병목은 시간이다 — 호출당 36~56초라 `--max-seconds`가 먼저 걸린다(T73).
- **max_tokens 8192 → 12288**: 실측 78건 중 **2건(3%)이 상한에 닿아 잘렸다**.
  잘린 건은 저장하지 않지만 **비용은 발생한다**($0.0857씩 · 전체의 6% 낭비).
  출력 중앙값이 2,928토큰(상한의 36%)이라 상한을 올려도 평균 비용은 거의 안 오른다 —
  모델은 필요한 만큼만 쓴다.

- `stop_reason == "max_tokens"`면 **명시적으로 실패 처리**한다. 잘린 JSON을 저장하면 대시보드가 나중에 500을 낸다.
- 월 실링 도달 시 큐로 이월하고 텔레그램으로 통지한다.
- `check_budget()`은 `cost_log where env='prod'`만 집계한다.
- **가격 상수**: Sonnet 5 입력 $2 / 출력 $10 / 캐시읽기 $0.20 per MTok (2026-08-13 확인). **날짜 기준 가격 전환 로직을 넣지 마라** — HermesCall이 2026-09-01 $3/$15 전환을 넣어 두었으나 Anthropic 공식 확인 결과 인상은 시행되지 않았다.

---

## 8. 텔레그램 (@Invest_EarningCallBot — HermesCall과 공유)

### 8.1 절대 규칙

**`setWebhook`을 호출하지 마라.** 텔레그램은 봇당 웹훅 1개만 허용하고, 새로 등록하면 이전 것이 **에러 없이 덮어써진다.** HermesCall 대시보드가 웹훅을 점유 중이므로 등록 시 HermesCall의 `/add /remove /list /cost /status /analyze`가 조용히 죽는다.

**Heimdallr는 `sendMessage` 발송 전용이다.** 발송에는 제약이 없다.

단, `/api/telegram/lookup` 엔드포인트는 미리 만들어 둔다 — 나중에 HermesCall 웹훅에서 폴백 체이닝(watchlist에서 못 찾으면 Heimdallr로 넘김)을 붙일 때 HermesCall 쪽 5줄만 고치면 되고, 안 쓰더라도 대시보드 자체 검색에 재사용된다.

### 8.2 발송 rate limit (봇 토큰 공유)

같은 채팅방 기준 대략 초당 1건이 한도이며, 두 시스템이 이를 나눠 쓴다. 반드시 구현할 것:
- 연속 발송 사이 **1초 간격**
- 429 응답의 `retry_after`를 존중하는 백오프 (3회 재시도)
- 발송 실패해도 파이프라인은 계속 진행 (DB에 이미 저장되어 대시보드로 확인 가능)
- 메시지 4,096자 제한 — 초과 시 상위 N개로 자르고 "외 M종목" 표기

### 8.3 ⚡ 즉시 알림 (★ / ○ 만)

> 아래 수치는 **레이아웃 설명용 가상 예시**다.

```
🛡️★ 실적 가속 · 스코어 82 · 주가반영 31 (미반영)

📌 리노공업 (058470 · KOSDAQ)
   반도체 검사 소켓 · 시총 2.4조

📊 2026 2Q (잠정)
   매출     892억  YoY +34.2%  (전분기 +18.1% → 가속 ▲16.1%p)
   영업이익 341억  YoY +58.7%
   OPM      38.2%  YoY +5.9%p  · TTM OPM +2.4%p
   EPS      2,180원 YoY +61.3%

✅ 게이트 통과 · 기저효과 경고 없음 (TTM 매출 사상 최고)
🎯 A 가속 28/35 · B 수익성 27/32 · C 서프 12/15 · (D 확정치 대기)
   raw 67/82 → 정규화 82점
📈 컨센 대비  매출 +6.2% / 영업이익 +14.8% (추정기관 4)

📉 주가반영도 31/100
   3M 상대수익률 +2.1%p · 52주 위치 58% · PER 3년밴드 41%
   → 실적 가속 대비 주가가 아직 따라오지 않음

💡 HBM 테스트 소켓 물량이 본격 반영된 첫 분기.
   가동률 상승에 따른 영업레버리지가 OPM +5.9%p로 확인됨.
   가속 지속 전망: 3개 분기

🔔 3개월 내 트리거
   · 3Q 가이던스 (10월 말) — 매출 950억 상회 여부
   · 주요 고객사 HBM4 양산 일정 확정
⚠️ 리스크: 고객 집중도 (상위 2사 비중 추정 60%+) · 발생가능성 중간 / 영향 큼

🔗 https://heimdallr-call.vercel.app/stock/058470
```

### 8.4 📊 일일 요약 (17:30 KST)

```
🛡️📊 2026-08-13 발굴 요약

실적 공시 87건 · 게이트 통과 12 · ★2 ○3 △1

등급  종목            스코어  반영도  매출YoY   OPM YoY
 ★   리노공업          82     31    +34.2%   +5.9%p
 ★   에스티아이         78     28    +51.0%   +4.2%p
 ○   HPSP             74     44    +28.4%   +3.1%p  ⚠컨센없음
 △   ○○테크          80     72    +42.1%   +6.0%p  (선반영)

🔗 https://heimdallr-call.vercel.app
```

### 8.5 🔄 승격 알림 (주 1회, 월요일)

△(고스코어·고반영) 종목의 PRI가 하락해 ○/★로 승격되면 알린다. **조정 시 담을 종목**을 놓치지 않기 위한 장치다.

---

## 9. 대시보드 (Next.js 14 App Router + Supabase anon + Tailwind + Recharts)

| 경로 | 내용 | 우선순위 |
|---|---|---|
| `/stock/[code]` | **종목 상세 — 시스템의 핵심 화면** (§9.1) | 1 |
| `/` | 이번 시즌 발굴 목록. 등급·스코어·반영도 정렬 | 2 |
| `/matrix` | **2축 산점도** (X=스코어, Y=주가반영도). 사분면 색상 구분, 점 클릭 시 상세 | 3 |
| `/screener` | 전 종목 스크리너. 분기·업종·시총·등급·컨센서스 유무 필터 | 4 |
| `/season` | 시즌 진행률 + 발표 캘린더 + 미발표 종목 | 5 |
| `/outcome` | **결과 추적** — 등급별 D+20/D+60 초과수익 분포, 축별 IC | 6 |
| `/settings` | 임계값 · 비용 현황 | 7 |

### 9.1 `/stock/[code]` 구성

1. **헤더** — 종목명·코드·업종·시총 / 현재가·등락 / 52주 위치 게이지 / 3·6·12M 수익률 (지수 대비 병기)
2. **판정 카드** — 등급(★○△·) / 스코어 A·B·C·D 스택 바 / **PRI 분해 바** / 분기 내 백분위 / 경고 배지(기저효과·업종주의·컨센없음)
3. **분기 실적 추이 (8분기)** — 이중축 차트
   - 막대: 매출·영업이익 / **선: 매출 YoY 성장률 (이 화면의 주인공 — 가속이 눈으로 보여야 한다)** / 점선: TTM 매출
4. **분기 히스토리 표** — 매출/YoY/QoQ · 영업이익/YoY · OPM/YoY%p · EPS/YoY · FCF · TTM · 잠정/확정 표시 · `score_delta`
5. **컨센서스 대비** — 서프라이즈 % + 추정기관 수 (없으면 "커버리지 없음" 명시)
6. **밸류에이션** — PER·PBR·Fwd PER·PEG / 3년 밴드 내 위치 / 동일 업종 대비 / 주가 위치 판정
7. **LLM 분석** — 한 줄 아이디어 / 왜 지금인가 / 성장 엔진(구조적·일시적) / 가속 지속 전망 / 3·6개월 트리거 / Bull·Base·Bear 확률 / 리스크 표 / 다음에 확인할 데이터 / 내가 틀릴 수 있는 이유
8. **업종 비교 표** — 상위 5개사 매출YoY·OPM·PER·스코어
9. **결과 추적** — 발표 후 D+1/5/20/60 수익률 (지수 대비)
10. **원문 토글** — DART 링크 + 발췌

### 9.2 방어 코드 (HermesCall에서 실제로 터진 것)

1. **`analyses.payload`는 부분적으로만 채워질 수 있다.** `payload && payload.scenarios.bull`처럼 상위 객체만 확인하고 하위 필드를 읽으면 페이지 전체가 500이 난다. **필드 단위로 확인할 것.**
2. **새 컬럼 미적용 기간을 견딜 것.** DDL은 REST로 실행 불가라 SQL Editor 적용 전까지 공백이 생기는데, 그 사이 쓰기는 PGRST204, 조회는 42703으로 **각각 파이프라인과 페이지를 죽인다.** 누락 컬럼을 감지해 제외하고 재조회하는 루프 패턴을 쓸 것(PostgREST는 누락 컬럼을 한 번에 하나씩만 알려주므로 루프가 필요하다).
3. **PostgREST max-rows 1,000.** 1,300종목 조회는 반드시 `range()` 페이징. `.limit(5000)`을 줘도 1,000행만 온다.
4. **Vercel Deployment Protection**이 기본 켜져 있으면 외부 접근이 401로 막힌다.

---

## 10. 자동화 · 운영

| 워크플로우 | 스케줄 (UTC) | 내용 |
|---|---|---|
| `universe_daily.yml` | `0 21 * * *` (06:00 KST) | KIND+네이버+corpCode 갱신, 시세·지수 스냅샷, PRI 재계산 |
| `disclosure_poll.yml` | 시즌 `*/15 0-10 * * 1-5` / 비시즌 `0 1,4,7,10 * * 1-5` | DART 폴링 → 파싱 → 스크리닝 → ⚡알림 |
| `daily_digest.yml` | `30 8 * * 1-5` (17:30 KST) | 일일 요약 발송 |
| `quarterly_backfill.yml` | `0 20 1,15 * *` + 수동 | 확정 재무 배치 + 정밀 재무(게이트 통과분) + `score_final` 재계산 |
| `outcome_update.yml` | `0 22 * * 1-5` (07:00 KST) | D+1/5/20/60 수익률 갱신 |
| `promotion_check.yml` | `0 22 * * 1` (월요일) | △→○/★ 승격 확인 및 알림 |

### 10.1 비용 — repo를 public으로 둘 것
- Private repo는 GitHub Actions 무료 **2,000분/월**인데, 시즌 폴링만으로 38회/일 × 2분 × 20영업일 = **1,520분/월**이라 위험하게 근접한다.
- **Public repo는 Actions 무제한 무료.** 시크릿은 GitHub Secrets에 있고 Supabase anon key는 원래 공개 전제 + RLS로 방어되므로 코드 공개가 문제되지 않는다.
- `SEASON_MODE` 리포지토리 변수로 폴링 빈도를 전환한다.
- **잡 안에서 `sleep` 루프를 쓰지 마라.** sleep도 과금된다. 짧은 잡을 여러 번 띄우는 편이 싸다. 잡당 timeout 15분.

### 10.2 시즌 정의

| 분기 | 잠정실적 집중 | 정기보고서 마감 |
|---|---|---|
| 1Q | 4월 중순 ~ 5월 중순 | 5월 15일 |
| 2Q | 7월 중순 ~ 8월 중순 | 8월 14일 |
| 3Q | 10월 중순 ~ 11월 중순 | 11월 14일 |
| 4Q/연간 | 1월 말 ~ 2월 말 | 3월 31일 (사업보고서) |

실제 고부하는 연 4회 × 5주 ≈ **20주**. 나머지 32주는 저빈도.

---

## 11. 비용 설계

| 항목 | 단가 | 수량 | 분기 비용 |
|---|---|---|---|
| LLM 분석 (Sonnet 5) | $0.042/종목 | 40종목 | $1.68 |
| 잠정실적 Haiku 폴백 | $0.012/건 | 60건 | $0.72 |
| 일일 요약 생성 | $0.01/일 | 30일 | $0.30 |
| **분기 합계** | | | **$2.70** |
| **연간** | | | **$10.8 (월 평균 $0.90)** |

| 인프라 | 비용 |
|---|---|
| Supabase Free (조직당 활성 프로젝트 2개 — HermesCall이 1개 사용 중) | $0 |
| Vercel Hobby | $0 |
| GitHub Actions (public repo) | $0 |
| DART OpenAPI · KIND · 네이버 | $0 |

**가드레일**: 월 하드실링 **$8** / 일일 분석 상한 **20건**. HermesCall($15 실링, 실사용 $2.37/월)보다 낮게 잡아도 여유가 충분하다.

**LLM 단가 검산 (Sonnet 5, 2026-08-13 확인 단가)**
```
입력   4,500 tok × $2 /1M = $0.0090
캐시   2,500 tok × $0.2/1M = $0.0005
출력   3,200 tok × $10/1M = $0.0320
                    합계   = $0.0415 ≈ $0.042
```

---

## 12. 함정 목록 — 조용히 틀리는 것들 (`docs/traps.md`로 분리)

> 아래는 전부 **에러 없이 품질만 나빠지는** 종류다. 테스트 통과는 증거가 아니다.

### T1. DART 정기보고서 누적치 — **이 프로젝트의 급소**
- 1분기보고서(11013): `thstrm_amount` = **3개월 단독**
- **반기보고서(11012): 6개월 누적** → `Q2 = 반기 − Q1`
- 3분기보고서(11014): 3개월 단독 + 9개월 누적 둘 다 제공
- **사업보고서(11011): 12개월 누적** → `Q4 = 연간 − 3Q누적`
- `thstrm_amount`(당기)와 `thstrm_add_amount`(당기누적)를 **반드시 구분**하라.
- → `src/finance/quarterize.py`로 분리하고 **테스트를 먼저 쓸 것.**

### T2. 연결(CFS)/별도(OFS) 혼용
종목별로 하나를 고정하고 `fs_div`에 기록. 분기마다 기준이 바뀌면 성장률이 조작된 것처럼 보인다.

### T3. 재작성(restated) 전년동기
분할·합병·중단영업·회계기준 변경 시 전년동기가 재작성된다. **공시에 실린 전년동기 값을 우선**하고, DB 저장값과 다르면 `restated=true`로 화면에 밝힌다.

### T4. 잠정 ≠ 확정
잠정실적 공정공시 수치와 45일 뒤 확정치가 다를 수 있다. `is_estimate` 필수, `delta_from_preliminary`에 변동 기록. **차이 자체가 유용한 신호다.**

### T5. KIND 상장법인목록은 `html.parser`로 파싱
`lxml`은 코스닥 1,839행 중 **1,282행에서 예외도 경고도 없이 잘라낸다**(HermesCall 2026-08-09 실측 — 코스닥 557곳 30%가 사라짐). 원문 `<tr>` 개수와 대조해 유실을 감지하고 즉시 실패시킬 것. 다른 collector는 lxml이 정상이니 **이 소스만 예외다.**

### T6. KIND 응답의 종목코드 중복
같은 코드가 두 번 실려 오는 행이 있다(실측 36건). code 기준 중복 제거하지 않으면 PK 제약(23505)에 걸려 **캐시 저장이 통째로 실패**하고 매번 라이브 수집으로 되돌아간다(경고만 찍히고 분석은 계속돼 눈에 잘 안 띈다).

### T7. PostgREST max-rows 1,000
`.limit(5000)`을 줘도 1,000행만 온다. 시총 내림차순으로 읽으면 **잘려나가는 건 하위 소형주** — 이 시스템이 발굴하려는 바로 그 구간이다. 반드시 `range()` 페이징.

### T8. 네이버 시총 페이징은 엄격한 내림차순이 아니다
실측으로 순서가 흔들리는 지점이 3곳 발견됐다. "하한 미만을 처음 본 순간"이 아니라 **그 페이지의 마지막 항목까지 하한 미만일 때**만 멈춘다.

### T9. 시크릿에 개행이 섞인다
`os.environ`을 직접 읽지 말고 반드시 `src/utils/env.py`의 `require_env`/`optional_env`(내부에서 `.strip()`). HermesCall에서 값에 개행이 섞여 `httpcore.LocalProtocolError`가 나고 anthropic SDK가 이를 `APIConnectionError`로 감싸 **모든 LLM 호출이 6일간 조용히 실패**한 사고가 있었다.

### T10. 미선언 의존성
새 서드파티 임포트는 반드시 `pyproject.toml`에 선언. 로컬 venv에 수동 설치돼 있으면 로컬 테스트는 전부 통과하고 **GitHub Actions의 깨끗한 `pip install -e .` 환경에서만** 죽는다(HermesCall에서 3회 재발). `lxml`은 임포트가 아니라 **실제 파싱 순간**에만 죽어서 더 악질이었다.
검증: `python -m venv /tmp/x && /tmp/x/bin/pip install -e .` 후 실제 경로 1회 실행.

### T11. 단위를 못 읽으면 추측해서 곱하지 말 것
잠정실적 공시 원문 표는 원/백만원/억원이 섞인다. 단위 파싱 실패 시 **그 항목만 건너뛰고** 그 사실을 화면에 밝힌다. (DART API는 원 단위 정수라 이 문제가 없다 — L2' 파서에만 해당)

### T12. 부호가 바뀌는 구간의 성장률
적자→흑자, 흑자→적자에서 % 계산은 무의미하다. 분모가 0 또는 음수면 `None`을 반환하고 `status_label`을 쓴다.

### T13. 텔레그램 웹훅
`setWebhook` 호출 금지(§8.1). 봇당 1개만 허용되고 덮어쓰기가 조용하다.

### T14. 4Q의 특수성
한국 기업 4Q는 일회성 비용(재고평가손·성과급·손상차손)이 집중되어 OPM이 구조적으로 낮고, 사업보고서 차감으로 산출되므로 **잔차에 모든 회계 조정이 몰린다.** 4Q 스코어에는 신뢰도 플래그를 붙이고, 4Q QoQ 관련 판정은 하지 않는다.

### T15. KIS API — 토큰 재발급 제한과 초당 유량
접근토큰을 매 실행마다 새로 받으면 **발급 자체가 막힌다.** 파일/DB에 캐시하고 만료 전까지 재사용할 것. 유량은 실전계좌 초당 20건이라 1,300종목 순회 시 **토큰버킷 스로틀러가 없으면 중간에 `EGW00201`로 죽는다.** 그리고 **응답 필드명을 추정으로 박지 말 것** — 실제 호출 1회로 확정한 뒤 코드에 넣는다.

### T16. `.env`의 SUPABASE_URL/KEY는 HermesCall 것일 수 있다
프로젝트 폴더의 `.env.txt`에 이미 Supabase 값이 들어 있으나, **Heimdallr는 신규 Supabase 프로젝트를 쓴다**(설계 결정). 값을 그대로 쓰면 HermesCall DB에 Heimdallr 테이블이 생성되어 §2에서 분리하기로 한 이유가 통째로 무너진다. **P0에서 신규 프로젝트 값으로 교체했는지 반드시 확인할 것** — `SUPABASE_URL`의 프로젝트 ref가 HermesCall과 다른지 눈으로 대조한다.

---

## 13. Phase 계획 · 검증 게이트

> **한 세션 = 한 Phase.** 넘길 때마다 `/clear`. 컨텍스트가 커지면 앞에서 정한 규칙(예: "html.parser를 쓸 것")이 뒤에서 조용히 무시된다.

| Phase | 산출물 | 검증 게이트 — 통과 못 하면 다음 Phase 금지 |
|---|---|---|
| **P0** 스캐폴딩 | repo, pyproject, env.py, schema.sql, CLAUDE.md, docs/ | Supabase SQL Editor 적용 후 `python -m src.db.init` 성공 |
| **P1** 유니버스 | `src/universe/` | 시총 1,000억↑ 종목 수가 KIND 원문 `<tr>` 대조와 일치, corp_code 매칭률 ≥ 98%, 업종 제외 리스트 적용 결과 출력 |
| **P2** 분기 재무 ★ | `src/collectors/dart_financials.py`, `src/finance/quarterize.py` | **삼성전자(005930)·리노공업(058470)·에스티아이(039440) × 8분기 매출·영업이익이 DART 원문과 100% 일치.** 특히 **2Q·4Q 집중 확인** |
| **P2.5** 파생지표 | TTM · 2년 스택 · 성장률 · 상태라벨 | 손계산 3건 대조. 부호 전환 케이스 포함 |
| **P3** 스크리너 | `src/screener/gate.py`, `score.py`, `pri.py`, `matrix.py` | 순수 함수 단위 테스트 전부 통과 + 손계산 3건 + **정규화 규칙 검증(컨센 유/무 동일 종목 비교)** |
| **P4** 공시 감지 | `src/collectors/dart_disclosure.py`, `provisional_parser.py` | 과거 30일 replay — 검출률·파서 성공률·**오탐 < 5%** |
| **P5** 컨센서스 | `src/collectors/consensus.py` | 시총 구간별 샘플 50종목 파싱률 + `n_estimates` 분포 보고 |
| **P6** 시세·PRI | `src/collectors/kis_prices.py`, `src/screener/pri.py` | KIS 토큰 캐시 동작 + 초당 20건 스로틀 확인, **응답 필드명 실측 확정**, 지수 대비 상대수익률 3종목 수동 검산 |
| **P7** LLM | `src/analysis/`, `src/utils/cost_guard.py` | 실호출 1회 — 비용 $0.05 이하, JSON 전 필드 채움, 확률 합 ≈1.0, `env='prod'` 기록 |
| **P8** 텔레그램 | `src/notify/telegram.py` | 실발송 1건 + 동일 payload 재호출 시 차단 확인 |
| **P9** 대시보드 | `dashboard/` | 브라우저에서 `/stock/[code]` 렌더 + 8분기 차트 + 2축 산점도 확인 |
| **P10** 자동화 | `.github/workflows/` | 6개 워크플로우 수동 dispatch 각 1회 성공 |
| **P11** 결과추적 | `outcome_tracking` 배선 | 과거 분기 1개로 backfill 후 등급별 초과수익 분포 출력 |

### 13.1 지금 시점의 현실적 일정

오늘이 2026-08-13이므로 **2Q 잠정실적 시즌(7월 중순~8월 중순)이 마무리 중**이다.
- **8월 말까지 P0~P4** → 방금 지나간 2Q 데이터로 **실전 replay 검증** 가능
- **9월 P5~P9** → 대시보드까지
- **10월 초 P10~P11** → 3Q 시즌(10월 중순~11월 중순)을 **첫 실전 무대**로

### 13.2 세션 운영 규칙

**CLAUDE.md는 200줄 이내로 유지한다.** HermesCall의 CLAUDE.md는 1,440줄/138KB(한글 기준 약 5~7만 토큰)까지 비대해져 세션마다 그만큼을 소모한다. 내용 자체는 값지지만 파일 하나에 다 넣은 구조가 문제다.

```
CLAUDE.md                     ← 200줄 이내. 영구 규칙 + 최근 3세션 요약
docs/PRD.md                   ← 이 문서
docs/traps.md                 ← §12 함정 목록 (새 모듈 만들기 전 필독)
docs/decisions/NNN-*.md       ← 되돌리면 안 되는 설계 결정
docs/sessions/YYYY-MM-DD.md   ← 세션별 상세 기록
```

**세션 종료 프로토콜**
1. `docs/sessions/`에 상세 기록 (한 일 / 실측 수치 / 막힌 것 / 다음 세션이 알아야 할 것)
2. 새로 발견한 함정은 `docs/traps.md`에 추가 — **"무엇이 어떻게 조용히 틀리는가"를 반드시 포함**
3. `CLAUDE.md`에는 3줄 이내 요약만. 250줄 초과 시 가장 오래된 항목 삭제
4. 되돌리면 안 되는 결정은 `docs/decisions/`에 ADR로

**"완료" 선언 시 반드시 되물을 것**
> "실제로 돌려서 확인한 수치를 보여줘. 테스트가 통과했다는 말 말고, 실제 데이터로 뭐가 나왔는지."

HermesCall에서 가장 값비쌌던 실수들(lxml 30% 유실, 단위 혼용, PostgREST 1,000행 절단)은 **전부 에러 없이 조용히 품질만 나빠지는 종류**였다.

---

## 14. 리스크

| 리스크 | 가능성 | 영향 | 대응 |
|---|---|---|---|
| 누적치 분해 오류로 Q2/Q4 전면 왜곡 | 높음 | **매우 큼** | P2 검증 게이트. 3사 × 8분기 수동 대조 전에는 다음 Phase 금지 |
| 기저효과를 가속으로 오인 | 높음 | 큼 | 2년 스택 + TTM 최고 + 분기 최고 3중 확인, `base_effect_warning` |
| FnGuide/네이버 구조 변경 → 컨센서스 소실 | 높음 | 중간 | C축은 "없으면 정규화" 설계라 **시스템이 죽지 않는다.** 실패는 정상 케이스 |
| 텔레그램 웹훅 충돌로 HermesCall 봇 사망 | 중간 | 큼 | 발송 전용. `setWebhook` 금지를 CLAUDE.md에 명시 |
| 잠정실적 양식 다양성 → 파서 실패 | 중간 | 작음 | Haiku 폴백 → 45일 뒤 확정치로 자동 보정 |
| 게이트 통과 종목 과다(피크일 30+) | 중간 | 중간 | ★○만 알림, 상위 15 컷, 나머지는 대시보드 |
| **실적 가속이 이미 주가에 반영됨** | **높음** | **큼** | **PRI 별도 축 + 2축 매트릭스 + △등급 분리** ← v2 핵심 대응 |
| 스코어 가중치가 자의적 | 확실 | 중간 | `raw_*` 전량 저장 + `outcome_tracking` → 시즌 2회 후 IC 기반 조정 |
| Supabase 500MB 초과 | 낮음 | 중간 | 1,300종목 × 12분기 ≈ 15MB. 공시 원문은 **저장하지 않고 DART 링크만** |
| Supabase 1주 무활동 pause | 낮음 | 중간 | 매일 크론이 돌아 해당 없음 |

---

## 부록 A. 상수 테이블

> **전부 한 파일(`src/config/constants.py`)에 모은다.** HermesCall은 딥분석 문턱이 3곳(triage.py · workflow yml · costActions.ts)에 흩어져 있어 조용히 어긋난 적이 있다.

```python
# 유니버스
MARKET_CAP_FLOOR_KRW      = 100_000_000_000   # 1,000억원
MIN_QUARTERS_HISTORY      = 5                 # 신규 상장 판정

# 게이트
G4_OPM_DELTA_MIN_PP       = 0.0    # OPM YoY 상승 — 크기가 아니라 방향만 본다

# 스코어 배점
SCORE_WEIGHTS = {"A": 35, "B": 32, "C": 15, "D": 18}
A_WEIGHTS = {"a1": 10, "a2": 15, "a3": 4, "a4": 6}
B_WEIGHTS = {"b1": 14, "b2": 7,  "b3": 6, "b4": 5}
C_WEIGHTS = {"c1": 9,  "c2": 6}
D_WEIGHTS = {"d1": 6,  "d2": 4,  "d3": 4, "d4": 4}

# 스코어 구간 경계
A1_DELTA_MAX_PP           = 20.0    # 매출 YoY 델타 만점 기준
A2_DELTA_MAX_PP           = 40.0    # 영업이익 YoY 델타 만점 기준
B1_OPM_TIERS_PP           = (1.0, 3.0, 5.0)
B2_TTM_OPM_TIERS_PP       = (0.5, 2.0)
C1_SURPRISE_TIERS_PCT     = (3.0, 10.0, 20.0)
C2_SURPRISE_TIERS_PCT     = (2.0, 5.0, 10.0)
D2_DILUTION_TIERS_PCT     = (2.0, 5.0)
D4_LIQUIDITY_TIERS_KRW    = (500_000_000, 1_000_000_000)

# 컨센서스
MIN_ESTIMATES             = 2       # 추정기관 1개는 컨센서스가 아니다

# PRI
PRI_WEIGHTS = {"p1": 40, "p2": 25, "p3": 20, "p4": 15}

# 매트릭스 임계
SCORE_HIGH                = 75
SCORE_MID                 = 60
PRI_LOW                   = 40
PRI_HIGH                  = 65

# 알림
FLASH_DAILY_MAX           = 15
NOTIFY_GRADES             = ("★", "○")

# 비용
MONTHLY_COST_CEILING_USD  = 27
DAILY_ANALYSIS_LIMIT      = 120
EXCERPT_BUDGET_CHARS = 2400
EXCERPT_MAX_CHARS = 2600
LLM_INPUT_TOKEN_BUDGET = 16000
SONNET_INPUT_PER_MTOK     = 2.0     # 날짜 분기 로직 금지
SONNET_OUTPUT_PER_MTOK    = 10.0
SONNET_CACHE_READ_PER_MTOK = 0.20
HAIKU_INPUT_PER_MTOK      = 1.0
HAIKU_OUTPUT_PER_MTOK     = 5.0

# KIS Open API
KIS_BASE_URL              = "https://openapi.koreainvestment.com:9443"
KIS_RATE_LIMIT_PER_SEC    = 18      # 실전 20건, 안전 마진 2건
KIS_TOKEN_CACHE_PATH      = ".cache/kis_token.json"
KIS_TR_PRICE              = "FHKST01010100"
KIS_TR_DAILY_CHART        = "FHKST03010100"
KIS_ALLOWED_PATHS         = (       # 주문 API 호출 금지 — 화이트리스트
    "/oauth2/tokenP",
    "/uapi/domestic-stock/v1/quotations/inquire-price",
    "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
)
```

---

## 부록 B. 업종 예외 처리 (게이트 G3)

### B.1 제외 (분석 대상 아님)

| 구분 | 이유 |
|---|---|
| 은행 · 보험 · 증권 · 여신금융 · 저축은행 | 매출액 개념이 다르고 영업이익률이 무의미 |
| 지주회사 (순수지주) | 연결 매출이 자회사 합산이라 가속 판정 왜곡 |
| 부동산 임대·공급업 · 리츠 | 분기 실적 개념 부적합 |
| 스팩(SPAC) | 실적 없음 |

> KRX 업종 코드 기반으로 판정하되, 회사명에 "홀딩스"·"지주"가 포함되면서 매출총이익률이 비정상적으로 높은 경우를 지주회사 보조 판정으로 쓴다. **판정 결과를 `krx_universe.exclude_reason`에 기록해 나중에 검증 가능하게 할 것.**

### B.2 주의 표시 (제외하지 않되 `sector_caveat = true`)

| 구분 | 주의 사항 |
|---|---|
| 건설 · 조선 · 플랜트 | 진행기준 매출이라 분기 변동이 크다. 수주잔고 병행 필요(v1 범위 밖 — 경고만) |
| 바이오 · 제약(신약개발) | 매출이 미미하거나 마일스톤 일시 인식이라 가속 판정이 왜곡 |
| 게임 | 신작 출시 분기에만 급증하는 단발 패턴 |
| 조선기자재 · 방산 | 수주 인식 시점 편중 |

`sector_caveat`가 붙으면 등급은 유지하되 알림 본문과 대시보드에 주의 문구를 표시한다.

---

## 출처

- [코스닥 10곳 중 6곳은 증권사 리포트 '0건' — 헤럴드경제 (2026-06, 에프앤가이드 집계)](https://biz.heraldcorp.com/article/10770445)
- [OPEN DART 공시검색 API 개발가이드](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001)
- [OPEN DART 다중회사 주요계정 API 개발가이드](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019017)
- [OPEN DART 주식의 총수 현황 API 개발가이드](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS002&apiId=2020002)
- [Anthropic 모델 가격표](https://platform.claude.com/docs/en/about-claude/pricing)
- [Supabase Pricing (Free: 활성 프로젝트 2개, 1주 무활동 pause)](https://supabase.com/pricing)
- [The Market Sentiment Trend, Investor Inertia, and Post-Earnings Announcement Drift: Evidence from Korea's Stock Market, *Sustainability* 11(18):5137 (2019)](https://doi.org/10.3390/su11185137)
- [Investor Attention from Internet Search Volume and Underreaction to Earnings Announcements in Korea, *Sustainability* 12(22):9358 (2020)](https://www.mdpi.com/2071-1050/12/22/9358)
- [FnGuide 컨센서스 페이지](https://comp.fnguide.com/SVO2/asp/SVD_Consensus.asp?gicode=A005930)
- 참고 코드: `C:\Claude\dev\HermesCall` — CLAUDE.md, src/screener/quant_filters.py, src/orchestrator/pipeline.py, src/universe/krx_listing.py, src/utils/cost_guard.py, src/db/schema.sql, dashboard/lib/
