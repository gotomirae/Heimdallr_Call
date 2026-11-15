// PRD Ref: §9/10 · partial refresh must preserve independently dated fields.
const assert = require('node:assert/strict');
const load = require('jiti')(__filename);
const {mergeIndicatorQuote, completedCloseAtKst16} = load('../lib/naver.ts');
const prior = {quoteAvailable:true,annualAvailable:true,priceDate:'2026-11-12',close:100,
  per4q:10,eps:10,fwdPer:8,roe:20,fetchedAt:'2026-11-12T08:00:00Z'};
const quoteOnly = {...prior,annualAvailable:false,priceDate:'2026-11-13',close:120,per4q:null,eps:null,fwdPer:null,roe:null};
const merged = mergeIndicatorQuote(prior,quoteOnly);
assert.equal(merged.close,120);
assert.equal(merged.per4q,10); // Previous verified annual data survives a failed annual request.
assert.equal(merged.eps,10);
const annualOnly = {...prior,quoteAvailable:false,priceDate:null,close:null,per4q:12};
assert.equal(mergeIndicatorQuote(prior,annualOnly).close,100);
assert.equal(mergeIndicatorQuote(prior,annualOnly).priceDate,'2026-11-12');
assert.equal(mergeIndicatorQuote(prior,annualOnly).per4q,12);
assert.deepEqual(mergeIndicatorQuote(prior,null),prior);
assert.equal(mergeIndicatorQuote(null,null),null);
const prices = [{trade_date:'2026-11-12',close:100},{trade_date:'2026-11-13',close:120}];
assert.equal(completedCloseAtKst16(prices,new Date('2026-11-13T06:59:00Z')).tradeDate,'2026-11-12');
assert.equal(completedCloseAtKst16(prices,new Date('2026-11-13T07:00:00Z')).chgPct, (120/100-1)*100);
console.log('10 indicator assertions passed');
