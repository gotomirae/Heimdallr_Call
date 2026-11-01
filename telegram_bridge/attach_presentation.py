# PRD Ref: §8.7 K · SC: 실제 같은 대상 부모에 PPT 파일 저장·전체 재조회
"""Attach real PPTX/PDF to the source's verified company/industry parent."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse
import zipfile

from dotenv import dotenv_values
import httpx

from src.utils.env import optional_env
from telegram_bridge.notion_readback import PARENTS, compact_id

PPTX_MIME = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'


def file_hash(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024): digest.update(chunk)
    return digest.hexdigest()


def token() -> str:
    value = optional_env('NOTION_TOKEN')
    if not value:
        value = dotenv_values(Path.home()/'.claude/skills/kairos/.env').get('NOTION_TOKEN')
    if not value or value.startswith('<<<'):
        raise ValueError('NOTION_TOKEN_REQUIRED')
    return value.strip()


def page_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in {'notion.so','www.notion.so','app.notion.com'}:
        raise ValueError('NOTION_URL_INVALID')
    match = re.search(r'([0-9a-fA-F]{32})$', parsed.path.replace('-', ''))
    if not match:
        raise ValueError('NOTION_URL_INVALID')
    return match[1]


class Notion:
    def __init__(self):
        self.client = httpx.Client(base_url='https://api.notion.com/v1', timeout=90,
            headers={'Authorization':f'Bearer {token()}', 'Notion-Version':'2025-09-03'})

    def call(self, method: str, path: str, **kwargs) -> dict:
        response = self.client.request(method, path, **kwargs)
        if response.status_code >= 400:
            # Never print authorization, signed file links or API error bodies.
            raise RuntimeError(f'NOTION_HTTP_{response.status_code}')
        return response.json()

    def children(self, identity: str) -> list[dict]:
        results, cursor = [], None
        while True:
            params={'page_size':100}
            if cursor: params['start_cursor']=cursor
            data=self.call('GET',f'/blocks/{identity}/children',params=params)
            results.extend(data['results'])
            if not data.get('has_more'): return results
            cursor=data['next_cursor']

    def upload(self, path: Path, mime: str) -> str:
        size=path.stat().st_size
        multiple=size > 20*1024*1024
        chunk=10*1024*1024  # Official Notion 5–20MiB part contract.
        payload={'mode':'multi_part' if multiple else 'single_part','filename':path.name,'content_type':mime}
        if multiple: payload['number_of_parts']=(size+chunk-1)//chunk
        data=self.call('POST','/file_uploads',json=payload)
        with path.open('rb') as f:
            if multiple:
                for i in range(1,payload['number_of_parts']+1):
                    self.call('POST',f'/file_uploads/{data["id"]}/send',data={'part_number':str(i)},
                              files={'file':(path.name,f.read(chunk),mime)})
                completed=self.call('POST',f'/file_uploads/{data["id"]}/complete',json={})
            else:
                completed=self.call('POST',f'/file_uploads/{data["id"]}/send',files={'file':(path.name,f,mime)})
        if completed.get('status') != 'uploaded': raise ValueError('NOTION_UPLOAD_INCOMPLETE')
        return data['id']


def verified_parent(n: Notion, source: str, kind: str) -> tuple[dict, dict, dict]:
    source_page=n.call('GET',f'/pages/{page_id(source)}')
    if source_page.get('archived') or source_page.get('in_trash'):
        raise ValueError('NOTION_SOURCE_ARCHIVED')
    parent_id=source_page.get('parent',{}).get('page_id')
    if not parent_id: raise ValueError('NOTION_SOURCE_PARENT_INVALID')
    parent=n.call('GET',f'/pages/{parent_id}')
    root_id=parent.get('parent',{}).get('page_id')
    if (compact_id(root_id)!=PARENTS[kind] or parent.get('archived') or parent.get('in_trash')):
        raise ValueError('NOTION_TARGET_PARENT_INVALID')
    root=n.call('GET',f'/pages/{root_id}')
    if root.get('archived') or root.get('in_trash'): raise ValueError('NOTION_ROOT_ARCHIVED')
    return source_page,parent,root


def caption_text(block: dict) -> str:
    return ''.join(r.get('plain_text') or r.get('text',{}).get('content','')
                   for r in block.get(block.get('type'),{}).get('caption',[]))


def attach(n: Notion, kind: str, source: str, pptx: Path, pdf: Path, request_id: str, proof_path: Path) -> dict:
    if not re.fullmatch(r'D[1-9]\d*',request_id): raise ValueError('DECK_REQUEST_ID_INVALID')
    if pptx.suffix.lower()!='.pptx' or pdf.suffix.lower()!='.pdf': raise ValueError('DECK_EXTENSIONS_INVALID')
    with zipfile.ZipFile(pptx) as archive:
        if archive.testzip() or 'ppt/presentation.xml' not in archive.namelist(): raise ValueError('PPTX_INVALID')
    with pdf.open('rb') as stream:
        if stream.read(5)!=b'%PDF-': raise ValueError('PDF_INVALID')
    source_page,parent,root=verified_parent(n,source,kind)
    existing=n.children(parent['id'])
    additions,expected=[],[]
    for path,block_type,mime in [(pptx,'file',PPTX_MIME),(pdf,'pdf','application/pdf')]:
        digest=file_hash(path)
        marker=f'{request_id} | {path.name} | SHA256:{digest}'
        expected.append({'type':block_type,'filename':path.name,'sha256':digest,'caption':marker})
        if any(b['type']==block_type and caption_text(b)==marker for b in existing): continue
        upload_id=n.upload(path,mime)
        body={'type':'file_upload','file_upload':{'id':upload_id},'caption':[{'type':'text','text':{'content':marker}}]}
        if block_type=='file': body['name']=path.name
        additions.append({'object':'block','type':block_type,block_type:body})
    if additions: n.call('PATCH',f'/blocks/{parent["id"]}/children',json={'children':additions})
    # An upload acknowledgment alone is not a stored PPT: actual native reread required.
    _,reread_parent,reread_root=verified_parent(n,source,kind)
    blocks=n.children(parent['id'])
    for item in expected:
        matching=[b for b in blocks if b['type']==item['type'] and caption_text(b)==item['caption']]
        if len(matching)!=1 or matching[0][item['type']].get('type') not in {'file','file_upload'}:
            raise ValueError('DECK_ATTACHMENT_READBACK_FAILED')
    proof={'request_id':request_id,'kind':kind,'checked_at':datetime.now(timezone.utc).isoformat(),
           'source':source_page,'page':reread_parent,'ancestors':[reread_root],
           'blocks':{'results':blocks,'has_more':False},'attachments':expected,'verified':True}
    proof_path.parent.mkdir(parents=True,exist_ok=True)
    proof_path.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    return {'notion_url':parent.get('url') or 'https://www.notion.so/'+compact_id(parent['id']),
            'proof_path':str(proof_path.resolve()),'attachments_verified':len(expected)}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--kind',required=True,choices=['company','industry'])
    ap.add_argument('--source-url',required=True)
    ap.add_argument('--pptx',required=True,type=Path)
    ap.add_argument('--pdf',required=True,type=Path)
    ap.add_argument('--request-id',required=True)
    a=ap.parse_args()
    proof=Path(__file__).with_name('state')/'decks'/f'{a.request_id}-notion.json'
    print(json.dumps(attach(Notion(),a.kind,a.source_url,a.pptx,a.pdf,a.request_id,proof),ensure_ascii=False))


if __name__=='__main__': main()
