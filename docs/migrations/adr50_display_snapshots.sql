-- PRD Ref: §9/10 · ADR50. Separate daily dynamic data from button-approved fixed content.
create table if not exists public.stock_analysis_snapshots (
 code text primary key references public.krx_universe(code),
 payload jsonb not null,
 analyzed_at timestamptz not null default now()
);
alter table public.stock_analysis_snapshots enable row level security;
revoke all on public.stock_analysis_snapshots from anon,authenticated;
grant all on public.stock_analysis_snapshots to service_role;
create table if not exists public.daily_indicator_details (
 code text primary key references public.krx_universe(code),
 snap_date date not null,
 payload jsonb not null,
 checked_at timestamptz not null default now()
);
alter table public.daily_indicator_details enable row level security;
revoke all on public.daily_indicator_details from anon,authenticated;
grant all on public.daily_indicator_details to service_role;

-- One-time deployment baseline preserves the currently displayed public facts.
-- Subsequent changes are published only by the Pro button worker, never by collectors.
with funds as (select code,jsonb_agg(to_jsonb(q) order by fiscal_year,fiscal_quarter) as rows
 from public.quarterly_fundamentals q group by code),
excerpts as (select code,jsonb_agg(to_jsonb(e) order by rcept_no desc) as rows
 from public.disclosure_excerpts e group by code)
insert into public.stock_analysis_snapshots(code,payload)
select u.code,jsonb_build_object('fundamentals',coalesce(f.rows,'[]'::jsonb),
 'excerpts',coalesce(e.rows,'[]'::jsonb),'company_info',jsonb_build_object('name',u.name,'industry',u.industry,'products',to_jsonb(u)->'products'),
 'baseline',true) from public.krx_universe u left join funds f using(code) left join excerpts e using(code)
on conflict(code) do nothing;
notify pgrst,'reload schema';
