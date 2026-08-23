-- PRD Ref: §6 (DB 스키마) · 부록 A
-- Heimdallr_Call — Supabase 신규 프로젝트 전용 스키마
--
-- ★ 이 파일은 Supabase REST로 실행할 수 없는 DDL이다.
--   Supabase 대시보드 → SQL Editor 에 통째로 붙여넣어 실행할 것.
--   실행 순서와 체크리스트는 README.md 참조.
--
-- ★ 실행 전 확인: 지금 열려 있는 Supabase 프로젝트 ref가 HermesCall이 아닌
--   Heimdallr 신규 프로젝트인가? (ADR 8 · traps.md T16)
--   HermesCall에 이 스키마를 적용하면 분리 이유가 통째로 무너진다.
--
-- idempotent — 몇 번 실행해도 안전하다. 컬럼 추가 시 파일 하단의
-- "증분 마이그레이션" 절에 ALTER ... ADD COLUMN IF NOT EXISTS로 덧붙이고
-- 다시 통째로 실행하면 된다.

-- ═══════════════════════════════════════════════════════════════════
-- L0: 유니버스
-- 앵커는 code(6자리). watchlist 개념은 없다 — 대상이 "등록된 종목"이 아니라
-- "시총 하한을 넘는 전 종목"이기 때문이다.
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS krx_universe (
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
CREATE INDEX IF NOT EXISTS krx_universe_corp_code_idx ON krx_universe (corp_code);
CREATE INDEX IF NOT EXISTS krx_universe_market_cap_idx ON krx_universe (market_cap_krw DESC);

-- ═══════════════════════════════════════════════════════════════════
-- L2: 분기 재무 (핵심)
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS quarterly_fundamentals (
  code TEXT NOT NULL,
  fiscal_year INT NOT NULL,
  fiscal_quarter INT NOT NULL,              -- 1~4 (회계분기)
  fs_div TEXT NOT NULL,                     -- 'CFS' | 'OFS' (종목별 고정 — T2)
  -- 손익
  revenue NUMERIC, gross_profit NUMERIC, op NUMERIC,
  np NUMERIC, np_ctrl NUMERIC, eps NUMERIC,
  -- 성장률 (부호 전환 시 NULL + status_label — T12)
  revenue_yoy NUMERIC, revenue_qoq NUMERIC,
  op_yoy NUMERIC, op_qoq NUMERIC, np_yoy NUMERIC, eps_yoy NUMERIC,
  op_status_label TEXT,                     -- '흑전'|'적전'|'적자축소'|'적자확대'|NULL
  -- 마진
  opm NUMERIC, opm_yoy_delta NUMERIC, opm_qoq_delta NUMERIC,
  gpm NUMERIC, npm NUMERIC,
  -- TTM (계절성 제거용) ★ v2 신설. 4개 분기가 전부 있을 때만 계산 — 결측을 0으로 채우지 말 것
  ttm_revenue NUMERIC, ttm_op NUMERIC, ttm_opm NUMERIC, ttm_cfo NUMERIC,
  ttm_revenue_qoq NUMERIC, ttm_opm_delta NUMERIC,
  -- 2년 스택 (기저효과 방어) ★ v2 신설
  rev_2y_stack NUMERIC,
  -- 현금흐름·재무상태 (L2" — 게이트 통과 종목만)
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
CREATE INDEX IF NOT EXISTS quarterly_fundamentals_period_idx
  ON quarterly_fundamentals (fiscal_year DESC, fiscal_quarter DESC);

-- ═══════════════════════════════════════════════════════════════════
-- L3: 컨센서스 사전 스냅샷
-- 발표 후에는 (E)가 실적치로 덮여 사라지므로 미리 저장해야 한다 (T17)
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS consensus_snapshots (
  code TEXT NOT NULL,
  fiscal_year INT NOT NULL, fiscal_quarter INT NOT NULL,
  revenue_est NUMERIC, op_est NUMERIC, np_est NUMERIC, eps_est NUMERIC,
  n_estimates INT,                          -- < 2면 컨센서스로 인정하지 않음
  source TEXT,                              -- 'fnguide' | 'naver'
  snapshot_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (code, fiscal_year, fiscal_quarter, snapshot_at)
);

-- ═══════════════════════════════════════════════════════════════════
-- L1: 공시 이벤트
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS earnings_disclosures (
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
CREATE INDEX IF NOT EXISTS earnings_disclosures_code_idx
  ON earnings_disclosures (code, disclosed_at DESC);

-- ═══════════════════════════════════════════════════════════════════
-- L4: 시세 스냅샷
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS price_snapshots (
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

-- 분기말 종가 — 상세화면의 9분기 차트에 주가를 겹쳐 그리는 데 쓴다.
-- ★ price_snapshots는 '오늘의 스냅샷'이라 과거를 알 수 없다(실측 2일치뿐).
--   분기별 주가는 별도로 채워야 한다 — 네이버 일봉 1콜로 2.5년치가 온다.
CREATE TABLE IF NOT EXISTS quarter_prices (
  code TEXT NOT NULL, fiscal_year INT NOT NULL, fiscal_quarter INT NOT NULL,
  close NUMERIC,                            -- 그 분기 **마지막 거래일** 종가
  trade_date DATE,                          -- 실제로 어느 날 종가인지 (휴장일 보정 확인용)
  refreshed_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (code, fiscal_year, fiscal_quarter)
);

CREATE TABLE IF NOT EXISTS index_snapshots (   -- 상대수익률 계산용
  index_name TEXT NOT NULL,                    -- 'KOSPI' | 'KOSDAQ'
  snap_date DATE NOT NULL, close NUMERIC,
  PRIMARY KEY (index_name, snap_date)
);

-- ═══════════════════════════════════════════════════════════════════
-- L5: 스크리닝 결과
-- raw_* 를 전부 저장해야 나중에 가중치를 바꿔 재계산할 수 있다 (검토 ⑥)
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS screen_results (
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
  has_consensus BOOLEAN,                    -- ★ SC6 감시용 — 반드시 채운다
  pctile_in_quarter NUMERIC,                -- 분기 내 백분위
  -- 주가반영도 (스코어에 합산하지 않는다 — ADR 5)
  pri NUMERIC, pri_detail JSONB,
  -- 최종 분류
  grade TEXT,                               -- '★'|'○'|'△'|'·'|'✕'
  computed_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (code, fiscal_year, fiscal_quarter)
);
CREATE INDEX IF NOT EXISTS screen_results_rank_idx
  ON screen_results (fiscal_year DESC, fiscal_quarter DESC, score_flash DESC);

-- ═══════════════════════════════════════════════════════════════════
-- L6: LLM 분석
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS analyses (
  id BIGSERIAL PRIMARY KEY,
  code TEXT NOT NULL, fiscal_year INT, fiscal_quarter INT,
  model TEXT, cost_usd NUMERIC,
  payload JSONB,                            -- §7.2 스키마 (부분 채움 가능 — T18)
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE (code, fiscal_year, fiscal_quarter)
);

-- ═══════════════════════════════════════════════════════════════════
-- 정기보고서 발췌 — LLM 입력용 (2026-08-23 신설)
-- ★ 원문 XML은 3.5MB이고 1건 받는 데 ~30초 걸린다. 분석 때마다 받으면
--   269종목 배치에 2시간이 더 붙는다 → **미리 받아 저장**해 두고 읽어 쓴다.
-- ★ 발췌만 저장한다(원문 아님). 예산 안에서 자른 결과라 행이 가볍다.
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS disclosure_excerpts (
  rcept_no TEXT PRIMARY KEY,                -- DART 접수번호. 원문의 유일한 열쇠(T58)
  code TEXT NOT NULL, fiscal_year INT, fiscal_quarter INT,
  sections JSONB,                           -- {절 이름: 본문} — 부분 채움 가능
  excerpt_chars INT,                        -- 실제로 담은 길이
  full_chars INT,                           -- 원문 길이. 얼마나 잘랐는지 밝히기 위해
  fetched_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_excerpt_code_quarter
  ON disclosure_excerpts (code, fiscal_year, fiscal_quarter);

-- ═══════════════════════════════════════════════════════════════════
-- L7: 결과 추적 ★ v2 신설 — 이게 없으면 시스템을 검증할 수 없다
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS outcome_tracking (
  code TEXT NOT NULL, fiscal_year INT NOT NULL, fiscal_quarter INT NOT NULL,
  announce_date DATE,
  grade_at_announce TEXT, score_at_announce NUMERIC, pri_at_announce NUMERIC,
  ret_d1 NUMERIC, ret_d5 NUMERIC, ret_d20 NUMERIC, ret_d60 NUMERIC,
  excess_d1 NUMERIC, excess_d5 NUMERIC, excess_d20 NUMERIC, excess_d60 NUMERIC,
  updated_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (code, fiscal_year, fiscal_quarter)
);

-- ═══════════════════════════════════════════════════════════════════
-- 운영
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS notifications (
  id BIGSERIAL PRIMARY KEY,
  code TEXT, kind TEXT,                     -- 'flash'|'daily'|'budget'|'upgrade'
  fiscal_year INT, fiscal_quarter INT,
  sent_at TIMESTAMPTZ DEFAULT now(), payload JSONB,
  UNIQUE (code, fiscal_year, fiscal_quarter, kind)   -- ★ 중복 발송 차단 (SC4)
);

CREATE TABLE IF NOT EXISTS cost_log (
  id BIGSERIAL PRIMARY KEY, model TEXT,
  input_tokens INT, cache_write_tokens INT, cached_tokens INT, output_tokens INT,
  cost_usd NUMERIC,
  env TEXT DEFAULT 'prod',                  -- ★ 개발 실행이 운영 상한을 먹지 않도록
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS cost_log_env_created_idx ON cost_log (env, created_at DESC);

-- ═══════════════════════════════════════════════════════════════════
-- RLS — 전 테이블 ENABLE, cost_log 제외 anon SELECT
-- 쓰기는 service_role(서버사이드)만. service_role은 RLS를 우회한다.
-- cost_log에는 anon 정책을 주지 않는다 → 대시보드에서 비용을 읽으려면
-- 서버사이드 라우트를 경유해야 한다.
-- ※ Supabase 신규 프로젝트의 publishable 키(sb_publishable_...)는 anon과
--   동일한 저권한이므로 아래 `TO anon` 정책이 그대로 적용된다 (T16).
-- ═══════════════════════════════════════════════════════════════════
ALTER TABLE krx_universe            ENABLE ROW LEVEL SECURITY;
ALTER TABLE quarterly_fundamentals  ENABLE ROW LEVEL SECURITY;
ALTER TABLE consensus_snapshots     ENABLE ROW LEVEL SECURITY;
ALTER TABLE earnings_disclosures    ENABLE ROW LEVEL SECURITY;
ALTER TABLE price_snapshots         ENABLE ROW LEVEL SECURITY;
ALTER TABLE quarter_prices          ENABLE ROW LEVEL SECURITY;
ALTER TABLE index_snapshots         ENABLE ROW LEVEL SECURITY;
ALTER TABLE screen_results          ENABLE ROW LEVEL SECURITY;
ALTER TABLE disclosure_excerpts     ENABLE ROW LEVEL SECURITY;
ALTER TABLE analyses                ENABLE ROW LEVEL SECURITY;
ALTER TABLE outcome_tracking        ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications           ENABLE ROW LEVEL SECURITY;
ALTER TABLE cost_log                ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS anon_select_krx_universe ON krx_universe;
CREATE POLICY anon_select_krx_universe ON krx_universe
  FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS anon_select_disclosure_excerpts ON disclosure_excerpts;
CREATE POLICY anon_select_disclosure_excerpts ON disclosure_excerpts
  FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS anon_select_quarterly_fundamentals ON quarterly_fundamentals;
CREATE POLICY anon_select_quarterly_fundamentals ON quarterly_fundamentals
  FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS anon_select_consensus_snapshots ON consensus_snapshots;
CREATE POLICY anon_select_consensus_snapshots ON consensus_snapshots
  FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS anon_select_earnings_disclosures ON earnings_disclosures;
CREATE POLICY anon_select_earnings_disclosures ON earnings_disclosures
  FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS anon_select_price_snapshots ON price_snapshots;
CREATE POLICY anon_select_price_snapshots ON price_snapshots
  FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS anon_select_quarter_prices ON quarter_prices;
CREATE POLICY anon_select_quarter_prices ON quarter_prices
  FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS anon_select_index_snapshots ON index_snapshots;
CREATE POLICY anon_select_index_snapshots ON index_snapshots
  FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS anon_select_screen_results ON screen_results;
CREATE POLICY anon_select_screen_results ON screen_results
  FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS anon_select_analyses ON analyses;
CREATE POLICY anon_select_analyses ON analyses
  FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS anon_select_outcome_tracking ON outcome_tracking;
CREATE POLICY anon_select_outcome_tracking ON outcome_tracking
  FOR SELECT TO anon USING (true);

DROP POLICY IF EXISTS anon_select_notifications ON notifications;
CREATE POLICY anon_select_notifications ON notifications
  FOR SELECT TO anon USING (true);

-- cost_log: anon 정책 없음 (의도적). RLS만 켜 두면 anon은 0행을 본다.

-- ═══════════════════════════════════════════════════════════════════
-- 증분 마이그레이션 — 이후 Phase에서 컬럼을 추가할 때 여기에 덧붙인다.
-- (CREATE TABLE IF NOT EXISTS는 기존 테이블에 컬럼을 더해 주지 않는다.
--  적용 전까지 쓰기는 PGRST204, 조회는 42703으로 죽는다 — T18)
-- 예)
-- ALTER TABLE quarterly_fundamentals ADD COLUMN IF NOT EXISTS new_col NUMERIC;
-- ═══════════════════════════════════════════════════════════════════

-- 2026-08-17 — 발굴 목록의 '최근 5일 주가 상승률' 열
ALTER TABLE price_snapshots ADD COLUMN IF NOT EXISTS ret_5d NUMERIC;

-- 2026-08-17 (2) — 투자 섹터 분류 (`src/universe/sector_map.py`)
--   KRX 업종명은 투자에 쓰는 말이 아니다('특수 목적용 기계 제조업' 93종목).
ALTER TABLE krx_universe ADD COLUMN IF NOT EXISTS sector TEXT;
CREATE INDEX IF NOT EXISTS krx_universe_sector_idx ON krx_universe (sector);

-- 2026-08-17 (3) — 결과 추적에 **발표 전 5일**과 **발표 당일**을 추가
--   ★ 음수 시점은 컬럼명에 '-'를 쓸 수 없어 `m`으로 적는다 (ret_dm5).
ALTER TABLE outcome_tracking ADD COLUMN IF NOT EXISTS ret_dm5 NUMERIC;
ALTER TABLE outcome_tracking ADD COLUMN IF NOT EXISTS excess_dm5 NUMERIC;
ALTER TABLE outcome_tracking ADD COLUMN IF NOT EXISTS ret_d0 NUMERIC;
ALTER TABLE outcome_tracking ADD COLUMN IF NOT EXISTS excess_d0 NUMERIC;
