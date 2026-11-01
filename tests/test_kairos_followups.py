# PRD Ref: §8.7 K · Actual authorization, race and storage contracts.
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import json
import zipfile

import pytest

from src.notify import kairos_followups as f, listen
from telegram_bridge import attach_presentation as a, deck_runner as d


@pytest.fixture
def owner():
    return {'update_id':9,'user_id':111,'chat_id':111,'source':'telegram','status':'sent',
            'request_kind':'industry','industry':'반도체','notion_url':'https://www.notion.so/'+'a'*32,'telegram_message_id':45}


@pytest.fixture
def callback():
    return {'id':'cb','data':'kairos:analysis:9','from':{'id':111,'is_bot':False},
            'message':{'message_id':45,'chat':{'id':111,'type':'private'},'from':{'id':8933940541,'is_bot':True}}}


@pytest.fixture(autouse=True)
def state(tmp_path,monkeypatch):
    monkeypatch.setattr(f,'STATE',tmp_path/'followups.sqlite3')


@pytest.mark.parametrize('change', ['other_user','group','jarvis','wrong_message','foreign_bot','not_ready','other_chat'])
def test_forged_or_unowned_callbacks_cannot_queue(owner,callback,change):
    if change=='other_user': callback['from']['id']=222
    if change=='group': callback['message']['chat']['type']='group'
    if change=='jarvis': owner['source']='jarvis'
    if change=='wrong_message': callback['message']['message_id']=46
    if change=='foreign_bot': callback['message']['from']['id']=8605695587
    if change=='not_ready': owner['status']='working'
    if change=='other_chat': callback['message']['chat']['id']=222
    assert not f.authorize(callback,owner,'analysis',{'111','222'})


def test_actual_owner_and_message_allowed(owner,callback):
    assert f.authorize(callback,owner,'analysis',{'111'})
    assert not f.authorize(callback,owner,'deck',{'111'})
    with f.connect() as db:
        db.execute("INSERT INTO notices VALUES(1,9,'analysis',111,'sent','sent',45,NULL)")
    assert f.authorize(callback,owner,'deck',{'111'})


@pytest.mark.parametrize('kind',['company','industry'])
def test_repeat_click_reuses_completed_job_without_insert(owner,monkeypatch,kind):
    owner['request_kind']=kind
    existing={'id':1,'mode':'analysis','status':'sent'}
    monkeypatch.setattr(f,'latest_job',lambda *args:existing)
    client=Mock();monkeypatch.setattr(f,'get_client',lambda:client)
    assert f.enqueue_followup(owner,'analysis')==existing
    client.assert_not_called()


def test_unique_index_race_reuses_winner(owner,monkeypatch):
    class Conflict(Exception): code='23505'
    winner={'id':1,'mode':'analysis','status':'pending'}
    calls=iter([None,winner])
    monkeypatch.setattr(f,'latest_job',lambda *args:next(calls))
    client=Mock();client.table.return_value.insert.return_value.execute.side_effect=Conflict()
    monkeypatch.setattr(f,'get_client',lambda:client)
    assert f.enqueue_followup(owner,'analysis')==winner


def test_ppt_cannot_skip_analysis(owner,monkeypatch):
    monkeypatch.setattr(f,'latest_job',lambda *args:{'status':'working'})
    assert f.enqueue_followup(owner,'deck')['status']=='rejected'


def test_callback_replay_and_poll_error_not_consumed(owner,callback,monkeypatch):
    client=Mock(token='8933940541:fixture')
    client.call.return_value={'result':[{'update_id':99,'callback_query':callback}]}
    monkeypatch.setattr(f,'handle_callback',Mock(side_effect=RuntimeError('DB unavailable')))
    listen.poll_once(client,analyze=False,universe={'005930':'삼성전자'},industries={'반도체'},chats={'111'})
    assert client.call.call_count==1  # no confirm getUpdates offset


def test_expired_callback_ack_does_not_lose_durable_job(owner,callback,monkeypatch):
    monkeypatch.setattr(f,'request_row',lambda *x:owner)
    queued=Mock(return_value={'id':1,'status':'pending','mode':'analysis'})
    monkeypatch.setattr(f,'enqueue_followup',queued)
    client=Mock(token='8933940541:fixture');client.call.side_effect=RuntimeError('expired callback')
    result=f.handle_callback(client,callback,{'111'})
    assert result['status']=='pending' and result['acknowledged'] is False
    queued.assert_called_once_with(owner,'analysis')


def test_completion_notification_exactly_once(owner,monkeypatch):
    job={'id':1,'mode':'analysis','status':'sent','notion_url':owner['notion_url']}
    f.remember(job,owner)
    dbclient=Mock();dbclient.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value=SimpleNamespace(data=[job])
    monkeypatch.setattr(f,'get_client',lambda:dbclient)
    monkeypatch.setattr(f,'request_row',lambda *x:owner)
    monkeypatch.setattr(listen,'allowed_chats',lambda:{'111'})
    tg=Mock(token='8933940541:fixture');tg.call.return_value={'result':{'message_id':56}}
    monkeypatch.setattr(f,'TelegramClient',lambda **kw:tg)
    assert f.flush_notifications()['sent']==1
    assert f.flush_notifications()['sent']==0
    assert tg.call.call_args.args[1]['reply_markup']['inline_keyboard'][1][0]['callback_data']=='kairos:deck:9'
    buttons = tg.call.call_args.args[1]['reply_markup']['inline_keyboard']
    assert all('kairos:analysis:' not in button.get('callback_data', '') for row in buttons for button in row)


def test_auto_analysis_start_without_approval_and_ppt_blocked_until_complete(owner, callback, monkeypatch):
    owner.update(status='working', stage='claude', notion_url=None)
    job={'id':1,'mode':'analysis','status':'pending'}
    f.remember(job,owner)
    monkeypatch.setattr(listen,'allowed_chats',lambda:{'111'})
    tg=Mock(token='8933940541:fixture');tg.call.return_value={'result':{'message_id':57}}
    assert f.notify_progress(job,owner,tg)==1
    assert 'reply_markup' not in tg.call.call_args.args[1]
    callback['data']='kairos:deck:9'
    assert not f.authorize(callback,owner,'deck',{'111'})


def test_ambiguous_send_not_retried(owner,monkeypatch):
    job={'id':1,'mode':'analysis','status':'sent','notion_url':owner['notion_url']};f.remember(job,owner)
    client=Mock();client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value=SimpleNamespace(data=[job])
    monkeypatch.setattr(f,'get_client',lambda:client);monkeypatch.setattr(f,'request_row',lambda *x:owner)
    monkeypatch.setattr(listen,'allowed_chats',lambda:{'111'})
    tg=Mock(token='8933940541:fixture');tg.call.side_effect=TimeoutError()
    monkeypatch.setattr(f,'TelegramClient',lambda **kw:tg)
    f.flush_notifications();f.flush_notifications();assert tg.call.call_count==1


def test_jarvis_never_gets_heimdallr_followup_message(owner,monkeypatch):
    job={'id':1,'mode':'analysis','status':'sent','notion_url':owner['notion_url']};f.remember(job,owner)
    owner['source']='jarvis'
    client=Mock();client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value=SimpleNamespace(data=[job])
    monkeypatch.setattr(f,'get_client',lambda:client);monkeypatch.setattr(f,'request_row',lambda *x:owner)
    tg=Mock();monkeypatch.setattr(f,'TelegramClient',tg)
    assert f.flush_notifications()['sent']==0;tg.assert_not_called()


def test_receipt_then_real_start_once_each(owner,monkeypatch):
    job={'id':1,'mode':'analysis','status':'pending'};f.remember(job,owner)
    monkeypatch.setattr(listen,'allowed_chats',lambda:{'111'})
    tg=Mock(token='8933940541:fixture');tg.call.return_value={'result':{'message_id':57}}
    assert f.notify_progress(job,owner,tg)==1
    assert f.notify_progress(job,owner,tg)==0
    assert '실행 대기' in tg.call.call_args.args[1]['text']
    job['status']='working'
    assert f.notify_progress(job,owner,tg)==1
    assert '시작했습니다' in tg.call.call_args.args[1]['text']
    assert f.notify_progress(job,owner,tg)==0 and tg.call.call_count==2


@pytest.mark.parametrize('event',['started','completed'])
def test_codex_milestones_are_new_once_only_messages(owner,monkeypatch,event):
    owner.update(status='working',stage='claude')
    monkeypatch.setattr(listen,'allowed_chats',lambda:{'111'})
    tg=Mock(token='8933940541:fixture');tg.call.return_value={'result':{'message_id':60}}
    assert f.notify_codex(owner,event,tg)==1
    assert f.notify_codex(owner,event,tg)==0
    tg.call.assert_called_once()
    assert tg.call.call_args.args[0]=='sendMessage'
    assert 'Codex 분석' in tg.call.call_args.args[1]['text']
    assert 'reply_markup' not in tg.call.call_args.args[1]


def test_codex_uncertain_notice_and_jarvis_are_not_sent_again(owner,monkeypatch):
    owner['status']='working'
    monkeypatch.setattr(listen,'allowed_chats',lambda:{'111'})
    tg=Mock(token='8933940541:fixture');tg.call.side_effect=TimeoutError()
    assert f.notify_codex(owner,'started',tg)==0
    assert f.notify_codex(owner,'started',tg)==0
    owner['source']='jarvis'
    assert f.notify_codex(owner,'completed',tg)==0
    tg.call.assert_called_once()


def test_progress_ambiguous_send_not_replayed(owner,monkeypatch):
    job={'id':1,'mode':'analysis','status':'working'};f.remember(job,owner)
    monkeypatch.setattr(listen,'allowed_chats',lambda:{'111'})
    tg=Mock(token='8933940541:fixture');tg.call.side_effect=TimeoutError()
    assert f.notify_progress(job,owner,tg)==0
    assert f.notify_progress(job,owner,tg)==0 and tg.call.call_count==1


def test_jarvis_and_unwatched_jobs_have_no_start_message(owner,monkeypatch):
    job={'id':1,'mode':'analysis','status':'working'}
    tg=Mock(token='8933940541:fixture')
    assert f.notify_progress(job,owner,tg)==0
    f.remember(job,owner);owner['source']='jarvis'
    assert f.notify_progress(job,owner,tg)==0
    tg.call.assert_not_called()


@pytest.mark.parametrize('kind',['company','industry'])
def test_actual_parent_and_attachment_readback_idempotency(tmp_path,kind):
    ppt=tmp_path/'real.pptx'
    with zipfile.ZipFile(ppt,'w') as z:z.writestr('ppt/presentation.xml','<presentation/>')
    pdf=tmp_path/'real.pdf';pdf.write_bytes(b'%PDF-1.7 fixture')
    sourceid='a'*32;parentid='b'*32;rootid=a.PARENTS[kind]
    class Native:
        def __init__(self):self.blocks=[];self.uploads=0
        def call(self,method,path,**kw):
            if method=='GET':
                i=path.split('/')[-1]
                return {'id':i,'url':'https://www.notion.so/'+i,'parent':{'page_id':parentid if i==sourceid else rootid}}
            for b in kw['json']['children']:
                block=deepcopy(b);t=b['type'];block[t]['type']='file';block[t]['file']={'url':'https://secure.notion-static.com/actual'}
                self.blocks.append(block)
            return {}
        def children(self,*x):return self.blocks
        def upload(self,*x):self.uploads+=1;return 'actual-upload-id'
    n=Native();proof=tmp_path/'proof.json';url='https://www.notion.so/'+sourceid
    result=a.attach(n,kind,url,ppt,pdf,'D1',proof)
    assert result['attachments_verified']==2 and n.uploads==2
    a.attach(n,kind,url,ppt,pdf,'D1',proof);assert n.uploads==2
    d.validate_deck_readback({**result,'drive_dir':str(tmp_path),'files':[str(ppt),str(pdf)]},'D1',kind)
    ppt.write_bytes(ppt.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='DECK_READBACK_INVALID'):
        d.validate_deck_readback({**result,'drive_dir':str(tmp_path),'files':[str(ppt),str(pdf)]},'D1',kind)


def test_wrong_industry_parent_cannot_upload():
    n=Mock()
    n.call.side_effect=[{'parent':{'page_id':'b'*32}},{'parent':{'page_id':a.PARENTS['company']}}]
    with pytest.raises(ValueError,match='NOTION_TARGET_PARENT_INVALID'):
        a.verified_parent(n,'https://www.notion.so/'+'a'*32,'industry')
    n.upload.assert_not_called()


def test_large_ppt_upload_completes_every_part_before_attach(tmp_path):
    p=tmp_path/'large.pptx'
    with p.open('wb') as stream: stream.truncate(21*1024*1024)
    calls=[]
    def call(method,path,**kw):
        if path=='/file_uploads':
            assert kw['json']['mode']=='multi_part' and kw['json']['number_of_parts']==3
            return {'id':'upload'}
        if path.endswith('/send'):
            calls.append((kw['data']['part_number'],len(kw['files']['file'][1])))
            return {'status':'pending'}
        assert path.endswith('/complete') and len(calls)==3
        return {'status':'uploaded'}
    n=object.__new__(a.Notion);n.call=call
    assert n.upload(p,a.PPTX_MIME)=='upload'
    assert calls==[('1',10*1024*1024),('2',10*1024*1024),('3',1024*1024)]


def test_industry_deck_prompt_inherits_analysis_and_industry_contract(monkeypatch):
    monkeypatch.setattr(d,'local_context',lambda *a:(None,None,'G:/industry'))
    p=d.build_prompt({'id':4,'mode':'deck','analysis':{'update_id':9,'request_kind':'industry','market':'KR','industry':'반도체','status':'sent','notion_url':'https://www.notion.so/'+'a'*32},'claude_analysis':{'status':'sent','analysis_md':'G:/industry/analysis.md','notion_url':'https://www.notion.so/'+'c'*32}})
    assert '--kind "industry"' in p and '--analysis-md "G:/industry/analysis.md"' in p
    assert 'presentation_workflow.md' in p
