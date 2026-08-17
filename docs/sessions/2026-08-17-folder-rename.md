# 2026-08-17 — 폴더 rename 수습 · 운영 상태 점검

전 세션(배포 완료)에서 **예고만 해뒀던 T57이 실제로 발동한 세션**이다.
새 기능은 없다. 코딩·배포는 이미 끝났고 남은 건 시간이라는 판단은 그대로다.

## 한 일

### 1. 폴더 rename 수습 (T57 실발동)

사용자가 로컬 폴더를 `C:\Claude\dev\Heinmdallr_Call` → `C:\Claude\dev\Heimdallr_Call`로
바꿨다(명명 규칙 `Heimdallr`(m) 확정에 맞춘 정리).

**들어왔을 때의 상태 — 겉보기엔 멀쩡했다.**

```
$ python -c "import src; print(src.__file__)"
C:\Claude\dev\Heimdallr_Call\src\__init__.py          ← 정상으로 보인다
```

그런데 finder는 옛 경로를 가리키고 있었다:

```
.venv/Lib/site-packages/__editable___heimdallr_call_0_1_0_finder.py
  → Heinmdallr_Call  (1건)
```

**프로젝트 밖에서 부르니 바로 드러났다:**

```
$ cd /c && .venv/Scripts/python.exe -c "import src"
ModuleNotFoundError: No module named 'src'
```

루트 안에서 통과한 건 cwd가 `sys.path`에 들어가서지 editable 설치가 살아서가 아니다.

**조치**

```
python -m pip install -e ".[dev]"
  → Uninstalling heimdallr-call-0.1.0 / Successfully installed heimdallr-call-0.1.0
```

**검증(세 갈래 전부)**

| 검증 | 결과 |
|---|---|
| finder 경로 | `Heimdallr_Call` 1건 (옛 경로 0건) |
| 루트 **밖**에서 `import src` | `C:\Claude\dev\Heimdallr_Call\src\__init__.py` ✓ |
| 루트 밖에서 깊은 임포트 | `src.config.constants`(대문자 상수 66개) · `src.notify.telegram.bot_id_of` ✓ |
| `pytest tests/ -q` | **413 passed, 1 skipped** — 기준선 일치(T53) |

`pyvenv.cfg`의 `command` 줄에는 옛 경로가 남아 있으나 **기록용이라 동작 무관** — 건드리지 않았다.
console script(`[project.scripts]`)는 정의된 게 없어 `.exe` 런처 문제도 없다.

### 2. 대시보드 — 경로 의존 없음 확인

`.next` 빌드 캐시가 절대경로를 들고 있어 rename 후 조용히 어긋날 수 있어 확인했다.

```
npx tsc --noEmit   → exit 0
npm run build      → 10 라우트 전부 정상 (7화면 + /api/cost + /api/telegram/lookup + _not-found)
```

### 3. 운영 중인 시스템 상태 점검

| 항목 | 실측 |
|---|---|
| 대시보드 | https://heimdallr-call.vercel.app → **200** |
| `/api/cost` | `available:true` · `spentUsd 0.0991204` · `monthCalls 3` (월 실링 $8) |
| cron | `telegram_listen`(schedule, 26초) · `disclosure_poll`(schedule, 7초) 모두 성공 |
| git | 작업 트리 clean · origin/main 동기화 · remote `gotomirae/Heimdallr_Call` |

**CI 실패 1건(31984269498)은 코드 문제가 아니다.**

```
httpx.HTTPStatusError: Client error '403 Forbidden'
  for url 'https://kind.krx.co.kr/corpgeneral/corpList.do?...'
RuntimeError: HTTP 조회 실패: https://kind.krx.co.kr/corpgeneral/corpList.do
```

전 세션이 "다음 세션이 알아야 할 것 4번"으로 정확히 예고한 KRX 일시 장애다.
직후 실행들은 전부 success. **collector를 모킹하지 않는 설계의 대가**이고, 판별법도
그대로 유효하다 — 빨간 X를 보면 먼저 실패 테스트 이름이 `test_universe`·`test_dart_*`인지,
사유가 `HTTP 조회 실패`인지 확인한다.

## 막힌 것

없다.

## 문서에 남긴 것

- `CLAUDE.md` — 폴더명 문단을 **현재 사실로** 수정(`Heimdallr_Call`, rename 날짜 명시).
  "코드는 폴더명에 의존하지 않지만 **venv는 의존한다**"로 초점을 옮겼다.
  진행 상황에 3줄 추가 + 250줄 규칙에 따라 T39·P9(모두 traps.md에 있거나 후속 항목에
  대체됨) 삭제 → 247줄.
- `docs/traps.md` T57 — **"실제로 발생했다"** 절 추가. 핵심은 검증 방법이다:
  **pytest 초록은 이 함정의 증거가 되지 못한다**(`pythonpath = ["."]`).
  반드시 **프로젝트 밖에서 `import src`**를 해봐야 한다.

## 다음 세션이 알아야 할 것

1. **여전히 남은 건 시간이다.** D+20·D+60 표본 축적, 11월 3Q 시즌에
   `gh variable set SEASON_MODE --body on`.
2. **폴더를 또 옮기면 `pip install -e ".[dev]"`.** 검증은 루트 밖 `import src`로.
3. 기준선 **`413 passed, 1 skipped`** — passed 수만 보지 말고 skip까지 대조(T53).
4. **로컬 `--watch` 금지** — `telegram_listen` cron이 살아 있다(T44).
5. `.claude/settings.local.json`에 옛 경로가 박힌 허용 규칙이 1건 남아 있다.
   git 추적 대상이 아니고 매칭이 안 될 뿐이라 **동작에는 무해하다**(권한 프롬프트가 한 번 더
   뜨는 정도). 고칠 필요를 느끼면 그때 지워라.
