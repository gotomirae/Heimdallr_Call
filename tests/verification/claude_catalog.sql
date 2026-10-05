-- PRD Ref: §8.7 H-4. Read-only production catalog audit; no sent transitions.
WITH checks AS (
 SELECT 'columns' AS check_name, count(*)=3 AS passed FROM information_schema.columns
 WHERE table_schema='public' AND table_name='kairos_deck_requests' AND column_name IN ('mode','analysis_md','top_pick')
 UNION ALL SELECT 'mode-default', column_default LIKE '%deck%' AND is_nullable='NO' FROM information_schema.columns
 WHERE table_schema='public' AND table_name='kairos_deck_requests' AND column_name='mode'
 UNION ALL SELECT 'mode-unique-index',indexdef LIKE '%(request_id, mode)%' FROM pg_indexes WHERE schemaname='public' AND indexname='kairos_deck_open_idx'
 UNION ALL SELECT 'single-worker-index',indexdef LIKE '%working%' FROM pg_indexes WHERE schemaname='public' AND indexname='kairos_deck_single_worker_idx'
 UNION ALL SELECT 'sent-trigger',count(*)=1 FROM pg_trigger WHERE tgrelid='public.kairos_requests'::regclass AND tgname='kairos_sent_claude_analysis' AND tgenabled='O'
 UNION ALL SELECT 'trigger-jarvis-transition', pg_get_functiondef('public.kairos_queue_claude_analysis()'::regprocedure) LIKE '%NEW.source=''jarvis''%' AND pg_get_functiondef('public.kairos_queue_claude_analysis()'::regprocedure) LIKE '%OLD.status IS DISTINCT FROM ''sent''%'
 UNION ALL SELECT 'claim-priority',pg_get_functiondef('public.kairos_claim_deck()'::regprocedure) LIKE '%a.mode=''analysis'' AND a.status IN (''pending'',''working'')%' AND pg_get_functiondef('public.kairos_claim_deck()'::regprocedure) LIKE '%claude_analysis%'
 UNION ALL SELECT 'status-claude-deck',pg_get_functiondef('public.jarvis_analysis_status(text,bigint[])'::regprocedure) LIKE '%_kairos_claude_status%' AND pg_get_functiondef('public.jarvis_analysis_status(text,bigint[])'::regprocedure) LIKE '%mode=''deck''%'
 UNION ALL SELECT 'reused-claude',pg_get_functiondef('public.jarvis_request_analysis(text,jsonb)'::regprocedure) LIKE '%''claude'',public._kairos_claude_status(r.update_id)%'
 UNION ALL SELECT 'deck-mode-dedupe',pg_get_functiondef('public.jarvis_request_deck(text,bigint)'::regprocedure) LIKE '%mode=''deck''%'
 UNION ALL SELECT 'anon-helper-denied',NOT has_function_privilege('anon','public._kairos_claude_status(bigint)','EXECUTE')
 UNION ALL SELECT 'anon-claim-denied',NOT has_function_privilege('anon','public.kairos_claim_deck()','EXECUTE')
 UNION ALL SELECT 'service-claim-allowed',has_function_privilege('service_role','public.kairos_claim_deck()','EXECUTE')
 UNION ALL SELECT 'anon-private-table-denied',NOT has_table_privilege('anon','public.kairos_deck_requests','SELECT')
)
SELECT check_name,passed FROM checks ORDER BY check_name;
