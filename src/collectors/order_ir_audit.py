# PRD Ref: §9.1-3
"""KIND 공식 제출 IR의 재현 가능한 원문 조사 장부. 숫자를 자동 승인하지 않는다."""
import argparse
import csv
import hashlib
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import httpx
import pymupdf
from bs4 import BeautifulSoup

from src.config.constants import ORDER_IR_AUDIT_PAGE_SIZE, ORDER_IR_AUDIT_WORKERS
from src.utils.http import decode_html
from src.utils.console import enable_utf8_stdout

def main() -> int:
    enable_utf8_stdout()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codes-file',required=True,help='code 열을 가진 확보현황 CSV')
    parser.add_argument('--from-date',required=True)
    parser.add_argument('--to-date',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    for value in (args.from_date,args.to_date):
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError('날짜 형식')
        except ValueError:
            parser.error('날짜는 유효한 YYYY-MM-DD')
    if args.from_date > args.to_date:
        parser.error('시작일은 종료일 이전이어야 한다')
    root=Path(args.output); root.mkdir(parents=True,exist_ok=True)
    endpoint='https://kind.krx.co.kr/corpgeneral/irschedule.do'
    with Path(args.codes_file).open(encoding='utf-8-sig',newline='') as handle:
        codes={r['code'] for r in csv.DictReader(handle)}
    if not codes or any(not re.fullmatch(r'\d{6}',code) for code in codes):parser.error('6자리 code 목록 필요')
    (root/'targets.json').write_text(json.dumps(sorted(codes)),encoding='utf-8')
    params={'method':'searchIRMaterialsSub','forward':'searchirmaterials_sub','currentPageSize':str(ORDER_IR_AUDIT_PAGE_SIZE),'fromDate':args.from_date,'toDate':args.to_date}
    # GET은 서버가 필터를 무시해 15행을 돌려준다. POST 총건수/페이지를 검증한다.
    query_id=hashlib.sha256(json.dumps(params,sort_keys=True).encode()).hexdigest()[:12]
    def page(index):
        path=root/f'list-{query_id}-{index}.html'
        if not path.exists():
            response=httpx.post(endpoint,data={**params,'pageIndex':str(index)},timeout=90)
            response.raise_for_status();path.write_text(decode_html(response),encoding='utf-8')
        soup=BeautifulSoup(path.read_text(encoding='utf-8'),'html.parser')
        total=int(soup.select_one('.info em').get_text().replace(',',''))
        rows=[]
        for tr in soup.select('tbody tr'):
            cells=tr.find_all('td')
            if len(cells)!=5:continue
            company=cells[1].find('a',onclick=True)
            m=re.search(r"companysummary_open\('([0-9]{5})'\)",company.get('onclick','') if company else '')
            if not m:continue
            code=m[1]+'0'
            if code not in codes:continue
            for a in cells[4].select('a[download]'):
                if not a.get('href','').lower().endswith('.pdf'):continue
                url=urljoin(endpoint,a['href'])
                if not url.startswith('https://kind.krx.co.kr/external/dst/irReference/'):
                    raise ValueError('KIND 공식 IR 경로 이탈')
                rows.append({'code':code,'company':company.get_text(strip=True),'date':cells[2].get_text(strip=True),
                             'title':a.get('title',''),'url':url})
        return total,rows
    total,rows=page(1); pages=math.ceil(total/ORDER_IR_AUDIT_PAGE_SIZE)
    print('listing_total',total,'pages',pages,flush=True)
    with ThreadPoolExecutor(max_workers=ORDER_IR_AUDIT_WORKERS) as pool:
        for future in as_completed([pool.submit(page,i) for i in range(2,pages+1)]):
            n,rs=future.result()
            if n!=total:raise RuntimeError('IR listing changed during audit')
            rows.extend(rs)
    print('matched',len(rows),'companies',len({r['code'] for r in rows}),flush=True)
    (root/'discovery.json').write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
    selected={}
    for row in sorted(rows,key=lambda r:r['date'],reverse=True):
        # 같은 파일명으로 반복 NDR되는 자료는 최신 공개본 한 번만 읽는다.
        selected.setdefault((row['code'],row['title']),row)
    docs=list(selected.values())
    print('distinct_docs',len(docs),flush=True)
    def document(row):
        name=hashlib.sha256(row['url'].encode()).hexdigest()[:20]
        path=root/(name+'.pdf')
        if not path.exists():
            response=httpx.get(row['url'],timeout=90,follow_redirects=True)
            response.raise_for_status()
            if not response.content.startswith(b'%PDF'):raise ValueError('not_pdf')
            path.write_bytes(response.content)
        found=[]; image_only=[]
        with pymupdf.open(path) as doc:
            for i,p in enumerate(doc):
                t=p.get_text()
                if not t.strip():image_only.append(i+1)
                if re.search(r'수주\s*(?:잔고|잔액|실적|추이|액)|수주\s*\(\s*별도|신규\s*수주|New\s*Orders|Quarterly\s*Order|Order\s*(?:Backlog|Intake)|Bookings',t,re.I):
                    found.append({'page':i+1,'text':t})
        return {**row,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'pages':found,'image_only_pages':image_only}
    results=[];failures=[]
    with ThreadPoolExecutor(max_workers=ORDER_IR_AUDIT_WORKERS) as pool:
        futures={pool.submit(document,r):r for r in docs}
        for i,future in enumerate(as_completed(futures),1):
            try:results.append(future.result())
            except Exception as error:failures.append({**futures[future],'error':type(error).__name__})
            if i%25==0:print('read',i,'/',len(docs),'candidate_docs',sum(bool(r['pages']) for r in results),'failures',len(failures),flush=True)
            (root/'scan.json').write_text(json.dumps({'results':results,'failures':failures},ensure_ascii=False),encoding='utf-8')
    (root/'scan.json').write_text(json.dumps({'results':results,'failures':failures},ensure_ascii=False),encoding='utf-8')
    print('done',len(results),'candidates',sum(bool(r['pages']) for r in results),'companies',len({r['code'] for r in results if r['pages']}),'failures',len(failures),flush=True)
    summary={'from_date':args.from_date,'to_date':args.to_date,'target_companies':len(codes),
             'listing_total':total,'listing_pages':pages,'matched_rows':len(rows),
             'matched_companies':len({r['code'] for r in rows}),'read_documents':len(results),
             'candidate_documents':sum(bool(r['pages']) for r in results),
             'candidate_companies':len({r['code'] for r in results if r['pages']}),
             'failures':len(failures),'image_only_documents':sum(bool(r['image_only_pages']) for r in results)}
    (root/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
