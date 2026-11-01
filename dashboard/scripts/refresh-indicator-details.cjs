// PRD Ref: §9/10 · ADR50 — only invoked by the 16:00 Python-gated workflow.
const {createClient} = require('@supabase/supabase-js');
const load = require('jiti')(__filename);
const naver = load('../lib/naver.ts');
const constants = require('../lib/constants.json');
const url = (process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL || '').trim();
const key = (process.env.SUPABASE_SERVICE_KEY || '').trim();
if (!url || !key) throw new Error('INDICATOR_STORAGE_CONFIG_MISSING');
const db = createClient(url, key);
const day = new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const arg = process.argv.indexOf('--code');
const selected = arg >= 0 ? process.argv[arg+1] : null;
const bootstrap = process.argv.includes('--bootstrap');
if (!bootstrap && process.env.HEIMDALLR_DAILY_INDICATORS_ALLOWED !== 'true') throw new Error('DAILY_CALENDAR_GATE_REQUIRED');
if (selected && !/^[0-9A-Z]{6}$/.test(selected)) throw new Error('INVALID_CODE');

async function all(table, columns, alter=q=>q) {
  const rows=[];
  for(let offset=0;;offset+=constants.indicator_details.page_size) {
    const size=constants.indicator_details.page_size;
    const {data,error}=await alter(db.from(table).select(columns)).order('code').range(offset,offset+size-1);
    if(error) throw new Error(`STORAGE_${error.code}`);
    rows.push(...data);
    if(data.length<size) return rows;
  }
}
async function main() {
  const codes=await all('krx_universe','code',q=>selected?q.eq('code',selected):q
    .eq('is_excluded',false).gte('market_cap_krw',constants.gate.market_cap_floor_krw));
  const stored=new Map((await all('daily_indicator_details','code,snap_date,payload',q=>selected?q.eq('code',selected):q)).map(r=>[r.code,r]));
  const stats={day,targets:codes.length,updated:0,reused:0,partial:0,failed:0};
  async function collect({code}) {
    const before=stored.get(code), prior=before?.payload || {};
    if(before?.snap_date===day && !prior.incomplete && prior.quote && prior.prices?.length && prior.flows?.length) {stats.reused++;return;}
    const from=prior.flows?.map(r=>r.trade_date).sort().at(-1) || `${Number(day.slice(0,4))-constants.indicator_details.history_years}${day.slice(4)}`;
    const [prices,quote,flows]=await Promise.all([
      naver.collectNaverDailyPrices(code,constants.indicator_details.history_years),
      naver.collectNaverLiveSnapshot(code),naver.collectNaverInvestorFlows(code,from)]);
    const merged=new Map((prior.flows || []).map(r=>[r.trade_date,r]));
    flows.forEach(row=>merged.set(row.trade_date,row));
    // Failures preserve the previous valid field and its actual source date.
    const payload={prices:prices.length?prices:prior.prices || [],quote:quote || prior.quote || null,
      flows:[...merged.values()].filter(r=>r.trade_date>=`${Number(day.slice(0,4))-constants.indicator_details.history_years}${day.slice(4)}`).sort((a,b)=>a.trade_date.localeCompare(b.trade_date)),
      sources:{prices:prices.length?day:prior.sources?.prices || null,quote:quote?day:prior.sources?.quote || null,flows:flows.length?day:prior.sources?.flows || null},
      incomplete:!prices.length || !quote?.quoteAvailable || !quote?.annualAvailable || !flows.length};
    if(!prices.length && !quote && !flows.length) {stats.failed++;return;}
    const asOf=bootstrap ? payload.prices.at(-1)?.trade_date || quote?.priceDate : day;
    if(!asOf) {stats.failed++;return;}
    const {error}=await db.from('daily_indicator_details').upsert({code,snap_date:asOf,payload,checked_at:new Date().toISOString()},{onConflict:'code'});
    if(error) throw new Error(`STORE_${error.code}`);
    stats.updated++;if(payload.incomplete)stats.partial++;
  }
  for(let i=0;i<codes.length;i+=constants.indicator_details.concurrency)
    await Promise.all(codes.slice(i,i+constants.indicator_details.concurrency).map(collect));
  console.log(JSON.stringify(stats));
  // A delisted/temporarily unavailable source must not prevent every other daily indicator.
  // Explicit counts remain in the job log; failed stocks retain their prior dated snapshot.
  if(stats.targets && stats.failed===stats.targets) process.exitCode=1;
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
