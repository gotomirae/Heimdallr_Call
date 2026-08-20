# 2026-08-20 — 전 구간 검증 · 섹터 오분류 수습 · HTTP 재시도

## 왜 이 세션을 했나

"배포와 검증까지 끝난 상태인가? 계획대로 정상작동 되는가?"
기록(CLAUDE.md)을 믿지 않고 **전부 다시 돌려서** 확인했다.

## 1. 검증 — 실측 수치

| 항목 | 실측 |
|---|---|
| 테스트 | 508 passed, 1 skipped (세션 종료 시 **525 passed, 1 skipped**) |
| git | `main...origin/main` 동기 · 워킹트리 클린 |
| 대시보드 6 라우트 | `/` `/matrix` `/outcome` `/season` `/settings` `/stock/[code]` 전부 200 |
| 화면 ↔ DB | 게이트 통과 **238** / 전체 **1,111** · ★27 ○41 △18 ·128 ✕24 · 발송대상 **68** — **완전 일치** |
| T59 캐시 | `X-Vercel-Cache: MISS` · `Age: 0` — 수정 유효 |
| `/api/cost` | `available:true` · **$8.497 / 실링 $12** · 247콜 |
| **T72 (발송↔분석 괴리)** | 발송대상 68 중 분석 없음 **0** · 게이트 통과 238 중 분석 없음 **0** — 해소 확인 |
| cron | telegram_listen · disclosure_poll · daily_digest · llm_batch · outcome_update · promotion_check 최근 전부 success |
| 비시즌 스킵 | 로그에 `비시즌이라 30분 폴링을 건너뛴다 (SEASON_MODE=off)` — 설계대로 |

DB 실측: krx_universe 1,340 · quarterly_fundamentals 10,092 · screen_results 1,595 ·
analyses 239 · outcome_tracking 481 · price_snapshots 4,478 · quarter_prices 3,069 · cost_log 247.

`screen_results`는 분기별로 흩어져 있고(2026.1Q 1,105 · 2026.2Q 482),
**종목별 최신 분기만 추리면** 1,111종목 · 통과 238 — 화면 숫자와 정확히 맞는다.

## 2. 찾아낸 것 — 네 가지

### ① 섹터 오분류 (고침 · T77)
화면에 그대로 노출되고 있었다. 정답지를 만들어 재 보니 **78종목 중 23개(29.5%)가 오분류**.
`기타` 비율(1.2%)만 재고 있었고 **틀리게 가린 비율은 아무도 재지 않았다.**
→ 70.5% → **97.4%**. 자세한 내용은 T77.

### ② HTTP 재시도 취약 (고침 · T78)
`universe_daily`가 2026-08-19에 실패해 있었다 — KIND HTTP 실패.
직접 호출해 보니 **지금은 정상**(2,650행, 파싱 유실 0) → 일시적 장애.
그런데 재시도가 **3회 · 총 4.5초**뿐이라 딸꾹질 한 번에 잡 전체가 죽는다.
→ 5회 · 지수 백오프+지터(약 25초) · 4xx 즉시 포기.

### ③ 결과 추적 표본 부족 (시간 문제 — 손댈 것 없음)
`outcome_tracking` 481행 중 D+1 481 · D+5 341 · **D+20 6 · D+60 0**.
ADR 1(실적 가속이 유효한가)의 검증은 여전히 불가능하다.

### ④ 라이브 flash 발송이 사실상 미검증 (11월이 첫 실전)
`notifications` 총 **6행**(flash 2 · daily 4). 68개 발송대상은 08-13~15
**백필로 생겨서 알림이 안 나갔다.** 시즌에 수십 건이 몰릴 때의 동작은
`SEASON_MODE=on`이 되는 11월이 처음이다. `quarterly_backfill`도 스케줄만
걸려 있고 **한 번도 실행된 적 없다**(첫 실행 9/1).

## 3. 한 일

- `tests/sector_labels.py` — 손 라벨 78종목 정답지. **전부 실제 DB 값 그대로.**
  다투는 6종목(두산·삼성물산·현대로템·호텔신라·루닛·파크시스템스)은 뺐다 —
  정답지가 흔들리면 측정값이 의미를 잃는다.
- `sector_map.py` 개정 — 위치 우선 · 제외어 · 회사명 제외 · 업종전용 키워드.
- `dashboard/lib/sector.ts` 동일 알고리즘 반영 + `constants.json` 재생성.
- `tests/test_sector_map_parity.py` — **파이썬과 TS를 실제 값으로 대조.**
  `jiti`로 `sector.ts`를 직접 실행한다(`dashboard/scripts/sector_parity.mjs`).
- `tests/test_http_retry.py` — 재시도 횟수·총 대기시간·4xx 즉시 실패를 못 박는다.
- 배포 확인: 커밋 `14b32ee` → CI 41초 success → 배포 사이트에서 5종목 섹터 변경 확인.

## 4. 막힌 것 / 남긴 것

- **포스코퓨처엠·천보**는 못 맞힌다. 제품 나열 순서와 투자 정체성이 다른 소재
  기업이다. 맞히려면 대한항공이 '항공기' 한 단어로 방산이 된다(실측) — 안 고쳤다.
  정답지에 **틀린 채로 남기고** 근거를 적었다. 지우면 한계가 잊힌다.
- `jiti` v1의 별칭(`@`) 옵션이 조용히 안 먹는다. `sector.ts` 소스를 읽어
  임포트 한 줄만 상대경로로 바꿔 임시 파일로 돌린다(알고리즘은 손대지 않는다).
- `krx_universe.sector` 컬럼은 **DB에 없다.** 대시보드가 읽는 시점에 분류하므로
  DDL 없이 배포만으로 반영된다 — 규칙을 고치면 `export_constants`를 반드시 돌린다.

## 5. 다음 세션이 알아야 할 것

1. **섹터 규칙을 건드리면** `python -m src.config.export_constants`를 돌려라.
   안 돌리면 화면만 옛 답을 낸다 — 테스트가 잡지만, 잡히기 전까지 배포되면 조용하다.
2. **정확도 기준선은 `MIN_LABEL_ACCURACY = 0.96`**이고 `KNOWN_MISSES`는 2종목이다.
   총점만 보면 맞바꿈을 못 본다 — 두 테스트가 짝이다.
3. 남은 것은 **시간뿐**이다: D+20·D+60 표본, 11월 `SEASON_MODE=on` 첫 실전,
   9/1 `quarterly_backfill` 첫 실행. 이 셋은 코드로 앞당길 수 없다.
