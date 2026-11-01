# PRD Ref: §8.7 L · replay: 코세스 사용량/후처리 장애, 외부 생성·발송 없음
from datetime import date, datetime, timezone
import json
import sqlite3
from unittest.mock import Mock

import pytest

from src.collectors import drive_bootstrap as drive
from telegram_bridge import deck_runner, research_handoff as handoff, usage_notices as notices, bridge


def test_industry_reads_all_recent_publications_not_folder_date(tmp_path, monkeypatch):
    folder=tmp_path/'1. 산업분석/1. AI 반도체'
    for sub in ['260601','260930','261001']:
        (folder/sub).mkdir(parents=True)
    included=folder/'260601/2026-09-01_IR.pdf';included.write_bytes(b'published Sep, stored in older folder')
    excluded=folder/'261001/260701_과거.pdf';excluded.write_bytes(b'old publication in new folder')
    boundary=folder/'260930/260711_경계.pdf';boundary.write_bytes(b'exact 3 month boundary')
    unknown=folder/'261001/260230_오기.pdf';unknown.write_bytes(b'invalid date')
    monkeypatch.setattr(drive,'industry_folder',lambda *args:(folder,False))
    result=drive.bootstrap({'request_kind':'industry','target_name':'반도체'},root=tmp_path,today=date(2026,10,11))
    assert set(result['reused_sources'])=={str(included),str(boundary)}
    assert result['source_folder']==str(folder)
    assert result['industry_pdf_destination']==str(folder/'261001')
    assert str(unknown) in result['source_date_unverified']
    assert drive.source_cutoff(date(2026,5,31))==date(2026,2,28)


def test_claude_cannot_skip_codex_gap(tmp_path):
    package=tmp_path/'7-handoff.json'
    handoff.save_package(package,{'request_id':7,'facts':[], 'gaps':[
        {'id':'G1','topic':'고객사 전망','reason':'공식 IR 미열람','attempted_queries':['IR']}]},7)
    review=tmp_path/'A8-gap-review.json'
    data={'request_id':'A8','gaps':[]}
    review.write_text(json.dumps(data))
    result={'gap_review_path':str(review)}
    with pytest.raises(ValueError,match='COVERAGE'):handoff.validate_gap_review(result,'A8',package)
    data['gaps']=[{'id':'G1','searches':[{'query':'고객사 공식 IR 전망','outcome':'공개 IR 접근 실패'}],
                   'analysis_attempt':'공개 실적을 읽었지만 미공개 고객별 수주는 판단 불가', 'status':'unresolved','source_urls':[]}]
    review.write_text(json.dumps(data))
    handoff.validate_gap_review(result,'A8',package)
    data['gaps'][0]['searches']=[];review.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='ATTEMPT'):handoff.validate_gap_review(result,'A8',package)


def test_usage_waits_never_exhaust_failure_budget():
    for count in [1,4,99]:
        result=deck_runner.usage_retry_payload("You've hit your weekly limit",count,datetime.now(timezone.utc))
        assert result['status']=='pending' and result['attempts']==count-1 and result['completed_at'] is None


def test_usage_notifications_persist_cycles_without_duplicate(tmp_path,monkeypatch):
    from src.notify import listen
    monkeypatch.setattr(notices,'STATE',tmp_path/'usage.sqlite3')
    monkeypatch.setattr(listen,'allowed_chats',lambda:{'123'})
    client=Mock();client.token='8933940541:fixture'
    client.call.return_value={'result':{'message_id':55}}
    monkeypatch.setattr(notices,'TelegramClient',lambda **kwargs:client)
    owner={'source':'telegram','chat_id':123,'target_name':'코세스'}
    assert notices.usage_event('A7',owner,True,'Claude Code')['notification']=='sent'
    notices.usage_event('A7',owner,True,'Claude Code')
    assert client.call.call_count==1
    notices.usage_event('A7',owner,False,'Claude Code')
    notices.usage_event('A7',owner,False,'Claude Code')
    notices.usage_event('A7',owner,True,'Claude Code')
    assert client.call.call_count==3
    with sqlite3.connect(notices.STATE) as db:
        assert db.execute('SELECT count(*) FROM events').fetchone()[0]==3
    notices.usage_event('A9',{'source':'jarvis','chat_id':0},True,'Claude Code')
    assert client.call.call_count==3


def test_uncertain_usage_send_never_replays(tmp_path,monkeypatch):
    from src.notify import listen
    monkeypatch.setattr(notices,'STATE',tmp_path/'usage.sqlite3')
    monkeypatch.setattr(listen,'allowed_chats',lambda:{'123'})
    client=Mock();client.token='8933940541:fixture';client.call.side_effect=TimeoutError
    monkeypatch.setattr(notices,'TelegramClient',lambda **kwargs:client)
    owner={'source':'telegram','chat_id':123}
    assert notices.usage_event('C7',owner,True,'Codex')['notification']=='uncertain'
    notices.usage_event('C7',owner,True,'Codex')
    assert client.call.call_count==1


def test_new_claim_requires_file_first_completion(tmp_path,monkeypatch):
    monkeypatch.setattr(bridge,'STATE',tmp_path/'queue.sqlite3')
    db=bridge.connect()
    db.execute("INSERT INTO jobs(id,company,code,raw_text,chat_id,status) VALUES(7,'코세스','089890','코세스',123,'working')")
    db.commit();bridge.ensure_checkpoint(db,7)
    with pytest.raises(ValueError,match='FILE_FIRST_USE_COMPLETE_CODEX'):
        bridge.deliver(db,7,'https://www.notion.so/'+'a'*32,'반도체')
    bridge.save_handoff(db,7,{'request_id':7,'facts':[],'gaps':[]})
    db.close()


@pytest.mark.parametrize('alive,expected',[(True,False),(None,False),(False,True)])
def test_orphan_recovery_requires_both_processes_proven_dead(tmp_path,monkeypatch,alive,expected):
    monkeypatch.setattr(deck_runner,'STATE',tmp_path)
    identity='9cbc0129-97a3-446d-aed2-b65d19925aa0'
    (tmp_path/'D5-session.json').write_text(json.dumps({'session_id':identity}))
    (tmp_path/f'{identity}-execution.json').write_text(json.dumps({'worker_pid':123,'claude_pid':456}))
    monkeypatch.setattr(deck_runner,'process_alive',lambda pid:alive)
    client=Mock()
    client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data=[
        {'id':5,'mode':'deck','status':'working','attempts':1}]
    client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data=[{'id':5}]
    actual=deck_runner.recover_interrupted(client)
    assert bool(actual)==expected
    if expected:assert actual['status']=='pending' and actual['error']=='INTERRUPTED'
    else:client.table.return_value.update.assert_not_called()


def test_crash_after_usage_checkpoint_reuses_wait_without_losing_attempts(tmp_path,monkeypatch):
    monkeypatch.setattr(deck_runner,'STATE',tmp_path)
    identity='9cbc0129-97a3-446d-aed2-b65d19925aa0'
    (tmp_path/'A5-session.json').write_text(json.dumps({'session_id':identity}))
    (tmp_path/f'{identity}-execution.json').write_text(json.dumps({'worker_pid':123,'claude_pid':456}))
    saved=deck_runner.usage_retry_payload("You've hit your session limit",1,datetime.now(timezone.utc))
    (tmp_path/'A5.json').write_text(json.dumps(saved))
    monkeypatch.setattr(deck_runner,'process_alive',lambda pid:False)
    client=Mock()
    client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data=[
        {'id':5,'mode':'analysis','status':'working','attempts':1}]
    client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data=[{'id':5}]
    result=deck_runner.recover_interrupted(client)
    assert result['error']=='USAGE' and result['attempts']==0 and result['retry_after']==saved['retry_after']
