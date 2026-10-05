-- PRD Ref: §8.7 H. Apply after kairos_jarvis.sql. No historical sent backfill.
BEGIN;
ALTER TABLE public.kairos_deck_requests
 ADD COLUMN IF NOT EXISTS mode text NOT NULL DEFAULT 'deck',
 ADD COLUMN IF NOT EXISTS analysis_md text,
 ADD COLUMN IF NOT EXISTS top_pick jsonb;
ALTER TABLE public.kairos_deck_requests DROP CONSTRAINT IF EXISTS kairos_deck_requests_mode_check;
ALTER TABLE public.kairos_deck_requests ADD CONSTRAINT kairos_deck_requests_mode_check CHECK (mode IN ('analysis','deck'));
DROP INDEX IF EXISTS public.kairos_deck_open_idx;
CREATE UNIQUE INDEX kairos_deck_open_idx ON public.kairos_deck_requests(request_id,mode)
 WHERE status IN ('pending','working','sent');
-- Keep kairos_deck_single_worker_idx: both modes share one Claude process.
CREATE OR REPLACE FUNCTION public._kairos_claude_status(p_request_id bigint) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT jsonb_build_object('status',status,'notion_url',notion_url,'error',error,'top_pick',top_pick)
 FROM public.kairos_deck_requests WHERE request_id=p_request_id AND mode='analysis' ORDER BY id DESC LIMIT 1;
$$;
CREATE OR REPLACE FUNCTION public.kairos_queue_claude_analysis() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
BEGIN
 IF NEW.source='jarvis' AND NEW.status='sent' AND OLD.status IS DISTINCT FROM 'sent' THEN
  INSERT INTO public.kairos_deck_requests(request_id,mode) VALUES(NEW.update_id,'analysis') ON CONFLICT DO NOTHING;
 END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS kairos_sent_claude_analysis ON public.kairos_requests;
CREATE TRIGGER kairos_sent_claude_analysis AFTER UPDATE OF status ON public.kairos_requests
 FOR EACH ROW EXECUTE FUNCTION public.kairos_queue_claude_analysis();
CREATE OR REPLACE FUNCTION public.jarvis_request_analysis(p_token text,p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
#variable_conflict use_variable
DECLARE kind text:=p_payload->>'kind'; market text; identity text;
 target text:=trim(p_payload->>'target_name'); folder text; after_at timestamptz;
 r public.kairos_requests%ROWTYPE; us public.kairos_us_companies%ROWTYPE; new_id bigint;
BEGIN
 IF NOT public._jarvis_ok(p_token) THEN RAISE EXCEPTION 'unauthorized'; END IF;
 IF kind IS NULL OR kind NOT IN ('company','industry') OR target IS NULL OR target='' OR length(target)>200 THEN
  RETURN jsonb_build_object('status','rejected','reason','빈 이름 또는 잘못된 대상'); END IF;
 market:=coalesce(nullif(upper(p_payload->>'market'),''),'KR');
 identity:=upper(trim(p_payload->>'code'));
 IF market NOT IN ('KR','US') THEN RETURN jsonb_build_object('status','rejected','reason','지원하지 않는 시장'); END IF;
 IF kind='industry' THEN
  SELECT folder_name INTO folder FROM public.kairos_industry_folders
   WHERE alias_key=public._kairos_folder_key(target);
  -- Unmapped nonempty industry is allowed; worker allocates next folder number.
  folder:=coalesce(folder,target);
 ELSE
  IF market='KR' THEN
   SELECT name INTO target FROM public.krx_universe WHERE code=identity;
   IF target IS NULL THEN RETURN jsonb_build_object('status','rejected','reason','국내 코드 미등록'); END IF;
  ELSE
   SELECT * INTO us FROM public.kairos_us_companies WHERE ticker=identity AND verified_at>=now()-interval '2 days';
   IF us.ticker IS NULL THEN RETURN jsonb_build_object('status','rejected','reason','미국 티커 미확인 — SEC 명부 갱신 필요'); END IF;
   target:=us.name;
  END IF;
 END IF;
 BEGIN
  after_at:=greatest(now()-interval '30 days',coalesce((p_payload->>'reuse_after')::timestamptz,now()-interval '30 days'));
 EXCEPTION WHEN invalid_datetime_format OR datetime_field_overflow THEN
  RETURN jsonb_build_object('status','rejected','reason','reuse_after 형식 오류');
 END;
 -- Global transaction lock makes dedup and the six-request budget atomic.
 PERFORM pg_advisory_xact_lock(8933940541);
 SELECT * INTO r FROM public.kairos_requests q WHERE q.request_kind=kind AND
 ((kind='company' AND q.market=market AND coalesce(q.code,q.ticker)=identity) OR
  (kind='industry' AND public._kairos_folder_key(coalesce(q.drive_folder_name,(SELECT f.folder_name FROM public.kairos_industry_folders f WHERE f.alias_key=public._kairos_folder_key(q.industry)),q.industry))=public._kairos_folder_key(folder)))
 AND q.status IN ('pending','working','awaiting_input','sending') ORDER BY q.created_at LIMIT 1;
 IF r.update_id IS NOT NULL THEN RETURN jsonb_build_object('status','in_progress','request_id',r.update_id); END IF;
 SELECT * INTO r FROM public.kairos_requests q WHERE q.request_kind=kind AND
 ((kind='company' AND q.market=market AND coalesce(q.code,q.ticker)=identity) OR
  (kind='industry' AND public._kairos_folder_key(coalesce(q.drive_folder_name,(SELECT f.folder_name FROM public.kairos_industry_folders f WHERE f.alias_key=public._kairos_folder_key(q.industry)),q.industry))=public._kairos_folder_key(folder)))
 AND q.status='sent' AND q.notion_url IS NOT NULL AND q.completed_at>=after_at
 AND (kind='industry' OR (
  (market='US' AND us.earnings_checked_at>=now()-interval '1 day' AND (us.latest_earnings_at IS NULL OR us.latest_earnings_at<=q.completed_at)) OR
  (market='KR' AND NOT EXISTS(SELECT 1 FROM public.earnings_disclosures e WHERE e.code=identity
    AND e.doc_type IN ('periodic','provisional','pl_change') AND (e.disclosed_at::date + interval '1 day') AT TIME ZONE 'Asia/Seoul'>q.completed_at))))
 ORDER BY q.completed_at DESC LIMIT 1;
 IF r.update_id IS NOT NULL THEN RETURN jsonb_build_object('status','reused','request_id',r.update_id,'notion_url',r.notion_url,'completed_at',r.completed_at,'claude',public._kairos_claude_status(r.update_id)); END IF;
 IF (SELECT count(*) FROM public.kairos_requests WHERE source='jarvis' AND status IN ('pending','working','awaiting_input','sending'))>=6 THEN
  RETURN jsonb_build_object('status','rejected','reason','대기 6건 초과 — Codex 사용량 보호'); END IF;
 new_id:=nextval('public.kairos_jarvis_seq');
 INSERT INTO public.kairos_requests(update_id,chat_id,user_id,source,market,ticker,code,request_kind,
 target_name,company_name,industry,raw_text,reuse_after,drive_folder_name)
 VALUES(new_id,0,0,'jarvis',market,CASE WHEN kind='company' AND market='US' THEN identity END,
 CASE WHEN kind='company' AND market='KR' THEN identity END,kind,target,
 CASE WHEN kind='company' THEN target END,CASE WHEN kind='industry' THEN target ELSE p_payload->>'industry' END,
 target,after_at,CASE WHEN kind='industry' THEN folder END);
 RETURN jsonb_build_object('status','queued','request_id',new_id);
END $$;

CREATE OR REPLACE FUNCTION public.jarvis_analysis_status(p_token text,p_request_ids bigint[]) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE result jsonb;
BEGIN
 IF NOT public._jarvis_ok(p_token) THEN RAISE EXCEPTION 'unauthorized'; END IF;
 SELECT coalesce(jsonb_agg(jsonb_build_object('request_id',q.update_id,'status',q.status,
 'stage',q.stage,'notion_url',q.notion_url,'error',q.error,'completed_at',q.completed_at,
 'claude',public._kairos_claude_status(q.update_id),
 'deck',CASE WHEN d.id IS NOT NULL THEN jsonb_build_object('status',d.status,'notion_url',d.notion_url,'error',d.error) END)
 ORDER BY q.update_id),'[]'::jsonb) INTO result
 FROM public.kairos_requests q LEFT JOIN LATERAL (
 SELECT * FROM public.kairos_deck_requests WHERE request_id=q.update_id AND mode='deck' ORDER BY id DESC LIMIT 1) d ON true
 WHERE q.update_id=ANY(p_request_ids);
 RETURN result;
END $$;

CREATE OR REPLACE FUNCTION public.jarvis_request_deck(p_token text,p_request_id bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE r public.kairos_requests%ROWTYPE; d public.kairos_deck_requests%ROWTYPE;
BEGIN
 IF NOT public._jarvis_ok(p_token) THEN RAISE EXCEPTION 'unauthorized'; END IF;
 PERFORM pg_advisory_xact_lock(8933940541);
 SELECT * INTO r FROM public.kairos_requests WHERE update_id=p_request_id;
 IF r.update_id IS NULL OR r.request_kind<>'company' OR r.status<>'sent' OR r.notion_url IS NULL THEN
  RETURN jsonb_build_object('status','rejected','reason','완료된 기업 분석만 발표자료 생성 가능'); END IF;
 SELECT * INTO d FROM public.kairos_deck_requests WHERE request_id=p_request_id AND mode='deck' AND status IN ('pending','working','sent') ORDER BY id DESC LIMIT 1;
 IF d.status='sent' THEN RETURN jsonb_build_object('status','sent','notion_url',d.notion_url); END IF;
 IF d.id IS NOT NULL THEN RETURN jsonb_build_object('status','in_progress'); END IF;
 INSERT INTO public.kairos_deck_requests(request_id,mode) VALUES(p_request_id,'deck');
 RETURN jsonb_build_object('status','queued');
END $$;

CREATE OR REPLACE FUNCTION public.kairos_claim_deck() RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE d public.kairos_deck_requests%ROWTYPE; r public.kairos_requests%ROWTYPE; c jsonb;
BEGIN
 PERFORM pg_advisory_xact_lock(8933940542);
 IF EXISTS(SELECT 1 FROM public.kairos_deck_requests WHERE status='working') THEN RETURN NULL; END IF;
 SELECT * INTO d FROM public.kairos_deck_requests q WHERE q.status='pending' AND
 (q.retry_after IS NULL OR q.retry_after<=now()) AND
 (q.mode='analysis' OR NOT EXISTS(SELECT 1 FROM public.kairos_deck_requests a
 WHERE a.request_id=q.request_id AND a.mode='analysis' AND a.status IN ('pending','working')))
 ORDER BY q.created_at,q.id FOR UPDATE SKIP LOCKED LIMIT 1;
 IF d.id IS NULL THEN RETURN NULL; END IF;
 UPDATE public.kairos_deck_requests SET status='working',claimed_at=now(),attempts=attempts+1,error=NULL WHERE id=d.id RETURNING * INTO d;
 SELECT * INTO r FROM public.kairos_requests WHERE update_id=d.request_id;
 SELECT to_jsonb(a) INTO c FROM public.kairos_deck_requests a WHERE a.request_id=d.request_id
 AND a.mode='analysis' AND a.status='sent' ORDER BY a.id DESC LIMIT 1;
 RETURN to_jsonb(d)||jsonb_build_object('analysis',to_jsonb(r),'claude_analysis',c);
END $$;
REVOKE ALL ON FUNCTION public._kairos_claude_status(bigint),public.kairos_queue_claude_analysis(),public.kairos_claim_deck() FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.kairos_claim_deck() TO service_role;
-- CREATE OR REPLACE preserves existing token RPC ACLs.
NOTIFY pgrst,'reload schema';
COMMIT;
