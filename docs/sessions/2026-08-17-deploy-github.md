# 2026-08-17 — GitHub public 배포 · 시크릿 실검증

지난 세션이 "코드로 할 일은 끝났고 남은 건 배포"라며 보류했던 것을 실행했다.
사용자 확인: **GitHub까지만** · **비시즌 모드로 cron 활성**(Vercel은 사용자가 직접).

## 한 일

| 단계 | 결과 |
|---|---|
| `git init -b main` → 커밋 | 129파일 · `23710e5` |
| public repo 생성·push | https://github.com/gotomirae/Heimdallr_Call |
| Secrets 8개 + Variable 1개 | `SEASON_MODE=off` |
| 워크플로 실검증 4건 | ci · outcome_update · disclosure_poll · telegram_listen |

## 커밋 전에 한 안전 검사

`.gitignore` 실동작을 `git check-ignore`로 대조했다(추측하지 않았다):

```
.env.txt                IGNORED ok      ← 실제 API 키 21개가 든 파일
dashboard/.env.local    IGNORED ok
.venv/ .cache/ node_modules/ .next/     IGNORED ok
```

스테이징 **내용**도 실제 키 값으로 스캔했다 — 파일명만 보면 코드에 하드코딩된 키를 놓친다.
`.env.txt`의 값 21개를 하나씩 `git grep --cached`로 대조 → **누출 0건**.
(단, 첫 시도는 검사기 자체가 죽어 있었다 → **T54**.)

### `.gitignore`에 2줄 추가

```
.bkit/                          # 플러그인 런타임 상태 875K — 프로젝트 산출물이 아니다
.claude/settings.local.json     # ★ 전역 ignore에만 걸려 있었다
```

후자가 중요하다. `C:\Users\user/.config/git/ignore`가 막아 주고 있어서 **이 머신에서만**
안 올라간다. 다른 머신에서 클론하면 조용히 뚫린다 — 전역 ignore는 저장소를 따라가지 않는다.

## 시크릿은 등록이 아니라 **실행**으로 검증했다

등록 성공(`gh secret set` exit 0)은 값이 맞다는 증거가 아니다. 실제로 돌렸다.

| 워크플로 | 검증한 시크릿 | 실측 결과 |
|---|---|---|
| `ci` (push 자동) | 없음 | ✓ 39초 |
| `outcome_update` | SUPABASE_URL · SUPABASE_SERVICE_KEY · KIS_APP_KEY · KIS_APP_SECRET | ✓ `outcome_tracking upsert 459행` |
| `disclosure_poll -f notify=false` | OPENDART_API_KEY (+ Supabase) | ✓ `screen_results upsert 1111행` |
| `telegram_listen` | HEIMDALLR_TELEGRAM_BOT_TOKEN · CHAT_ID | ✓ `봇 8933940541 · 전용봇 True` |

`outcome_update`을 첫 검증 대상으로 고른 이유는 **Supabase·KIS 4개를 쓰면서
텔레그램 발송은 하지 않기** 때문이다. `disclosure_poll`도 `notify=false`로 발송을 껐다.

KIS가 진짜 불렸는지도 확인했다 — env 값이 `***`로 찍힌 것만으로는 증거가 안 된다:

```
대상 459건 · 일봉 구간 20260705~20260818
지수 종가 KOSPI 29일 · KOSDAQ 29일
```

D+5 등급별 초과수익은 지난 세션과 동일했다(★ +4.99 · ○ −0.68 · ✕ −4.20).
A축 IC가 D+1 +0.112 · D+5 +0.097로 여전히 최고 — ADR 1이 두 번째 측정에서도 지지된다.
`미래 분기 잔재 정리: 0행 삭제` → T36/T52 가드가 운영 환경에서도 동작한다.

**`ANTHROPIC_API_KEY`만 Actions에서 안 불렸다.** `telegram_listen`은 `LLM 분석 OFF`로 돌고
`disclosure_poll`은 알림을 껐기 때문이다. 값 자체는 로컬에서 이미 2회 실호출로 검증된 것과
같은 키다(cost_log $0.0643).

## ★ T53 — skip 수가 늘어난 건 커버리지가 사라진 것이다

커밋 직전 테스트가 **378 passed, 26 skipped**로 나왔다. 직전 기록은 403 passed, 1 skipped.
"passed"만 봤으면 그냥 넘어갔다.

로컬 venv에 `pyyaml`이 없어서 `tests/test_workflows.py` **25건이 통째로 skip**됐다.
하필 그게 **지금 public으로 올리려는 워크플로 YAML을 검증하는 테스트 전부**다 —
시크릿 하드코딩 검사, sleep 과금 검사, `python -m` 대상 모듈 존재 검사.

`pyproject.toml`에는 `dev` extras로 **제대로 선언돼 있었다**(T10 규칙 준수).
venv에 `.[dev]`를 안 깐 게 원인이다 → 설치 후 **403 passed, 1 skipped** 복구.

**정상 기준선은 `403 passed, 1 skipped`다.** 남은 skip 1건은
`PENDING_P11`이 비어서 나는 의도된 것이다.

## ★ T54 — 시크릿 검사기가 조용히 무력화됐다

```bash
git grep -c -F -- "$val" --cached | wc -l    # fatal → 파이프 뒤에서는 0
```

`--cached`를 패턴 뒤에 둬서 `git grep`이 fatal로 죽었는데, stderr는 흘러가고
`wc -l`이 **0**을 준다. **키가 실제로 새고 있어도 "누출 0건"이 나온다.**

→ 코드에 확실히 존재하는 문자열(`OPENDART_API_KEY`)로 스캐너를 먼저 쏴
**15개 파일 매칭**을 확인한 뒤에야 결과를 믿었다.

T51(RLS 빈 배열) · T49(미측정을 0으로)와 **같은 실패 모양**이다 —
0은 "안전"과 "검사 안 됨"을 구분해 주지 않는다.

## 지금 살아 있는 스케줄 (비시즌)

| 워크플로 | 주기 | 발송 |
|---|---|---|
| `universe_daily` | 매일 06:00 KST | — |
| `disclosure_poll` | 하루 4회 (`SEASON_MODE=off`) | ⚡ 즉시 알림 |
| `telegram_listen` | 07:00~24:00 KST 15분 | 질의 회신 |
| `daily_digest` | 평일 17:30 KST | 다이제스트 |
| `outcome_update` | 평일 07:00 KST | — |
| `promotion_check` | 월요일 07:00 KST | 승격 알림 |
| `quarterly_backfill` | 매월 1·15일 05:00 KST | — |

3Q 발표 시즌(11월경)에 `gh variable set SEASON_MODE --body on`으로 30분 폴링을 켠다.

## 막힌 것 / 남은 것

1. **Vercel 배포는 안 했다**(사용자 작업). Root Directory를 `dashboard`로 지정하는 게
   필수다 — 모노레포라 루트에 `next build` 대상이 없다. 환경변수 4개는
   `dashboard/.env.local`에 있고 `SUPABASE_SERVICE_KEY`가 없으면 `/settings` 비용이
   `—`로 뜬다(0으로 뜨면 안 된다 — T51).
2. **Node 20 deprecation 경고.** `actions/checkout@v4` · `actions/setup-python@v5`가
   Node 24로 강제 실행되고 있다. 지금은 동작하지만 v5/v6로 올려야 한다.
3. **로컬 `--watch`를 켜지 마라.** `telegram_listen` cron이 살아났다 —
   동시에 켜면 `getUpdates`가 서로 메시지를 뺏는다(T44). 폴러는 하나만이다.
4. `ANTHROPIC_API_KEY`는 Actions에서 아직 안 불렸다. 첫 `daily_digest`나
   ★/○ 종목 발생 시 확인된다.

## 다음 세션이 알아야 할 것

1. **repo는 public이다**(Actions 무료 한도 때문). 시크릿은 GitHub Secrets에만 있고
   Supabase anon key는 원래 공개 전제 + RLS 방어다.
2. **테스트 기준선 `403 passed, 1 skipped`.** venv에 `pip install -e ".[dev]"`가 필요하다.
3. **이제부터는 실제로 텔레그램이 나간다.** 코드를 고치고 push하면 다음 cron부터 반영된다.
4. 남은 건 Vercel 배포와 **시간**(D+20·D+60 표본이 쌓이는 것)뿐이다.

---

# 후속 — 자동화 가능한 잔여 작업 처리 (같은 날)

## 1. Node 20 deprecation 해소

```
actions/checkout    v4 → v7
actions/setup-python v5 → v7
actions/cache       v4 → v6
```

메이저를 3단계씩 건너뛰지만 **변경점이 전부 Node24 전환 + ESM 마이그레이션**이라
이 repo 사용법(입력 없는 checkout, `python-version`+`cache: pip`, 단순 path 캐시)에는
영향이 없다. 러너는 실측 **2.336.0**으로 요구치 2.327.1을 넘는다.
setup-python v7의 "Validate and retry manifest fetch to prevent silent failures"는
이 프로젝트 성향에 오히려 맞는 변경이다.

검증: push → `ci` ✓ **411 passed**, `telegram_listen` ✓ — **ANNOTATIONS 섹션 자체가 사라졌다.**

## 2. `DASHBOARD_BASE_URL` 배선 (조용한 링크 사망 방지)

텔레그램 메시지의 대시보드 링크는 코드에 박힌 기본값을 쓰고 있었다:

```python
optional_env("DASHBOARD_BASE_URL", "https://heimdallr-call.vercel.app")
```

워크플로가 이 값을 **전달하지 않았다.** Vercel 프로젝트 이름이 기본값과 다르면
그날부터 전 메시지의 링크가 죽는데 — 에러도 없고 메시지는 멀쩡해 보이고
**눌러보기 전까지 아무도 모른다.**

→ 텔레그램 봇 토큰을 받는 워크플로 5개에 배선:

```yaml
DASHBOARD_BASE_URL: ${{ vars.DASHBOARD_BASE_URL }}
```

**변수가 없어도 안전하다.** `optional_env`는 빈 문자열을 default로 떨군다(실측 확인,
`src/utils/env.py:80`). 즉 지금 당장은 기존과 동일하게 동작하고,
Vercel 도메인이 정해지면 `gh variable set`만으로 덮을 수 있다.

### 테스트는 "깨뜨려서" 검증했다

`test_sending_workflows_wire_dashboard_url` 추가. 판정 기준을 `--send` 플래그가 아니라
**봇 토큰 보유**로 잡았다 — `telegram_listen`은 `--send` 없이 회신하므로 플래그로 거르면 빠진다.

넣기 전에 `daily_digest.yml`에서 배선을 지우고 돌려 **실제로 FAIL하는 것을 확인**했다:

```
FAILED tests/test_workflows.py::test_sending_workflows_wire_dashboard_url[daily_digest.yml]
1 failed, 7 passed          ← 지웠을 때
8 passed                    ← 복원 후
```

T54의 교훈이다. 통과만 보고 넣으면 아무것도 안 하는 테스트가 하나 늘 뿐이다.
**tests 403 → 411 passed.**

## ★ 발견 — 정기 실행에서는 LLM이 영영 불리지 않는다

`ANTHROPIC_API_KEY`를 쓰는 워크플로는 `telegram_listen` **하나뿐**인데,
`--analyze`가 **수동 실행(workflow_dispatch)에만** 붙는다:

```yaml
run: python -m src.notify.listen --once ${{ inputs.analyze && '--analyze' || '' }}
```

cron 실행에는 `inputs`가 없다 → 항상 빈 문자열 → **LLM 호출 0회.**
실측 로그도 매번 `LLM 분석 OFF`다. `src.analysis.run`을 부르는 워크플로는 없다.

즉 지금 상태로 두면 사용자가 종목을 물어봐도 **해석 없는 숫자 리포트만** 간다
(`analysis_block`이 빈 채로 나간다). 이미 분석이 있는 종목만 예외다.

비용이 걸린 결정($0.03/건)이라 **임의로 바꾸지 않고 사용자 판단으로 남긴다.**
`default: false`가 의도적 비용 방어인지, cron 경로를 빠뜨린 것인지가 갈린다.
CLAUDE.md는 "LLM은 기존 분석 없을 때만 호출(재질의해도 비용 0)"이라고 적어
**호출하는 쪽이 의도**로 읽히지만, 확정은 사용자 몫이다.

---

# 후속 2 — LLM 정기 분석 ON · Vercel 도메인 반영 (사용자 요청)

## LLM을 켰다 — 다만 플래그만 뒤집으면 안 됐다

요청은 "켜줘"였지만 원래 형태는 **양방향으로** 고장나 있었다(→ **T55**).

```yaml
${{ inputs.analyze && '--analyze' || '' }}
```

`schedule`에는 `inputs`가 없어 늘 빈 문자열이고(그래서 cron에서 LLM 0회),
기본값만 `true`로 뒤집으면 이번엔 GitHub 표현식에서 `false`가 falsy라
**`-f analyze=false`가 조용히 무시된다.** 그래서 분기를 셸로 옮겼다.

두 경로를 **둘 다** 돌려 확인했다 — 켠 쪽만 보면 ②를 못 잡는다:

```
기본 디스패치        → 허용 chat: [***] · LLM 분석 ON
-f analyze=false    → LLM 분석 OFF — 수동 실행에서 명시적으로 껐다
```

### 비용은 코드가 막는다 (켜기 전에 확인한 것)

| 장치 | 값 | 위치 |
|---|---|---|
| 월 하드실링 | **$8** | `MONTHLY_COST_CEILING_USD` |
| 일일 건수 | **20건** | `DAILY_ANALYSIS_LIMIT` |
| 재질의 | **0원** | `ensure_analysis`가 기존 분석 재사용 |
| 호출 전 검사 | `check_budget()` | `analyze.py:186` |

건당 실측 $0.03 기준 일 최대 $0.60이고, 월 실링이 먼저 막는다.
모르는 chat은 조용히 무시되므로 외부인이 비용을 태울 수 없다.

### timeout 5 → 12분 (곁다리로 드러난 것)

`confirm()`이 **배치를 다 처리한 뒤에야** offset을 확정한다(`listen.py:243`).
BATCH 20 × 분석 30초면 5분을 넘겨 죽고, 죽으면 확정이 안 돼
**같은 20건이 계속 재배달된다** → 매번 같은 자리에서 죽는 빨간 X 루프.
질문은 영영 답을 못 받는데 로그만 쌓인다. timeout은 상한일 뿐이라 과금은 늘지 않는다.

## Vercel 도메인 — 프로젝트 이름을 바꿀 필요는 없었다

사용자 확인: Vercel 프로젝트명은 **`heinmdallr`**(코드 기본값은 `heimdallr-call`).

이름을 맞출 필요는 없다. 앞서 배선한 저장소 변수가 그 목적이었다:

```
gh variable set DASHBOARD_BASE_URL --body https://heinmdallr.vercel.app   ✓ 등록
```

다만 **fallback이 틀린 채 남으면 변수가 빠졌을 때 조용히 죽으므로** 코드 기본값도 고쳤다.
그러면서 3개 파일(`batch.py`·`promotion.py`·`run.py`)에 흩어져 있던 리터럴을
`constants.DASHBOARD_URL_DEFAULT` 한 곳으로 모았다 —
"임계값은 constants.py 한 곳에만"이라는 프로젝트 규칙이 URL에는 안 지켜지고 있었다.
`.env.example`도 갱신.

**tests 411 → 412 passed.** `test_telegram_listen_analyzes_on_schedule`은
옛 형태로 되돌리면 실제로 FAIL하는 것을 확인하고 넣었다.

## 남은 사용자 작업

1. **Vercel 배포** — Root Directory `dashboard`, 환경변수 4개.
2. 배포 후 **실제 URL이 `heinmdallr.vercel.app`이 맞는지 확인.** Vercel이 이름 충돌 시
   접미사를 붙이므로 다르면 `gh variable set DASHBOARD_BASE_URL`로 덮으면 된다(코드 수정 불필요).
3. 텔레그램 봇에 종목명 하나 보내기 — 이제 분석이 없으면 LLM이 붙어 회신한다.

## ANTHROPIC 경로까지 실검증 — 8개 시크릿 전부 확인 완료

"봇에 메시지를 보내는 것"은 사용자 계정이 필요하지만, **LLM 호출 경로 자체는
`build_report(code, analyze=True)`로 직접 돌릴 수 있다.** 텔레그램 수신만 못 흉내낼 뿐이다.

대상 선정: `screen_results`를 **종목별 최신 1행으로 접고**(T40) ★ 등급 중 분석이 없는 것.
실측 — 원본 1,595행 → 1,111종목 · ★ 26종목 · **기존 분석은 단 1건**(그래서 26개 전부 후보).

```
llm_called: True · analysis: 신규 호출 $0.0348      ← PRD 상한 $0.05 이내
cost_log:   월 $0.0643 → $0.0991
일일 카운터: 0 → 1 / 20
메시지 961자 · 💡 해설 · 트리거 2건 · 리스크 1건 전부 채워짐
🔗 https://heinmdallr.vercel.app/stock/452280      ← DASHBOARD_URL_DEFAULT 적용 확인
```

로컬에는 `DASHBOARD_BASE_URL` 환경변수가 없으므로 이 링크는 **새 상수가 실제로 쓰인
증거**다. Actions에서는 저장소 변수가 같은 값을 덮는다.

이로써 **Secrets 8개 전부 실행으로 검증**됐다(직전까지 ANTHROPIC만 미확인이었다).

## Vercel — 자격증명이 이 머신에 없다

확인한 것: Vercel CLI 미설치 · `%APPDATA%/com.vercel.cli` 없음 · `~/.vercel` 없음 ·
`.env.txt`에 VERCEL 키 없음 · 참고 프로젝트에도 없음. node 24.15.0 / npm 11.12.1은 있다.

따라서 배포는 **브라우저 로그인** 또는 **사용자가 발급한 Vercel 토큰** 중 하나가 필요하다.
토큰이 있으면 CLI로 프로젝트 생성·Root Directory 지정·환경변수 4개 주입·프로덕션 배포까지
전부 무인으로 가능하다(`dashboard/.env.local`에 필요한 4개가 모두 있는 것을 확인).
