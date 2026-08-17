# 워크플로 공통 규칙 (PRD §10)

## 비용 — **repo를 public으로 둘 것** (실측 추정)

| 워크플로 | 월 실행 | 분/회 | 월 합계 |
|---|---:|---:|---:|
| universe_daily | 30 | 33 | 990 |
| disclosure_poll (시즌) | 380 | 2 | 760 |
| telegram_listen | 2,040 | 1 | 2,040 |
| quarterly_backfill | 2 | 45 | 90 |
| daily_digest | 20 | 1 | 20 |
| ci | 20 | 2 | 40 |
| outcome_update | 20 | 8 | 160 |
| **합계** | | | **4,108분** |

private 무료 한도가 **2,000분/월**이라 **2.1배 초과**한다. public은 무제한 무료다.
시크릿은 GitHub Secrets에 있고 Supabase anon key는 원래 공개 전제 + RLS로
방어되므로 코드 공개가 문제되지 않는다.

`universe_daily`의 33분은 추정이 아니라 **실측**이다(시세 1,112종목 × 2콜 = 1,988초).
- **잡 안에서 sleep 루프 금지.** sleep도 과금된다. 짧은 잡을 여러 번 띄우는 편이 싸다.
- 잡당 `timeout-minutes` 필수. 무한 대기가 분을 태운다.

## 필요한 Secrets
| 이름 | 쓰는 곳 |
|---|---|
| `OPENDART_API_KEY` | 재무·공시 수집 |
| `SUPABASE_URL` · `SUPABASE_SERVICE_KEY` | 전 워크플로 |
| `KIS_APP_KEY` · `KIS_APP_SECRET` | 시세(universe_daily만) |
| `HEIMDALLR_TELEGRAM_BOT_TOKEN` · `HEIMDALLR_TELEGRAM_CHAT_ID` | 알림 |
| `ANTHROPIC_API_KEY` | LLM 분석 |

## 필요한 Variables
| 이름 | 값 | 뜻 |
|---|---|---|
| `SEASON_MODE` | `on` / `off` | 공시 폴링 빈도 전환 |

## KIS 토큰 캐시
KIS를 부르는 워크플로는 **`universe_daily` 하나뿐**이고 하루 1회다.
따라서 매 실행 토큰 재발급도 한도에 걸리지 않는다.
그래도 `actions/cache`로 `.cache/`를 보존해 재발급을 줄인다 —
수동 재실행이 잦으면 발급 제한(분당 1회)에 걸릴 수 있기 때문이다.

## ⚠ 폴러는 하나만
`telegram_listen`은 `getUpdates`를 쓰는데 이건 **읽기가 아니라 소비**다(T44).
로컬 `--watch`와 이 워크플로를 동시에 켜면 서로 메시지를 빼앗는다.
`concurrency` 그룹으로 워크플로끼리는 막았지만 로컬까지는 못 막는다.
