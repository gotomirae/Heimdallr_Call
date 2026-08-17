# 2026-08-16 — 대시보드 나머지 3화면 (/screener · /season · /settings)

PRD §9의 우선순위 4·5·7. 이로써 **PRD가 정의한 7개 화면이 전부** 구현됐다.

## 한 일

| 화면 | 경로 | 핵심 |
|---|---|---|
| 전 종목 스크리너 | `app/screener/` + `components/ScreenerTable.tsx` | 필터 6종 · **탈락 사유 표시** |
| 시즌 현황 | `app/season/` | 진행률 · 발표 캘린더 · 미발표 종목 |
| 설정·비용 | `app/settings/` + `app/api/cost/route.ts` | 임계값 읽기 전용 · 비용 |
| 상수 내보내기 | `src/config/export_constants.py` | `constants.py` → `dashboard/lib/constants.json` |

## 실측

### /screener — 이 화면만 전수를 본다

```
1,111종목 · 가속 344 · 탈락 731 · 판정 불가 36
필터: 게이트 · 등급 · 분기(3) · 시총(4구간) · 컨센 · 업종(125)
```

다른 화면은 가속 종목만 담지만 여기는 **"왜 안 걸렸나"를 확인하는 곳**이라
`getLatestScreens({ accelerating: false })`로 전수를 읽는다.

탈락 사유가 종목별로 붙는다(실측):

```
대명에너지    → 매출 가속 없음
안트로젠      → 이익 성장 없음
두산로보틱스   → 이익 성장 없음
```

### /season

```
2026.2Q 시즌 현황 · 정기보고서 마감 8월 14일
진행률 43.3%  (481 / 1,112종목)
확정 129 · 잠정만 352 · 미발표 631
발표 캘린더 21일치 (07-15 ~ 08-13, 피크 08-13에 155건)
```

### /settings

임계값은 **읽기 전용**이다. 화면에서 고칠 수 있게 만들면 파이썬 상수와 갈라져
어느 쪽이 실제로 쓰이는지 알 수 없게 된다.

`constants.py`가 유일한 출처라는 규칙을 지키려고 **JSON 생성물**을 만들었다 —
TS에 숫자를 다시 적으면 두 곳이 조용히 어긋난다(참고 프로젝트가 겪은 사고).
`tests/test_constants_export.py`가 생성물이 낡는 것까지 막는다:

```
A 35 · B 32 · C 15 · D 18 = 100
분모 82/67/100/85 = 축 합과 일치
PRI p1~p4 = 100 · 분모 하한 40 > p2(25)
```

## ★ T51 — RLS는 에러가 아니라 빈 배열을 준다

`/settings`에서 비용이 **$0.0000 / 0건**으로 나왔다. 실제로는 `$0.0643 · 2건`이다.

`cost_log`에는 anon SELECT 정책을 **일부러 주지 않았다**(schema.sql에 명시).
그런데 그걸 잊고 anon 클라이언트로 바로 읽었고, RLS는 **행을 숨길 뿐 에러를 내지 않는다.**
화면은 200이고 콘솔도 조용하다 — "아직 LLM을 안 썼구나"로 읽고 넘어가기 딱 좋다.

anon 접근을 테이블별로 실제 대조해 원인을 확정했다:

```
cost_log                 anon 0행     ← 정책 없음(의도)
notifications            anon 1행
screen_results           anon 1,594행
quarterly_fundamentals   anon 10,091행
```

→ `app/api/cost/route.ts`(service_role)를 경유한다. 스키마 주석이 지시한 방식 그대로다.
→ 키가 없거나 실패하면 **0이 아니라 `available: false` + 사유**를 돌려주고,
  화면은 숫자 대신 `—`와 경고를 띄운다. **"0"으로 보이면 안 된다.**

## ★ T52 — 미래 분기 한 행이 화면을 무의미하게 만든다

`/season`이 처음에 이렇게 나왔다:

```
2026.3Q 시즌 현황
발표 진행률 0.1%  (1 / 1,112종목)
```

2026-08에 3분기는 끝나지도 않았다. 원인은 **T36에서 이미 찾아낸** 비12월 결산 기업의
`2026.3Q` 행 하나다. 스크리너에서는 `last_reportable_index()`로 막아 뒀는데,
**새 화면을 만들며 같은 규칙을 다시 적용하지 않았다.**

→ 대시보드에도 같은 날짜 상한을 적용 → **2026.2Q · 43.3%**로 정상화.

**한 곳에서 막은 함정은 새 소비자가 생길 때마다 다시 뚫린다.**

## 설계 판단

**임계값을 화면에서 고칠 수 있게 만들지 않았다.** 편집 UI를 붙이면 파이썬 상수와
DB 값 중 무엇이 실제로 쓰이는지 추적이 안 된다 — 이 프로젝트에서 가장 비싼 종류의 혼란이다.

**스크리너만 전수를 본다.** 나머지 화면은 가속 종목만 담는다(사용자 요청).
`getLatestScreens({ accelerating })`로 조회 계층에서 한 번에 가르므로
새 화면이 실수로 탈락분을 섞을 일이 없다.

**비용은 실패를 0으로 표시하지 않는다.** 이게 T51의 교훈이고,
프로젝트 전반의 원칙("결측은 None, 0이 아니다")과 같은 규칙이다.

## 테스트

```
python -m pytest tests/   →  403 passed, 1 skipped  (직전 395)
```

`tests/test_constants_export.py` 8건 — 생성물 동기화 · 축 합 100 ·
분모가 축 합과 일치 · PRI 분모 하한이 p2보다 큼(T35) · 매트릭스 임계 순서.

## 막힌 것 / 미완

1. **`/screener`는 300종목까지만 그린다.** 1,111행을 한 번에 그리면 느리다.
   가상 스크롤이나 서버 페이징이 필요하지만 지금 표본에서는 필터로 충분하다.
2. **`SUPABASE_SERVICE_KEY`가 대시보드에 필요해졌다.** Vercel 배포 시
   환경변수로 넣어야 `/settings`의 비용이 보인다(없으면 사유와 함께 `—`).
3. **P11 이후 남은 것은 전부 배포와 시간**이다 — 코드로 할 일은 끝났다.

## 다음 세션이 알아야 할 것

1. **PRD의 7개 화면이 전부 구현됐다.** `/stock/[code]` `/` `/matrix`
   `/screener` `/season` `/outcome` `/settings`.
2. **상수를 고치면 `python -m src.config.export_constants`를 반드시 돌려라.**
   안 돌리면 대시보드가 옛 숫자를 보여준다 — 테스트가 잡아주지만 CI에서만 안다.
3. **0행을 보면 권한부터 의심하라**(T51). RLS를 켠 프로젝트에서 "데이터가 없네"는
   절반의 확률로 "볼 수 없네"다.
4. 남은 일은 **repo public 전환 + Vercel 배포**뿐이다(사용자 작업).

## 배포 절차 안내 (2026-08-16, 코드 변경 없음)

**아직 git repo가 아니다** (`git status` → `not a git repository`). 배포 방법을 단계별로
안내만 하고 실행은 보류했다 — repo 생성·push·secrets 등록은 되돌리기 까다롭고
push 즉시 `telegram_listen`·`disclosure_poll` cron이 살아나 **실제 텔레그램 발송이
시작될 수 있어** 사용자 확인 없이 실행하지 않았다.

**GitHub public 전환**: `git init` → `.gitignore`가 `.env.txt`·`dashboard/.env.local`
차단 확인 → `gh repo create Heimdallr_Call --public --source=. --remote=origin --push`
→ Secrets 8개(`OPENDART_API_KEY` · `SUPABASE_URL` · `SUPABASE_SERVICE_KEY` ·
`KIS_APP_KEY` · `KIS_APP_SECRET` · `HEIMDALLR_TELEGRAM_BOT_TOKEN` ·
`HEIMDALLR_TELEGRAM_CHAT_ID` · `ANTHROPIC_API_KEY`, `.github/workflows/_setup.md` 참조)
+ Variable `SEASON_MODE=off`(2Q 시즌 종료 상태) 등록.

**Vercel 배포**: repo import 시 **Root Directory를 `dashboard`로 지정 필수**
(모노레포라 루트에 `next build` 대상이 없어 안 하면 빌드 실패) → 환경변수 4개
(`NEXT_PUBLIC_SUPABASE_URL` · `NEXT_PUBLIC_SUPABASE_ANON_KEY` · `SUPABASE_URL` ·
`SUPABASE_SERVICE_KEY`, 값은 `dashboard/.env.local`) → 배포 후 `/settings`가
`—` 아닌 실제 비용(`$0.0643` 부근)을 보이는지로 `SUPABASE_SERVICE_KEY` 검증.

`gh auth status` 확인 결과 `gotomirae` 계정으로 이미 로그인돼 있어(`repo`·`workflow`
스코프 보유) 사용자가 진행 신호를 주면 GitHub 쪽은 CLI로 바로 실행 가능하다.
