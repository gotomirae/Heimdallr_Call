-- PRD Ref: §10 · traps.md T23, T217, T229 · cron_dispatch.sql 다음에 실행
-- universe_daily.yml 정시 시작 = pg_cron → workflow_dispatch (daily_digest 와 같은 방식).
-- GitHub schedule 은 06:00 KST 예약이 08:41~09:51 에 시작했다(9/28~10/2) — 장중이라 시세가 장중가로 저장됐다(T217).
--
-- ▶ 실행: Heimdallr Supabase SQL Editor 에서 전체 실행. 토큰 치환 없음(cron_dispatch.sql 의 Vault 토큰·함수를 쓴다).
--   재실행 안전. 확인:
--     select jobname, schedule, active from cron.job where jobname like 'heimdallr-%' order by 1;
--     select * from public.job_runs order by run_day desc limit 5;   -- 첫 완료 후 행이 생긴다
--
-- 스케줄(UTC, 매일):
--   06:00 KST = 21:00 UTC(전날) — 정시
--   16:30 KST = 07:30 UTC        — 보충: 아침 실행이 실패·생략됐을 때만 돈다(확정 종가 · 이미 완료면 게이트에서 끝)
-- 워크플로 게이트는 평일 07:25~16:00 KST 시작을 거부한다(제한시간 안에 장중에 걸리면 장중가가 종가로 저장된다).

-- ① 실행 완료 표식 (service_role 만 쓴다. anon 정책 없음 — RLS 만 켜 두면 anon 은 0행)
create table if not exists public.job_runs (
  job text not null,
  run_day date not null,                 -- KST 날짜
  status text not null,                  -- 'complete'
  finished_at timestamptz not null default now(),
  detail jsonb,
  primary key (job, run_day)
);
alter table public.job_runs enable row level security;

-- ② 스케줄
select cron.unschedule(jobid) from cron.job where jobname like 'heimdallr-universe-%';
select cron.schedule('heimdallr-universe-0600', '0 21 * * *',
  $$select heimdallr_ops.dispatch_workflow('universe_daily.yml', '{"trigger": "pg_cron 06:00"}')$$);
select cron.schedule('heimdallr-universe-1630', '30 7 * * *',
  $$select heimdallr_ops.dispatch_workflow('universe_daily.yml', '{"trigger": "pg_cron 16:30"}')$$);
