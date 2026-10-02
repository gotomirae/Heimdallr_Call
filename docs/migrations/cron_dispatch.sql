-- PRD Ref: §10 · traps.md T228 · JARVIS INTEGRATION_TASKS F (D7·D50)
-- 일일 요약(daily_digest.yml) 정시 시작 = Supabase pg_cron → GitHub workflow_dispatch.
-- GitHub schedule 은 실측 7시간 지연(10/1 17:37 실행분이 00:37 시작, 10/2 는 18:05 까지 미시작)이라
-- entry_checks 가 JARVIS 19:10 판정에 늦고, JARVIS 는 '원천 지연'으로 🟢 를 만들지 않았다(D50).
-- daily_digest.yml 의 schedule 은 이 잡들의 **30분 뒤 예비**로만 남는다. 둘 다 돌아도 결과는 한 번이다
-- (워크플로 첫 스텝 게이트 · entry_checks upsert · 요약 digest_date 1일 1회 · K1 중복키).
--
-- ▶ 실행 방법 (사용자, Heimdallr Supabase(ref drpxciqkbjlruximqbox) 대시보드 SQL Editor 에서만 — Vault 권한)
--   1) GitHub → Settings → Developer settings → Fine-grained personal access tokens → Generate new token
--      Repository access: Only select repositories → gotomirae/Heimdallr_Call
--      Permissions: Repository → Actions: Read and write   (다른 권한 불필요)
--   2) 아래 ③ 의 'GITHUB_TOKEN_HERE' 를 **편집기 안에서만** 그 토큰으로 바꿔 전체 실행.
--      이 파일에 토큰을 적어 저장·커밋하지 말 것(공개 저장소). 재실행 안전 — 토큰 교체도 이 파일로 한다.
--   3) 확인:
--        select jobname, schedule, active from cron.job where jobname like 'heimdallr-%' order by 1;
--        select status_code, created from net._http_response order by created desc limit 5;   -- 204 = 성공
--      즉시 시험(선택 · dry_run 이라 텔레그램·DB 쓰기 없음 — Actions 탭에 'sql test' 실행이 생기면 성공):
--        select heimdallr_ops.dispatch_workflow('daily_digest.yml', '{"trigger": "sql test", "dry_run": "true"}');
--      응답 해석: 204 성공 · 401 토큰 오류/만료 · 403/404 토큰 권한·저장소 범위 · 422 ref 또는 inputs 불일치
--
-- pg_cron 은 UTC 기준이다(KST = UTC+9). 평일(월~금)만 — 휴장일엔 entry_checks 가 직전 거래일로 계산된다.

-- ① 확장
create extension if not exists pg_cron;
create extension if not exists pg_net;

-- ② 실행 함수는 API(PostgREST)에 노출되지 않는 전용 스키마에 둔다.
--    public 에 두면 anon 이 /rest/v1/rpc 로 워크플로를 마음대로 띄울 수 있다(Supabase 기본 권한).
create schema if not exists heimdallr_ops;
revoke all on schema heimdallr_ops from public, anon, authenticated;

-- ③ workflow_dispatch 호출 (토큰은 Vault 에서 읽는다). inputs 는 워크플로에 **선언된 키만** — 아니면 422.
create or replace function heimdallr_ops.dispatch_workflow(workflow text, inputs jsonb default '{}'::jsonb)
returns bigint
language plpgsql
security definer
set search_path = heimdallr_ops, public, extensions
as $$
declare
  tok text;
  rid bigint;
begin
  if workflow !~ '^[a-z0-9_]+\.yml$' then
    raise exception 'workflow 파일명 형식 오류: %', workflow;
  end if;
  select decrypted_secret into tok from vault.decrypted_secrets
   where name = 'heimdallr_github_dispatch_token' limit 1;
  if tok is null or tok = 'GITHUB_TOKEN_HERE' then
    raise warning 'heimdallr_github_dispatch_token 이 Vault 에 없거나 자리표시자 그대로다';
    return null;
  end if;
  select net.http_post(
    url := 'https://api.github.com/repos/gotomirae/Heimdallr_Call/actions/workflows/' || workflow || '/dispatches',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || tok,
      'Accept', 'application/vnd.github+json',
      'X-GitHub-Api-Version', '2022-11-28',
      'User-Agent', 'heimdallr-pg-cron',
      'Content-Type', 'application/json'
    ),
    body := jsonb_build_object('ref', 'main', 'inputs', coalesce(inputs, '{}'::jsonb))
  ) into rid;
  return rid;
end;
$$;
revoke all on function heimdallr_ops.dispatch_workflow(text, jsonb) from public, anon, authenticated;

-- ④ 토큰 저장 (이미 있으면 교체). 'GITHUB_TOKEN_HERE' 를 편집기 안에서만 실제 토큰으로 바꿔 실행
do $$
declare sid uuid;
begin
  select id into sid from vault.secrets where name = 'heimdallr_github_dispatch_token';
  if sid is null then
    perform vault.create_secret(
      'GITHUB_TOKEN_HERE', 'heimdallr_github_dispatch_token',
      'GitHub fine-grained PAT (gotomirae/Heimdallr_Call · Actions RW) — pg_cron 정시 시작 (T228)'
    );
  else
    perform vault.update_secret(sid, 'GITHUB_TOKEN_HERE');
  end if;
end $$;

-- ⑤ 스케줄 — 장 마감 후 1차 + 재시도 2회(평일). 앞 실행이 완료됐으면 워크플로 게이트에서 바로 끝난다.
--    17:37 KST = 08:37 UTC · 18:17 KST = 09:17 UTC · 19:07 KST = 10:07 UTC (JARVIS 판정 19:10 전)
select cron.unschedule(jobid) from cron.job where jobname like 'heimdallr-digest-%';
select cron.schedule('heimdallr-digest-1737', '37 8 * * 1-5',
  $$select heimdallr_ops.dispatch_workflow('daily_digest.yml', '{"trigger": "pg_cron 17:37"}')$$);
select cron.schedule('heimdallr-digest-1817', '17 9 * * 1-5',
  $$select heimdallr_ops.dispatch_workflow('daily_digest.yml', '{"trigger": "pg_cron 18:17"}')$$);
select cron.schedule('heimdallr-digest-1907', '7 10 * * 1-5',
  $$select heimdallr_ops.dispatch_workflow('daily_digest.yml', '{"trigger": "pg_cron 19:07"}')$$);
