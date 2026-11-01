-- PRD Ref: §7/9/10 · ADR50. Service role only; browsers never write directly.
create table if not exists public.pro_analysis_jobs (
 id uuid primary key default gen_random_uuid(),
 request_key text not null unique,
 kind text not null check(kind in ('company','industry','market','strategy')),
 target text not null,
 fiscal_year integer,
 fiscal_quarter integer check(fiscal_quarter between 1 and 4),
 historical boolean not null default false,
 force_analysis boolean not null default false,
 status text not null default 'pending' check(status in ('pending','working','deferred','completed','failed')),
 requested_at timestamptz not null default now(),
 claimed_at timestamptz,
 completed_at timestamptz,
 retry_after timestamptz,
 error text,
 evidence_hash text,
 result jsonb
);
alter table public.pro_analysis_jobs enable row level security;
revoke all on public.pro_analysis_jobs from anon, authenticated;
grant all on public.pro_analysis_jobs to service_role;
create index if not exists pro_analysis_jobs_pending on public.pro_analysis_jobs(status,historical,requested_at);

-- Same date/target must not have two pending or working executions. API and worker
-- also use compare-and-set, and the local CLI has a cross-queue execution mutex.
create or replace function public.pro_enqueue_analysis(p_request jsonb)
returns jsonb language plpgsql security definer set search_path=public as $$
declare old public.pro_analysis_jobs; answer public.pro_analysis_jobs;
begin
 perform pg_advisory_xact_lock(hashtext('heimdallr-pro-analysis-enqueue'));
 select * into old from public.pro_analysis_jobs where request_key=p_request->>'request_key' for update;
 if found and old.status in ('pending','working','deferred') then
   if old.historical and not coalesce((p_request->>'historical')::boolean,false) then
     update public.pro_analysis_jobs set historical=false where id=old.id returning * into old;
   end if;
   return to_jsonb(old);
 end if;
 if not coalesce((p_request->>'historical')::boolean,false)
    and (select count(*) from public.pro_analysis_jobs where not historical and requested_at >= now()-interval '24 hours')
       >= (p_request->>'daily_limit')::integer then raise exception 'DAILY_REQUEST_LIMIT'; end if;
 insert into public.pro_analysis_jobs(request_key,kind,target,fiscal_year,fiscal_quarter,historical,force_analysis)
 values(p_request->>'request_key',p_request->>'kind',p_request->>'target',
   (p_request->>'fiscal_year')::integer,(p_request->>'fiscal_quarter')::integer,
   coalesce((p_request->>'historical')::boolean,false),coalesce((p_request->>'force_analysis')::boolean,false))
 on conflict(request_key) do update set status='pending',requested_at=now(),claimed_at=null,
 completed_at=null,retry_after=null,error=null,force_analysis=excluded.force_analysis,historical=excluded.historical
 returning * into answer;
 -- Keep previous validated result until the replacement has passed validation.
 return to_jsonb(answer);
end $$;
revoke all on function public.pro_enqueue_analysis(jsonb) from public,anon,authenticated;
grant execute on function public.pro_enqueue_analysis(jsonb) to service_role;
notify pgrst, 'reload schema';
