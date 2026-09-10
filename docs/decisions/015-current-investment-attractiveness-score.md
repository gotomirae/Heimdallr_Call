# ADR 15: 기업 투자 매력도 스코어를 확장하고 가격은 PRI로 분리

## 상태

채택 — 2026-09-10

## 문맥

실적 가속 원점수만으로는 산업 성장, 산업 내 위치, 밸류에이션, 자본효율, 현금창출력을 함께
판단할 수 없다. 그러나 현재 주가를 같은 숫자에 합치면 기업의 질과 가격을 분리해 읽을 수 없고
ADR 5가 무너진다. 기존 A~D 점수는 감사 가능한 실적 근거로 남기면서 대표 기업 점수를 확장한다.

## 결정

대표 기업 스코어 `investment_v1`은 다음 7축의 가중 평균으로 계산한다.

| 축 | 배점 |
|---|---:|
| 산업 성장 | 10 |
| 산업 내 위치 | 10 |
| 실적 원점수 | 25 |
| 성장 스토리의 수치 근거 | 20 |
| 밸류에이션(PER·F.PER) | 20 |
| ROE | 8 |
| 최근 분기 FCF | 7 |

측정 불가능한 축은 분모에서 제외하며 측정 배점 합계 60점 미만이면 판정하지 않는다.
성장 스토리는 LLM 해석이 아니라 전망 성장률, TTM 이익 변화, 연속 가속 등 구조화 숫자로 만든다.
FCF는 정밀 데이터가 있는 **최근 분기** 값만 사용하고 TTM으로 이름을 바꾸거나 추정하지 않는다.
현재 주가는 PRI로만 측정하며 기업 스코어에 넣지 않는다. 최종 등급은 기존 2축 매트릭스의
기업 점수 75/60, PRI 40/65 경계를 사용한다.

## 결과

- 발굴 목록의 `score_norm`은 기업 투자 매력도, `grade`는 현재 가격까지 반영한 최종 판단을 뜻한다.
- `gate_detail`에 `score_mode`, 원점수, 7축 입력·결측·분모를 함께 저장해 재현성을 확보한다.
- A~D 원점수와 PRI 원점수는 하위 감사·설명 정보로 유지한다.
- 동종 산업 상대 순위는 산업별 표본이 작을 때 결측으로 처리하며 임의의 0점으로 불이익을 주지 않는다.
- PRI가 없는 종목은 기업 점수를 보여 줄 수 있지만 최종 등급은 판정하지 않는다.

## 근거

FCF는 기업의 현금창출과 가치평가에 직접 연결되는 독립 지표로 취급한다. 시장 배수는 동일한
성장·위험·자본효율 조건에서 비교해야 하므로 PER/F.PER와 ROE를 산업 내 상대 순위로 반영한다.
참고: [CFA Free Cash Flow Valuation](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/free-cash-flow-valuation),
[CFA Market-Based Valuation](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/market-based-valuation-price-enterprise-value-multiples),
[Damodaran 변수 자료](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/variable.htm),
[Damodaran 성장과 ROE](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/valquestions/growth.htm).
