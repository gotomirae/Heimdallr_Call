# Heimdallr_Call 🛡️

KOSPI/KOSDAQ 시가총액 1,000억원 이상 약 1,300종목을 대상으로,
**분기실적이 실제로 가속되고 있으면서 그 사실이 아직 주가에 반영되지 않은 종목**을
매 분기 자동 발굴해 텔레그램(🛡️ @Invest_EarningCallBot)과 전용 대시보드로 전달한다.

- 설계 문서: [`docs/PRD.md`](docs/PRD.md) — **구현 전에 해당 절을 읽는다**
- 함정 목록: [`docs/traps.md`](docs/traps.md) — **새 모듈 만들기 전 필독**
- Phase 프롬프트: [`docs/phases.md`](docs/phases.md) · 작업 지침: [`CLAUDE.md`](CLAUDE.md)

현재 상태: **P8 텔레그램 완료** (유니버스 1,322 · 분기재무 9,743 · 스크리닝 1,111 · 공시 639 · 컨센서스 207 · 시세 1,112 · 분석 1 · 알림 1 · P9 대시보드 대기)

---

## 셋업 순서

### 1. 의존성 설치

```bash
python -m venv .venv && .venv\Scripts\activate && pip install -e ".[dev]"
```

### 2. 환경변수

```bash
copy .env.example .env
```

`.env`를 채운다. 이 폴더에 이미 있는 `.env.txt`에서 값을 옮겨도 되지만,
**Supabase 값은 반드시 아래 3번 체크리스트로 검증한 뒤에 쓴다.**

> `src/utils/env.py`가 `.env`를 먼저 찾고, 없으면 `.env.txt`를 읽는다.
> 둘 다 `.gitignore`에 있다.

### 3. Supabase 스키마 적용 — ★ 여기가 P0의 본체다

`src/db/schema.sql`은 **REST로 실행할 수 없는 DDL**이다. 직접 붙여넣어야 한다.

1. Supabase 대시보드에서 **Heimdallr 전용 신규 프로젝트**를 연다
   (HermesCall 프로젝트가 아닌지 확인 — 아래 체크리스트)
2. 좌측 **SQL Editor** → **New query**
3. `src/db/schema.sql` 전문을 붙여넣고 **Run**
4. `Success. No rows returned` 확인

파일은 idempotent(`IF NOT EXISTS`)라 여러 번 실행해도 안전하다.
이후 Phase에서 컬럼이 추가되면 파일 하단 "증분 마이그레이션" 절에
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`로 덧붙인 뒤 통째로 다시 실행한다.

### 4. 검증

```bash
python -m src.db.init
```

11개 테이블 존재 + anon SELECT 동작 + `cost_log` 차단을 확인한다.
**여기서 통과해야 P1로 넘어간다.**

```bash
python -m pytest tests/
```

---

## ⚠️ 적용 전 체크리스트 (직접 확인할 것)

- [ ] **`SUPABASE_URL`의 프로젝트 ref가 HermesCall과 다른가?**
      `https://<ref>.supabase.co`의 `<ref>`를 눈으로 대조한다.
      Heimdallr는 신규 Supabase 프로젝트를 쓴다(ADR 8 · traps.md T16).
      **같은 값이면 HermesCall DB에 Heimdallr 테이블이 생성되어 분리 이유가 통째로 무너진다.**
      - HermesCall ref: `tioefbkuzidqecovbyku`
      - 현재 `.env.txt`의 Heimdallr ref: `drpxciqkbjlruximqbox` → **다름 (확인 완료 2026-08-13)**
- [ ] `SUPABASE_URL`에 `/rest/v1`이 붙어 있지 않은가? (supabase-py가 스스로 붙인다)
- [ ] `SUPABASE_SERVICE_KEY`에 **secret 키**(`sb_secret_...`),
      `NEXT_PUBLIC_SUPABASE_ANON_KEY`에 **publishable 키**(`sb_publishable_...`)가 들어갔는가?
      ⚠️ `sb_secret_...`를 `NEXT_PUBLIC_*`에 넣으면 RLS를 우회해 전체 데이터가 열린다.
- [ ] Supabase Free는 조직당 활성 프로젝트 2개다. HermesCall이 1개를 쓰므로 여유가 1개뿐 —
      다른 프로젝트가 슬롯을 먹고 있지 않은지 확인.
- [ ] `.env` / `.env.txt`가 git에 올라가지 않는지 (`git status`로 확인)

---

## 절대 금지 (요약 — 전문은 CLAUDE.md)

- **`setWebhook` 호출 금지.** 봇당 웹훅 1개만 허용되고 조용히 덮어써진다.
  HermesCall 대시보드가 점유 중이다. Heimdallr는 `sendMessage` 발송 전용.
- **KIS 주문 API 호출 금지.** `KIS_ALLOWED_PATHS` 화이트리스트 밖은 호출하지 않는다.
- **`os.environ` 직접 읽기 금지.** 반드시 `src/utils/env.py`.
- **KIND 상장법인목록을 `lxml`로 파싱 금지.** 코스닥 1,839행 중 1,282행에서
  예외도 경고도 없이 잘라낸다. 이 소스만 `html.parser`.
- **PostgREST 1,000행 초과 조회는 `range()` 페이징.** `src/db/supabase_client.py`의
  `select_all()`을 쓴다.
- **새 서드파티 임포트는 `pyproject.toml`에 먼저 선언.**

---

## 디렉터리

```
src/
  config/constants.py     임계값·배점의 단 하나의 출처 (PRD 부록 A)
  utils/env.py            환경변수 단일 창구 (.strip() 강제)
  db/schema.sql           PRD §6 — SQL Editor에 붙여넣어 실행
  db/supabase_client.py   range() 페이징 강제, URL 검증
  db/init.py              P0 검증 게이트
  collectors/             P1·P2·P4·P5·P6 — 외부 데이터 수집
  finance/                P2 quarterize.py ★급소 · P2.5 파생지표
  screener/               P3 순수 함수 (외부 I/O 금지)
  analysis/               P7 LLM 해석 · cost guard
  notify/                 P8 텔레그램 (발송 전용)
  universe/               P1 유니버스
tests/
docs/  PRD.md · traps.md · phases.md · decisions/ · sessions/
```
