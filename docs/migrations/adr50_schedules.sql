-- PRD Ref: §10 · ADR50. Apply after cron_dispatch.sql and pro_analysis_jobs.sql.
-- The durable Python gates also exclude Korean holidays and suppress duplicate dispatch.
select cron.unschedule(jobid) from cron.job
where jobname like 'heimdallr-universe-%' or jobname like 'heimdallr-digest-%'
   or jobname in ('heimdallr-indicators-1600','heimdallr-disclosure-2h');
select cron.schedule('heimdallr-indicators-1600','0 7 * * 1-5',
  $$select heimdallr_ops.dispatch_workflow('universe_daily.yml','{"trigger":"pg_cron 16:00"}')$$);
select cron.schedule('heimdallr-disclosure-2h','0 1-23/2 * * *',
  $$select heimdallr_ops.dispatch_workflow('disclosure_poll.yml','{}')$$);
