# DDL(마이그레이션) 적용 방법

> **왜 사람이 해야 하나:** Supabase REST API로는 `CREATE TABLE`·`ALTER TABLE` 같은
> DDL을 실행할 수 없다. `SUPABASE_SERVICE_KEY`는 PostgREST(데이터 읽기·쓰기)용이고
> 스키마 변경 권한이 아니다. `src/db/init.py`도 이 전제로 만들어져 있다 —
> "이 스크립트는 DDL을 실행하지 않는다. 하는 일은 적용이 됐는지 확인하는 것뿐이다."

## 대상 프로젝트

```
Supabase 프로젝트 ref : drpxciqkbjlruximqbox
(HermesCall과 다른 별개 프로젝트다 — ADR 8. 반드시 위 ref를 확인하고 실행하라.)
```

---

## 1단계 — SQL Editor 열기

1. https://supabase.com/dashboard 로그인
2. 프로젝트 목록에서 **ref가 `drpxciqkbjlruximqbox`인 것**을 선택
   (이름이 비슷한 프로젝트가 있으면 ref로 구분한다)
3. 왼쪽 사이드바 → **SQL Editor** (아이콘: `>_`)
4. **New query** 클릭

## 2단계 — SQL 붙여넣고 실행

아래를 **전체 복사**해 붙여넣고 **Run**(또는 `Ctrl+Enter`):

```sql
-- 발표일 기준 추적: 발표 전 5일 · 발표 당일
-- ★ 컬럼명에 '-'를 쓸 수 없어 음수 시점은 m으로 적는다 (ret_dm5 = D-5)
ALTER TABLE outcome_tracking ADD COLUMN IF NOT EXISTS ret_dm5    NUMERIC;
ALTER TABLE outcome_tracking ADD COLUMN IF NOT EXISTS excess_dm5 NUMERIC;
ALTER TABLE outcome_tracking ADD COLUMN IF NOT EXISTS ret_d0     NUMERIC;
ALTER TABLE outcome_tracking ADD COLUMN IF NOT EXISTS excess_d0  NUMERIC;
```

- `IF NOT EXISTS`가 붙어 있어 **여러 번 실행해도 안전하다**(멱등).
- 성공하면 `Success. No rows returned`가 뜬다. 이게 정상이다 —
  DDL은 돌려줄 행이 없다.

### (선택) 섹터 컬럼

**하지 않아도 된다.** 대시보드가 `industry`·`products`로 읽는 시점에 분류하므로
컬럼 없이도 섹터가 정상 표시된다(T71). 배치로 미리 계산해 두고 싶을 때만:

```sql
ALTER TABLE krx_universe ADD COLUMN IF NOT EXISTS sector TEXT;
CREATE INDEX IF NOT EXISTS krx_universe_sector_idx ON krx_universe (sector);
```

## 3단계 — 적용 확인

터미널에서:

```bash
python -m src.db.init
```

`✓ P0 검증 게이트 통과`가 나오면 스키마가 정상이다.
컬럼 단위로 보려면:

```bash
python -m src.db.check_migration
```

## 4단계 — 데이터 채우기

컬럼만 만들면 값은 비어 있다. 수집기를 한 번 돌린다:

```bash
# 발표 전 5일·당일 수익률 계산 (KIS 일봉을 다시 읽어 전 시점을 재계산한다)
python -m src.analysis.outcome_run --save

# (섹터 컬럼을 만든 경우에만)
python -m src.universe.sector_map --save
```

---

## 문제가 생기면

| 증상 | 원인 | 대처 |
|---|---|---|
| `permission denied for table` | SQL Editor가 아닌 곳에서 실행 | SQL Editor는 관리자 권한으로 돈다. 거기서 실행하라 |
| `relation "outcome_tracking" does not exist` | 다른 프로젝트를 골랐다 | 프로젝트 ref를 다시 확인 |
| 실행은 됐는데 화면이 안 바뀐다 | 스키마 캐시 | 1~2분 뒤 다시 보라. PostgREST가 스키마를 캐시한다 |
| 화면이 계속 옛 숫자 | **아니다** — `no-store`로 막아 뒀다(T59) | DB를 직접 확인하라 |

## 적용하지 않으면 어떻게 되나

**아무것도 깨지지 않는다.** 설계상 그렇게 만들어 뒀다:

- 조회는 없는 컬럼을 걷어내고 진행한다(`selectWithOptionalColumns`)
- 쓰기도 없는 컬럼을 빼고 저장하며 **빠뜨렸다는 사실을 출력한다**(T62)
- 화면은 `—`로 표시하고 "0이 아니라 미수집"임을 밝힌다

즉 **발표 전 5일·당일 열만 비어 있고** 나머지는 전부 정상 동작한다.
