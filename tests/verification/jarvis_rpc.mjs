// PRD Ref: §8.7 G. Local PostgreSQL fixture; no production DB or Notion writes.
import {PGlite} from '../../.cache/pg-jarvis/node_modules/@electric-sql/pglite/dist/index.js';
import fs from 'node:fs';
const db = new PGlite();
await db.exec(`
CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
CREATE SCHEMA vault;
CREATE TABLE vault.decrypted_secrets(name text,decrypted_secret text);
INSERT INTO vault.decrypted_secrets VALUES ('heimdallr_jarvis_token','fixture-only');
CREATE TABLE public.krx_universe(code text PRIMARY KEY,name text);
INSERT INTO public.krx_universe VALUES ('005930','삼성전자');
CREATE TABLE public.earnings_disclosures(code text,doc_type text,disclosed_at timestamptz);
`);
await db.exec(fs.readFileSync('docs/migrations/kairos_requests.sql','utf8'));
await db.exec("ALTER TABLE kairos_requests ADD CONSTRAINT kairos_requests_check CHECK ((request_kind='company' AND code IS NOT NULL) OR request_kind='industry')");
const sql = fs.readFileSync('docs/migrations/kairos_jarvis.sql','utf8');
await db.exec(sql);
await db.exec(sql);
const token = 'fixture-only';
const call=async (name,args)=> (await db.query(`SELECT public.${name}(${args.map((_,i)=>'$'+(i+1)).join(',')}) AS result`,args)).rows[0].result;
const checks=[];
function check(name,ok) {checks.push({name,ok});if(!ok) throw Error(name)}
let unauthorized=false;
try {await call('jarvis_request_analysis',['wrong',{kind:'company',target_name:'삼성전자',code:'005930',market:'KR'}]);}catch(e){unauthorized=e.message.includes('unauthorized')}
check('unauthorized',unauthorized);
const payload={kind:'company',target_name:'삼성전자',code:'005930',market:'KR'};
let a=await call('jarvis_request_analysis',[token,payload]);
check('queued-negative-id',a.status==='queued'&&a.request_id<0);
let b=await call('jarvis_request_analysis',[token,payload]);check('in-progress',b.status==='in_progress'&&b.request_id===a.request_id);
await db.query("UPDATE kairos_requests SET status='sent',notion_url='https://www.notion.so/fixture',completed_at=now() WHERE update_id=$1",[a.request_id]);
check('reused',(await call('jarvis_request_analysis',[token,payload])).status==='reused');
await db.exec("INSERT INTO earnings_disclosures VALUES ('005930','provisional',now())");
check('earnings-invalidates-reuse',(await call('jarvis_request_analysis',[token,payload])).status==='queued');
check('deck-queued',(await call('jarvis_request_deck',[token,a.request_id])).status==='queued');
check('deck-idempotent',(await call('jarvis_request_deck',[token,a.request_id])).status==='in_progress');
check('deck-not-ready',(await call('jarvis_request_deck',[token,-999])).status==='rejected');
let claimed=(await db.query('SELECT kairos_claim_deck() AS r')).rows[0].r;check('deck-claim',claimed.status==='working'&&claimed.attempts===1);
check('deck-exclusive',(await db.query('SELECT kairos_claim_deck() AS r')).rows[0].r===null);
await db.exec("UPDATE kairos_deck_requests SET status='sent',notion_url='https://www.notion.so/deck'");
check('deck-complete-reuse',(await call('jarvis_request_deck',[token,a.request_id])).status==='sent');
let status=await call('jarvis_analysis_status',[token,[a.request_id]]);
check('status-shape',Array.isArray(status)&&status[0].deck.status==='sent'&&status[0].status==='sent');
await db.exec("INSERT INTO kairos_us_companies VALUES ('NVDA','NVIDIA CORP','0001045810','Nasdaq',now(),NULL,now())");
let us=await call('jarvis_request_analysis',[token,{kind:'company',market:'US',code:'NVDA',target_name:'NVIDIA'}]);
let usrow=(await db.query('SELECT * FROM kairos_requests WHERE update_id=$1',[us.request_id])).rows[0];
check('US-no-KRX-FK',us.status==='queued'&&usrow.code===null&&usrow.ticker==='NVDA');
check('unknown-US-rejected',(await call('jarvis_request_analysis',[token,{kind:'company',market:'US',code:'XYZ123',target_name:'unknown'}])).status==='rejected');
let industry=await call('jarvis_request_analysis',[token,{kind:'industry',target_name:'AI · 반도체'}]);
check('industry-queued',industry.status==='queued');
check('industry-alias-dedup',(await call('jarvis_request_analysis',[token,{kind:'industry',target_name:'반도체'}])).status==='in_progress');
check('unmapped-industry-queued',(await call('jarvis_request_analysis',[token,{kind:'industry',target_name:'양자컴퓨터'}])).status==='queued');
await call('jarvis_request_analysis',[token,{kind:'industry',target_name:'여행'}]);
await call('jarvis_request_analysis',[token,{kind:'industry',target_name:'금융'}]);
check('six-budget',(await call('jarvis_request_analysis',[token,{kind:'industry',target_name:'다른산업'}])).status==='rejected');
await db.exec('SET ROLE anon');
check('anon-authenticated-rpc', (await call('jarvis_analysis_status',[token,[a.request_id]])).length===1);
let denied=false;try{await db.query('SELECT * FROM kairos_deck_requests')}catch(e){denied=true}
check('anon-table-denied',denied);
denied=false;try{await db.query("SELECT _jarvis_ok('fixture-only')")}catch(e){denied=true}
check('anon-secret-helper-denied',denied);
denied=false;try{await db.query("SELECT kairos_claim_deck()")}catch(e){denied=true}
check('anon-claim-denied',denied);
await db.exec('RESET ROLE');
console.log(JSON.stringify({checks:checks.length,passed:checks.filter(x=>x.ok).length,rerunnable:true,checks_detail:checks},null,2));
await db.close();
