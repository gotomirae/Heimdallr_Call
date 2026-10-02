-- PRD Ref: §8.8 · JARVIS INTEGRATION_TASKS B-1·B-10·B-11
-- Heimdallr Supabase(ref drpxciqkbjlruximqbox) SQL Editor에서 한 번 실행한다.
-- 전부 IF NOT EXISTS · 정책 존재 검사로 감싸 있어 **재실행해도 안전하다(멱등).**
-- 실행 후 확인: python -m src.db.check_anon   (anon 키로 대상 테이블 SELECT 대조)

-- ═══ 1. entry_checks — JARVIS 국내 M1·M2·M5 판정 (통과·탈락 모두 저장) ═══
CREATE TABLE IF NOT EXISTS public.entry_checks (
  code TEXT NOT NULL,
  check_date DATE NOT NULL,                 -- KR 거래일(확정 종가 기준일)
  fiscal_year INT,                          -- M1이 본 평가 분기
  fiscal_quarter INT,
  m1_pass BOOLEAN,                          -- NULL = 판정 불가(데이터 없음) · FALSE와 구분
  m1_detail JSONB,                          -- rev_yoy[t,t-1] · op_yoy[t,t-1] · op_positive · ttm_rev_growth ·
                                            -- ttm_op_growth · annual_consensus_ok(null=데이터없음) ·
                                            -- base_effect_warning · drawdown_from_post_earnings_high ·
                                            -- drawdown_from_52w_high · range_20d_pct · ret_20d_pct · pri ·
                                            -- price_state('PB'|'SW'|null) · checks · notes
  m2_pass BOOLEAN,
  m2_detail JSONB,                          -- macd · signal · hist[-3..0] · gap_pct_of_close ·
                                            -- projected_bars · cross_today · state
  m5_pass BOOLEAN,
  m5_detail JSONB,                          -- foreign_net[-3..0] · inst_net[-3..0] ·
                                            -- path('foreign'|'institution'|'combined') · streak_days · source
  invalidation_price NUMERIC,               -- PB → low_10d · SW → low_20d
  low_10d NUMERIC,
  low_20d NUMERIC,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (code, check_date)
);
CREATE INDEX IF NOT EXISTS entry_checks_date_idx ON public.entry_checks (check_date DESC);
CREATE INDEX IF NOT EXISTS entry_checks_pass_idx
  ON public.entry_checks (check_date DESC) WHERE m1_pass AND m2_pass;

-- ═══ 2. krx_universe.industry_l1 — JARVIS 노션 L1 코드(복수 가능, 예: {1a,1b}) ═══
ALTER TABLE public.krx_universe ADD COLUMN IF NOT EXISTS industry_l1 TEXT[];
ALTER TABLE public.krx_universe ADD COLUMN IF NOT EXISTS industry_l1_source TEXT;  -- 'jarvis_api'|'static'

-- ═══ 3. anon SELECT — JARVIS가 읽는 테이블 (B-11) ═══
-- 쓰기는 service_role 서버사이드만. 이미 anon/public SELECT 정책이 있으면 건드리지 않는다.
DO $$
DECLARE
  t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'screen_results', 'price_snapshots', 'quarterly_fundamentals', 'consensus_snapshots',
    'notifications', 'analyses', 'outcome_tracking', 'krx_universe', 'index_snapshots',
    'entry_checks'
  ] LOOP
    IF to_regclass('public.' || t) IS NULL THEN
      RAISE NOTICE '테이블 없음(건너뜀): %', t;
      CONTINUE;
    END IF;
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('GRANT SELECT ON public.%I TO anon', t);
    IF NOT EXISTS (
      SELECT 1 FROM pg_policies
      WHERE schemaname = 'public' AND tablename = t
        AND cmd IN ('SELECT', 'ALL')
        AND (roles && ARRAY['anon', 'public']::name[])
    ) THEN
      EXECUTE format(
        'CREATE POLICY %I ON public.%I FOR SELECT TO anon USING (true)',
        t || '_anon_select', t
      );
    END IF;
  END LOOP;
END $$;

-- notifications.kind 값: 'flash'|'daily'|'budget'|'upgrade'|'technical_setup'|'earnings_breakout'
-- (자유 TEXT라 DDL 변경 없음. earnings_breakout은 🔵 K1 — 진입 신호 아님.)
