-- PRD Ref: §8.7 G. Run AFTER kairos_requests.sql and kairos_drive_confirmation.sql.
-- Vault secret already exists. Never SELECT it into client logs.
BEGIN;
ALTER TABLE public.kairos_requests
 ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'telegram',
 ADD COLUMN IF NOT EXISTS market text NOT NULL DEFAULT 'KR',
 ADD COLUMN IF NOT EXISTS ticker text,
 ADD COLUMN IF NOT EXISTS stage text,
 ADD COLUMN IF NOT EXISTS stage_updated_at timestamptz,
 ADD COLUMN IF NOT EXISTS reuse_after timestamptz;
ALTER TABLE public.kairos_requests
 DROP CONSTRAINT IF EXISTS kairos_requests_source_check,
 DROP CONSTRAINT IF EXISTS kairos_requests_market_check,
 DROP CONSTRAINT IF EXISTS kairos_requests_target_shape_check,
 DROP CONSTRAINT IF EXISTS kairos_requests_check,
 DROP CONSTRAINT IF EXISTS kairos_requests_jarvis_identity_check,
 DROP CONSTRAINT IF EXISTS kairos_requests_jarvis_input_check;
ALTER TABLE public.kairos_requests
 ADD CONSTRAINT kairos_requests_jarvis_identity_check CHECK (
 source<>'jarvis' OR (update_id<0 AND chat_id=0 AND user_id=0)),
 ADD CONSTRAINT kairos_requests_jarvis_input_check CHECK (
 source<>'jarvis' OR status<>'awaiting_input'),
 ADD CONSTRAINT kairos_requests_source_check CHECK (source IN ('telegram','jarvis')),
 ADD CONSTRAINT kairos_requests_market_check CHECK (market IN ('KR','US')),
 ADD CONSTRAINT kairos_requests_target_shape_check CHECK (
 (request_kind='company' AND company_name IS NOT NULL AND
  ((market='KR' AND code IS NOT NULL AND ticker IS NULL) OR
   (market='US' AND ticker IS NOT NULL AND code IS NULL)))
 OR (request_kind='industry' AND code IS NULL AND industry IS NOT NULL));
CREATE SEQUENCE IF NOT EXISTS public.kairos_jarvis_seq INCREMENT -1 MINVALUE -9223372036854775808 MAXVALUE -1 START -1;
CREATE TABLE IF NOT EXISTS public.kairos_us_companies (
 ticker text PRIMARY KEY, name text NOT NULL, cik text NOT NULL,
 exchange text NOT NULL, verified_at timestamptz NOT NULL,
 latest_earnings_at timestamptz, earnings_checked_at timestamptz
);
ALTER TABLE public.kairos_us_companies ADD COLUMN IF NOT EXISTS earnings_checked_at timestamptz;
CREATE TABLE IF NOT EXISTS public.kairos_industry_folders (
 alias_key text PRIMARY KEY, folder_name text NOT NULL
);
CREATE TABLE IF NOT EXISTS public.kairos_deck_requests (
 id bigserial PRIMARY KEY,
 request_id bigint NOT NULL REFERENCES public.kairos_requests(update_id),
 status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','working','sent','failed')),
 notion_url text, drive_dir text, files jsonb, error text,
 attempts int NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT now(),
 claimed_at timestamptz, completed_at timestamptz, retry_after timestamptz
);
ALTER TABLE public.kairos_deck_requests ADD COLUMN IF NOT EXISTS retry_after timestamptz;
CREATE UNIQUE INDEX IF NOT EXISTS kairos_deck_open_idx ON public.kairos_deck_requests(request_id)
 WHERE status IN ('pending','working','sent');
-- A worker crash must not allow a second deck to execute concurrently.
CREATE UNIQUE INDEX IF NOT EXISTS kairos_deck_single_worker_idx ON public.kairos_deck_requests((status))
 WHERE status='working';
ALTER TABLE public.kairos_deck_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.kairos_us_companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.kairos_industry_folders ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.kairos_deck_requests, public.kairos_us_companies, public.kairos_industry_folders FROM anon, authenticated;
REVOKE ALL ON SEQUENCE public.kairos_jarvis_seq, public.kairos_deck_requests_id_seq FROM anon, authenticated;
GRANT ALL ON public.kairos_deck_requests, public.kairos_us_companies, public.kairos_industry_folders TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.kairos_deck_requests_id_seq TO service_role;

CREATE OR REPLACE FUNCTION public._kairos_folder_key(p_name text) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog AS $$
 SELECT upper(regexp_replace(regexp_replace(trim(p_name),'^[0-9]+[[:space:]]*[.)_-][[:space:]]*',''),'[[:space:]._\-]+','','g'));
$$;
-- Initial map; the local registry sync replaces these rows from editable YAML.
INSERT INTO public.kairos_industry_folders(alias_key,folder_name)
SELECT public._kairos_folder_key(a),f FROM (VALUES
 ('AI · 반도체','1. AI 반도체'),('AI','1. AI 반도체'),('반도체','1. AI 반도체'),('AI 반도체','1. AI 반도체'),
 ('바이오','2. 바이오'),('엔터','3. K-엔터'),('화장품_미용기기','15. 화장품'),('화장품','15. 화장품'),
 ('미용기기','4. 미용_의료기기'),('헬스케어','4. 미용_의료기기'),('헬스케어(의료기기)','4. 미용_의료기기'),
 ('전력인프라','5. 전력인프라'),('IT','6. IT'),('OLED','8. OLED'),('디스플레이','8. OLED'),
 ('네트워크','17. 네트워크'),('우주항공방산','7. 우주항공'),('소비재','9. 음식료'),
 ('소비재(음식료)','9. 음식료'),('음식료','9. 음식료'),('의류','13. 의류'),('Robot','10. 로봇'),
 ('로봇','10. 로봇'),('건설','11. 건설'),('조선','12. 조선'),('자율주행차','14. 자율주행차'),
 ('2차 전지','16. 2차 전지'),('ETF','18. ETF')
) AS v(a,f) ON CONFLICT (alias_key) DO NOTHING;

CREATE OR REPLACE FUNCTION public._jarvis_ok(p_token text) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE secret text; a bytea; b bytea; mismatch int:=0;
BEGIN
 SELECT decrypted_secret INTO secret FROM vault.decrypted_secrets WHERE name='heimdallr_jarvis_token';
 -- Fixed-length digest comparison, no prefix/length-dependent comparison loop.
 a:=sha256(convert_to(coalesce(p_token,''),'UTF8'));
 b:=sha256(convert_to(coalesce(secret,''),'UTF8'));
 FOR i IN 0..31 LOOP
   mismatch:=mismatch | (get_byte(a,i) # get_byte(b,i));
 END LOOP;
 RETURN secret IS NOT NULL AND p_token IS NOT NULL AND length(secret)>0 AND mismatch=0;
END $$;

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
 IF r.update_id IS NOT NULL THEN RETURN jsonb_build_object('status','reused','request_id',r.update_id,'notion_url',r.notion_url,'completed_at',r.completed_at); END IF;
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
 'deck',CASE WHEN d.id IS NOT NULL THEN jsonb_build_object('status',d.status,'notion_url',d.notion_url,'error',d.error) END)
 ORDER BY q.update_id),'[]'::jsonb) INTO result
 FROM public.kairos_requests q LEFT JOIN LATERAL (
 SELECT * FROM public.kairos_deck_requests WHERE request_id=q.update_id ORDER BY id DESC LIMIT 1) d ON true
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
 SELECT * INTO d FROM public.kairos_deck_requests WHERE request_id=p_request_id AND status IN ('pending','working','sent') ORDER BY id DESC LIMIT 1;
 IF d.status='sent' THEN RETURN jsonb_build_object('status','sent','notion_url',d.notion_url); END IF;
 IF d.id IS NOT NULL THEN RETURN jsonb_build_object('status','in_progress'); END IF;
 INSERT INTO public.kairos_deck_requests(request_id) VALUES(p_request_id);
 RETURN jsonb_build_object('status','queued');
END $$;

-- Service-only claim; scheduler concurrency alone is insufficient.
CREATE OR REPLACE FUNCTION public.kairos_claim_deck() RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE d public.kairos_deck_requests%ROWTYPE; r public.kairos_requests%ROWTYPE;
BEGIN
 PERFORM pg_advisory_xact_lock(8933940542);
 IF EXISTS(SELECT 1 FROM public.kairos_deck_requests WHERE status='working') THEN RETURN NULL; END IF;
 SELECT * INTO d FROM public.kairos_deck_requests WHERE status='pending' AND
 (retry_after IS NULL OR retry_after<=now()) ORDER BY created_at,id FOR UPDATE SKIP LOCKED LIMIT 1;
 IF d.id IS NULL THEN RETURN NULL; END IF;
 UPDATE public.kairos_deck_requests SET status='working',claimed_at=now(),attempts=attempts+1,error=NULL WHERE id=d.id RETURNING * INTO d;
 SELECT * INTO r FROM public.kairos_requests WHERE update_id=d.request_id;
 RETURN to_jsonb(d)||jsonb_build_object('analysis',to_jsonb(r));
END $$;
REVOKE ALL ON FUNCTION public._jarvis_ok(text), public._kairos_folder_key(text),
 public.jarvis_request_analysis(text,jsonb), public.jarvis_analysis_status(text,bigint[]),
 public.jarvis_request_deck(text,bigint), public.kairos_claim_deck() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.jarvis_request_analysis(text,jsonb),
 public.jarvis_analysis_status(text,bigint[]), public.jarvis_request_deck(text,bigint) TO anon, service_role;
GRANT EXECUTE ON FUNCTION public.kairos_claim_deck() TO service_role;
NOTIFY pgrst,'reload schema';
COMMIT;
