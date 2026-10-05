# PRD Ref: §8.7 H · I
"""Claude modes, local source handoff and completion validation. No live analysis writes."""
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from telegram_bridge import bridge, deck_runner as runner
from src.config.constants import KAIROS_ANALYSIS_TIMEOUT_SECONDS, KAIROS_DECK_TIMEOUT_SECONDS


def job(mode='analysis', kind='company'):
    return {'id':80, 'request_id':-7, 'mode':mode, 'attempts':1, 'analysis':{
        'update_id':-7,'company_name':'삼성전자' if kind=='company' else None,
        'target_name':'삼성전자' if kind=='company' else '반도체', 'industry':'반도체',
        'code':'005930' if kind=='company' else None,'market':'KR','request_kind':kind,
        'status':'sent','notion_url':'https://www.notion.so/'+'a'*32,
        'drive_folder_name':'1. AI 반도체'}}


def test_local_handoff_uses_request_id_not_claude_job_id(tmp_path,monkeypatch):
    queue=tmp_path/'queue.sqlite3'
    monkeypatch.setattr(bridge,'STATE',queue)
    db=bridge.connect()
    db.execute("INSERT INTO jobs(id,code,company,target_name,request_kind,raw_text,chat_id,status) VALUES(-7,'005930','삼성전자','삼성전자','company','삼성전자',0,'working')")
    db.commit();db.close()
    ledger=bridge.checkpoint_path(-7)
    ledger.parent.mkdir();ledger.write_text('actual sources',encoding='utf-8')
    sources=tmp_path/'sources/-7';sources.mkdir(parents=True)
    ledger.with_suffix('.drive.json').write_text(json.dumps({'folder':str(tmp_path/'drive')}),encoding='utf-8')
    prompt=runner.build_prompt(job())
    assert '--ledger '+json.dumps(str(ledger.resolve()),ensure_ascii=False) in prompt
    assert '--sources '+json.dumps(str(sources.resolve()),ensure_ascii=False) in prompt
    assert '--request-id "A80"' in prompt and '--codex ' in prompt
    assert runner.local_context(80)==(None,None,None)


def test_missing_context_omits_options_and_industry_target(monkeypatch):
    monkeypatch.setattr(runner,'local_context',lambda request_id:(None,None,None))
    prompt=runner.build_prompt(job(kind='industry'))
    assert '--kind "industry"' in prompt and '반도체' in prompt
    assert '--ledger' not in prompt and '--sources' not in prompt and '--code ' not in prompt
    assert '1. AI 반도체' in prompt


@pytest.mark.parametrize('prior,expected',[(None,False),({'status':'failed'},False),({'status':'sent','analysis_md':'G:/deep.md','notion_url':'https://www.notion.so/deep'},True)])
def test_deck_uses_completed_claude_analysis(monkeypatch,prior,expected):
    monkeypatch.setattr(runner,'local_context',lambda request_id:(None,None,None))
    data=job('deck');data['claude_analysis']=prior
    prompt=runner.build_prompt(data)
    assert ('--analysis-md' in prompt)==expected
    assert ('--claude-notion' in prompt)==expected
    assert '--request-id "D80"' in prompt


def analysis_result(tmp_path):
    md=tmp_path/'analysis.md';md.write_text('completed analysis',encoding='utf-8')
    return {'status':'ok','mode':'analysis','request_id':'A80','notion_url':'https://www.notion.so/'+'a'*32,
        'drive_dir':str(tmp_path),'files':[str(md)],'analysis_md':str(md)}


def test_analysis_success_needs_only_real_drive_md(tmp_path):
    runner.validate_success(analysis_result(tmp_path),'analysis')
    with pytest.raises(ValueError,match='FILES_INCOMPLETE'):
        runner.validate_success(analysis_result(tmp_path),'deck')


@pytest.mark.parametrize('invalid',['relative','missing','outside','empty'])
def test_analysis_md_must_be_absolute_nonempty_and_contained(tmp_path,invalid):
    result=analysis_result(tmp_path)
    if invalid=='relative':result['analysis_md']='analysis.md'
    elif invalid=='missing':result['analysis_md']=str(tmp_path/'missing.md')
    elif invalid=='outside':result['analysis_md']=str(tmp_path.parent/'outside.md')
    else:(tmp_path/'analysis.md').write_text('')
    with pytest.raises(ValueError):runner.validate_success(result,'analysis')


def test_fallback_distinguishes_mode_and_timestamp(tmp_path):
    work=tmp_path/'work/target';work.mkdir(parents=True)
    result=work/'result.json';result.write_text(json.dumps({'status':'ok','request_id':'A80'}))
    assert runner.result_file(tmp_path,80,0,'analysis')['request_id']=='A80'
    assert runner.result_file(tmp_path,80,0,'deck') is None
    assert runner.result_file(tmp_path,80,result.stat().st_mtime+1,'analysis') is None


@pytest.mark.parametrize('pick',[{'name':'삼성전자','market':'KR','code':'005930'},{'name':'NVIDIA','market':'US','code':'NVDA'},None])
def test_top_pick_contract(pick):
    assert runner.validate_top_pick(pick)==pick


@pytest.mark.parametrize('pick',[{}, {'name':'x','market':'KR','code':'NVDA'}, {'name':'x','market':'US','code':'NVDA;bad'}])
def test_top_pick_invalid(pick):
    with pytest.raises(ValueError,match='TOP_PICK'):runner.validate_top_pick(pick)


def worker_fixture(tmp_path,monkeypatch,data,output):
    (tmp_path/'SKILL.md').write_text('installed skill')
    monkeypatch.setattr(runner,'SKILL',tmp_path)
    monkeypatch.setattr(runner,'STATE',tmp_path/'state')
    monkeypatch.setattr(runner.shutil,'which',lambda *a:'claude.exe')
    monkeypatch.setattr(runner.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=json.dumps({'loggedIn':True,'authMethod':'claude.ai'})))
    monkeypatch.setattr(runner,'local_context',lambda request_id:(None,None,None))
    client=Mock();client.rpc.return_value.execute.return_value.data=data
    client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data=[{'id':80}]
    monkeypatch.setattr(runner,'get_client',lambda:client)
    seen=[]
    def run(args,timeout):
        seen.append((args,timeout));return SimpleNamespace(returncode=0,stdout=json.dumps(output),stderr='')
    monkeypatch.setattr(runner,'run_claude',run)
    return seen


def test_analysis_worker_persists_verified_md_and_top_pick(tmp_path,monkeypatch):
    result=analysis_result(tmp_path);result['top_pick']={'name':'삼성전자','market':'KR','code':'005930'}
    seen=worker_fixture(tmp_path,monkeypatch,job(kind='industry'),result)
    actual=runner.run_once()
    assert actual['status']=='sent' and actual['top_pick']==result['top_pick']
    assert actual['analysis_md']==result['analysis_md'] and seen[0][1]==KAIROS_ANALYSIS_TIMEOUT_SECONDS
    assert (tmp_path/'state/A80.json').is_file() and not (tmp_path/'state/D80.json').exists()


def test_wrong_mode_output_cannot_mark_sent(tmp_path,monkeypatch):
    result=analysis_result(tmp_path);result['request_id']='D80'
    worker_fixture(tmp_path,monkeypatch,job(),result)
    assert runner.run_once()['error']=='DECK_RESULT_WRONG_REQUEST'


def test_deck_timeout_and_company_pick_not_stored(tmp_path,monkeypatch):
    result=analysis_result(tmp_path);result.update(mode='deck',request_id='D80')
    for name in ['deck.pptx','deck.pdf']:
        (tmp_path/name).write_bytes(b'complete');result['files'].append(str(tmp_path/name))
    seen=worker_fixture(tmp_path,monkeypatch,job('deck'),result)
    actual=runner.run_once()
    assert actual['status']=='sent' and 'top_pick' not in actual and seen[0][1]==KAIROS_DECK_TIMEOUT_SECONDS


def test_invalid_industry_top_pick_cannot_mark_sent(tmp_path,monkeypatch):
    result=analysis_result(tmp_path)
    result['top_pick']={'name':'unknown','market':'KR','code':'INVALID'}
    worker_fixture(tmp_path,monkeypatch,job(kind='industry'),result)
    actual=runner.run_once()
    assert actual['status']=='failed' and actual['error']=='TOP_PICK_INVALID'
