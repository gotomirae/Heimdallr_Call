// PRD Ref: §8.7 H. Disposable PostgreSQL fixture only; no production requests or Notion writes.
import {PGlite} from '../../.cache/pg-jarvis/node_modules/@electric-sql/pglite/dist/index.js';
import fs from 'node:fs';
const db=new PGlite();
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
CREATE SCHEMA vault; CREATE TABLE vault.decrypted_secrets(name text,decrypted_secret text);
INSERT INTO vault.decrypted_secrets VALUES ('heimdallr_jarvis_token','fixture-only');
CREATE TABLE krx_universe(code text PRIMARY KEY,name text);
INSERT INTO krx_universe VALUES ('005930','삼성전자');
CREATE TABLE earnings_disclosures(code text,doc_type text,disclosed_at timestamptz);`);
for(const file of ['kairos_requests.sql','kairos_jarvis.sql','kairos_claude.sql','kairos_claude.sql'])
 await db.exec(fs.readFileSync('docs/migrations/'+file,'utf8'));
const checks=[];
function check(name,ok){checks.push({name,ok});if(!ok)throw Error(name)}
const call=async(name,args=[]) => (await db.query(`SELECT public.${name}(${args.map((_,i)=>'$'+(i+1)).join(',')}) AS r`,args)).rows[0].r;
const token='fixture-only';
for(const [name,args] of [['jarvis_request_analysis',['wrong',{}]],['jarvis_analysis_status',['wrong',[]]],['jarvis_request_deck',['wrong',-1]]]){
 let denied=false;try{await call(name,args)}catch(e){denied=e.message.includes('unauthorized')}check(name+'-unauthorized',denied);
}
const payload={kind:'company',market:'KR',code:'005930',target_name:'삼성전자'};
const request=await call('jarvis_request_analysis',[token,payload]);
check('queued',request.status==='queued');
check('not-created-before-sent',(await db.query('SELECT count(*)::int AS n FROM kairos_deck_requests')).rows[0].n===0);
await db.exec('BEGIN');
await db.query("UPDATE kairos_requests SET status='sent',notion_url='https://www.notion.so/fixture',completed_at=now() WHERE update_id=$1",[request.request_id]);
check('same-transaction-auto-analysis',(await db.query("SELECT mode,status FROM kairos_deck_requests")).rows[0]?.mode==='analysis');
await db.exec('ROLLBACK');
check('transaction-rollback',(await db.query('SELECT count(*)::int AS n FROM kairos_deck_requests')).rows[0].n===0);
await db.query("UPDATE kairos_requests SET status='sent',notion_url='https://www.notion.so/fixture',completed_at=now() WHERE update_id=$1",[request.request_id]);
let status=(await call('jarvis_analysis_status',[token,[request.request_id]]))[0];
check('claude-pending-deck-null',status.claude.status==='pending'&&status.deck===null&&status.claude.top_pick===null);
check('reused-claude',(await call('jarvis_request_analysis',[token,payload])).claude.status==='pending');
await db.query("UPDATE kairos_requests SET status='sent' WHERE update_id=$1",[request.request_id]);
check('sent-idempotent',(await db.query('SELECT count(*)::int AS n FROM kairos_deck_requests')).rows[0].n===1);
check('deck-queued-during-analysis',(await call('jarvis_request_deck',[token,request.request_id])).status==='queued');
check('deck-mode-dedupe',(await call('jarvis_request_deck',[token,request.request_id])).status==='in_progress');
let job=await call('kairos_claim_deck');check('analysis-first',job.mode==='analysis'&&job.analysis.update_id===request.request_id);
check('exclusive',await call('kairos_claim_deck')===null);
await db.query("UPDATE kairos_deck_requests SET status='pending',retry_after=now()+interval '30 minutes' WHERE id=$1",[job.id]);
check('deck-waits-for-retrying-analysis',await call('kairos_claim_deck')===null);
await db.query("UPDATE kairos_deck_requests SET retry_after=NULL WHERE id=$1",[job.id]);
job=await call('kairos_claim_deck');
await db.query("UPDATE kairos_deck_requests SET status='sent',notion_url='https://www.notion.so/claude',analysis_md='/fixture/analysis.md' WHERE id=$1",[job.id]);
const deck=await call('kairos_claim_deck');check('deck-after-analysis',deck.mode==='deck');
check('passes-successful-analysis',deck.claude_analysis.analysis_md==='/fixture/analysis.md');
await db.query("UPDATE kairos_deck_requests SET status='sent',notion_url='https://www.notion.so/deck' WHERE id=$1",[deck.id]);
status=(await call('jarvis_analysis_status',[token,[request.request_id]]))[0];
check('separate-result-links',status.deck.notion_url.endsWith('/deck')&&status.claude.notion_url.endsWith('/claude'));
check('deck-reuse',(await call('jarvis_request_deck',[token,request.request_id])).status==='sent');
await db.exec("INSERT INTO kairos_requests(update_id,chat_id,user_id,code,company_name,request_kind,target_name,raw_text) VALUES(1,111,111,'005930','삼성전자','company','삼성전자','삼성전자'); UPDATE kairos_requests SET status='sent' WHERE update_id=1;");
check('telegram-no-automatic-job',(await db.query('SELECT count(*)::int AS n FROM kairos_deck_requests WHERE request_id=1')).rows[0].n===0);
const industry=await call('jarvis_request_analysis',[token,{kind:'industry',target_name:'반도체'}]);
await db.query("UPDATE kairos_requests SET status='sent',notion_url='https://www.notion.so/industry',completed_at=now() WHERE update_id=$1",[industry.request_id]);
const pick={name:'삼성전자',market:'KR',code:'005930'};
await db.query("UPDATE kairos_deck_requests SET status='failed',error='USAGE',top_pick=$2 WHERE request_id=$1 AND mode='analysis'",[industry.request_id,pick]);
status=(await call('jarvis_analysis_status',[token,[industry.request_id]]))[0];check('industry-top-pick',status.claude.top_pick.code==='005930');
check('industry-no-deck',(await call('jarvis_request_deck',[token,industry.request_id])).status==='rejected');
await db.query("UPDATE kairos_deck_requests SET status='failed' WHERE request_id=$1 AND mode='analysis'",[request.request_id]);
await db.query("UPDATE kairos_deck_requests SET status='pending' WHERE request_id=$1 AND mode='deck'",[request.request_id]);
check('failed-analysis-unblocks-deck',(await call('kairos_claim_deck')).mode==='deck');
await db.exec('SET ROLE anon');
check('anon-token-status',(await call('jarvis_analysis_status',[token,[request.request_id]]))[0].claude.status==='failed');
for(const sql of ['SELECT * FROM kairos_deck_requests','SELECT kairos_claim_deck()',"SELECT _kairos_claude_status(-1)"]){
 let denied=false;try{await db.query(sql)}catch(e){denied=true}check('anon-denied-'+sql,denied);
}
await db.exec('RESET ROLE');
check('mode-index',(await db.query("SELECT indexdef FROM pg_indexes WHERE indexname='kairos_deck_open_idx'")).rows[0].indexdef.includes('(request_id, mode)'));
console.log(JSON.stringify({checks:checks.length,passed:checks.filter(x=>x.ok).length,rerunnable:true,details:checks},null,2));
await db.close();
