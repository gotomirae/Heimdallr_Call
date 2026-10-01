# ADR 24 — JARVIS 국내 진입 필수 조건 M1·M2·M5를 `entry_checks`로 제공한다

- 상태: 채택
- 날짜: 2026-10-01
- 관련: PRD §8.8, JARVIS PRD §7.3·§7.4·D13, JARVIS `docs/INTEGRATION_TASKS.md` B, traps.md T215~T219

## 결정

1. 국내 종목의 M1(실적 지속·가속 + 주가 미반영)·M2(MACD 상향 교차 직전)·M5(수급 2일 연속)는
   Heimdallr가 매 거래일 계산해 `entry_checks(code, check_date)`에 **통과·탈락 모두** 저장한다.
   JARVIS는 anon SELECT로 읽기만 한다. 한국 기술적 판정은 이 테이블 한 곳으로 모은다.
2. 임계값은 `src/config/constants.py`의 `ENTRY_*`·`K1_*` 한 곳이며 JARVIS
   `rules.yaml > entry_core`·`breakout_watch.K1_kr`와 같은 값이다. 테스트가 같은 PC의
   JARVIS 저장소를 찾으면 두 값을 대조한다(없으면 skip — CI는 대조하지 않는다).
3. 계산 순서는 **DB만으로 M1 재무 + PRI<50 → 통과 종목만 KIS 수급 → 통과 종목만 확정 일봉**이다.
   작업서의 "M5 통과 종목만 일봉"과 달리 **1단계 통과 종목 전부**의 일봉을 본다 —
   JARVIS 🟡 관찰(M1∧M2 + M3·M4·M5 중 2개)은 M5 없이도 성립하므로, M5 탈락으로 M2를
   비우면 🟡가 구조적으로 사라진다. 1단계 통과는 수십 종목이라 전 종목 일봉 호출을 피한다는
   원래 목적은 그대로 지켜진다.
4. 가격 조건(M1 조정·횡보, M2, 무효화선)은 **네이버 확정 일봉**으로만 계산한다.
   `check_date`는 KOSPI 지수 확정 일봉의 마지막 날이고 16:00 KST 전 오늘 봉은 버린다.
   `price_snapshots.close`는 쓰지 않는다(T216).
5. 판정값은 True/False/None을 구분한다. 데이터가 없거나 일봉·수급 기준일이 `check_date`와
   다르면 None이다(False로 뭉개면 "탈락"과 "모름"이 섞인다).
6. M2의 EMA는 JARVIS `technicals.ts`와 같은 **첫 값 시드**를 쓴다. 기존 §8.6 알림의 SMA 시드와
   다르지만, 경계값에서 JARVIS 표시와 이 판정이 갈리지 않게 하는 쪽을 택했다.
7. 🔵 K1은 진입 신호가 아니다. `notifications.kind='earnings_breakout'`에 1회 기록하고
   `TECHNICAL_TELEGRAM_ENABLED`가 True일 때만 텔레그램으로도 보낸다.

## 이유

JARVIS PRD §7.1-4(D13)가 국내 M1·M2·M5 계산 위치를 Heimdallr로 정했다. 재무·PRI·기저효과
경고가 전부 이 DB에 있고, HermesCall과 Heimdallr가 같은 한국 종목을 서로 다른 규칙으로
하루 2건씩 알리던 중복을 한 곳으로 모은다. 탈락 사유까지 저장해야 JARVIS가 "왜 🟢가 아닌가"를
설명하고 임계값을 보정할 수 있다.

## 되돌리면 무엇이 무너지는가

- 임계값을 한쪽만 바꾸면 JARVIS 🟢와 이 테이블이 **에러 없이** 어긋난다(T215).
- 통과 행만 저장하면 탈락 사유 분석과 🟡 판정이 불가능해진다.
- `price_snapshots` 종가로 돌아가면 장중 수집분이 확정 종가처럼 쓰여 같은 날 실행마다 답이 바뀐다.
- None을 False로 바꾸면 커버리지 공백(데이터 없음)이 "조건 불충족"으로 둔갑한다.
