# PRD Ref: §8.7 G. Replay pure contracts and bridge/runner effects; no Notion writes.
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from src.collectors import drive_bootstrap as drive
from src.collectors.sec_edgar import archive_base, filing_rows, resolve_us
from src.notify import listen
from src.notify.kairos_requests import AnalysisTarget, enqueue
from telegram_bridge import bridge, deck_runner as deck
from telegram_bridge.notion_readback import validate_readback


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, 'STATE', tmp_path / 'queue.sqlite3')
    conn = bridge.connect()
    yield conn
    conn.close()


def jarvis_job(db, status='working', kind='company'):
    db.execute("INSERT INTO jobs(id,code,company,raw_text,chat_id,status,source,request_kind,target_name,telegram_message_id) VALUES(-1,'005930','삼성전자','삼성전자',0,?,'jarvis',?,'반도체',999)", (status, kind))
    db.commit()


def no_telegram(*args, **kwargs):
    raise AssertionError('JARVIS sent a Heimdallr Telegram message')


def proof(job=-1, kind='company'):
    parent = '3d29c770aa6180469edceca9fb363529' if kind == 'company' else '3e69c770aa61808aa0e8e136d62dc59a'
    return {'request_id': job, 'checked_at': datetime.now(timezone.utc).isoformat(),
            'page': {'id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'archived': False},
            'blocks': {'has_more': False, 'results': [{'id': 'b', 'type': 'paragraph'}]},
            'ancestors': [{'id': parent}], 'template_verified': True,
            'sources_verified': True, 'target_verified': True}


def test_jarvis_sync_checks_negative_id_and_zero_owner(db, monkeypatch):
    monkeypatch.setattr(bridge, 'allowed_chats', lambda: set())
    monkeypatch.setattr(bridge, 'verify_bot', no_telegram)
    row = {'update_id': -1, 'chat_id': 0, 'user_id': 0, 'source': 'jarvis', 'market': 'US',
           'ticker': 'NVDA', 'company_name': 'NVIDIA', 'target_name': 'NVIDIA',
           'request_kind': 'company', 'raw_text': 'NVIDIA', 'created_at': '2026-10-05T00:00:00Z'}
    monkeypatch.setattr(bridge, 'select_all', lambda *a, **k: [row, {**row, 'update_id': 10},
        {**row, 'update_id': -2, 'user_id': 1}])
    assert bridge.sync_pending(db) == 1
    assert bridge.sync_pending(db) == 0
    local = dict(db.execute('SELECT * FROM jobs').fetchone())
    assert local['code'] == '' and local['ticker'] == 'NVDA' and local['market'] == 'US'


def test_jarvis_progress_writes_database_without_bot(db, monkeypatch):
    jarvis_job(db)
    calls = []
    monkeypatch.setattr(bridge, 'change_remote', lambda *a, **k: calls.append(k) or True)
    monkeypatch.setattr(bridge, 'TelegramClient', no_telegram)
    result = bridge.set_progress(db, -1, 'industry')
    assert result['telegram_updated'] is False
    assert calls[0]['stage'] == 'industry' and calls[0]['stage_updated_at']


def test_remote_progress_failure_keeps_local_stage(db, monkeypatch):
    jarvis_job(db)
    monkeypatch.setattr(bridge, 'change_remote', lambda *a, **k: False)
    with pytest.raises(RuntimeError):
        bridge.set_progress(db, -1, 'industry')
    assert db.execute('SELECT progress_stage FROM jobs').fetchone()[0] is None


def test_jarvis_fail_is_code_and_never_telegram(db, monkeypatch):
    jarvis_job(db)
    calls = []
    monkeypatch.setattr(bridge, 'change_remote', lambda *a, **k: calls.append(k) or True)
    monkeypatch.setattr(bridge, 'TelegramClient', no_telegram)
    assert bridge.fail(db, -1, 'NOTION_VERIFY')['status'] == 'failed'
    assert calls[0]['error'] == 'NOTION_VERIFY'


def test_jarvis_deliver_requires_readback_and_never_telegram(db, monkeypatch):
    jarvis_job(db)
    monkeypatch.setattr(bridge, 'change_remote', lambda *a, **k: True)
    monkeypatch.setattr(bridge, 'TelegramClient', no_telegram)
    url = 'https://www.notion.so/' + 'a' * 32
    with pytest.raises(RuntimeError, match='READBACK'):
        bridge.deliver(db, -1, url, '반도체')
    path = bridge.STATE.parent / 'checkpoints/-1-notion.json'
    path.parent.mkdir()
    path.write_text(json.dumps(proof()), encoding='utf-8')
    assert bridge.deliver(db, -1, url, '반도체')['status'] == 'sent'
    assert db.execute('SELECT status FROM jobs').fetchone()[0] == 'sent'


@pytest.mark.parametrize('change', [
    {'request_id': -2}, {'ancestors': []}, {'sources_verified': False},
    {'blocks': {'has_more': True, 'results': [{'id': 'b'}]}},
    {'page': {'id': 'b' * 32}}, {'checked_at': (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}
])
def test_readback_rejects_wrong_or_incomplete_evidence(tmp_path, change):
    path = tmp_path / 'notion.json'
    path.write_text(json.dumps({**proof(), **change}), encoding='utf-8')
    with pytest.raises(ValueError):
        validate_readback(-1, 'https://www.notion.so/' + 'a' * 32, 'company', path)


def test_jarvis_cannot_await_folder_reply(db, monkeypatch):
    jarvis_job(db, kind='industry')
    monkeypatch.setattr(bridge, 'TelegramClient', no_telegram)
    with pytest.raises(RuntimeError, match='BOOTSTRAP'):
        bridge.ask_folder(db, -1, '3. K-엔터', 'https://drive.google.com/drive/folders/abcdef')


@pytest.mark.parametrize(('name','sector','expected'), [
    ('AI · 반도체','','1. AI 반도체'), ('1. AI_반도체','','1. AI 반도체'),
    ('엔터','','3. K-엔터'), ('IT','디스플레이 제조','8. OLED'),
    ('IT','네트워크','17. 네트워크'), ('화장품_미용기기','미용 의료기기','4. 미용_의료기기'),
    ('소비재','의류','13. 의류'), ('IT','','6. IT'),
])
def test_industry_mapping_exact_and_overrides(name, sector, expected):
    assert drive.mapped_folder(name, sector) == expected


def test_industry_new_folder_number_and_yaml_persist(tmp_path, monkeypatch):
    mapping = tmp_path / 'folders.yaml'
    mapping.write_text('folders: {}\noverrides: {}\n', encoding='utf-8')
    monkeypatch.setattr(drive, 'MAPPING', mapping)
    root = tmp_path / 'industries'
    root.mkdir()
    (root / '18. ETF').mkdir()
    first, created = drive.industry_folder('양자컴퓨터', root, date(2026,10,5))
    assert created and first.name == '19. 양자컴퓨터'
    assert (first / '261005').is_dir()
    assert yaml.safe_load(mapping.read_text(encoding='utf-8'))['folders']['양자컴퓨터'] == first.name
    second, created = drive.industry_folder('양자컴퓨터', root, date(2026,10,5))
    assert not created and second == first
    assert not mapping.with_suffix('.lock').exists()


def test_recent_sources_use_calendar_months_and_old_style_us(tmp_path):
    folder = tmp_path / 'NVDA'
    folder.mkdir()
    for name in ('260705_NVDA.pdf', '260704_NVDA.pdf', '261006_NVDA.pdf', 'undated_old_report.pdf'):
        (folder / name).write_bytes(b'source')
    old_style = tmp_path / '260801_NVDA.pdf'
    old_style.write_bytes(b'source')
    assert {p.name for p in drive.recent_sources(folder,date(2026,10,5),'NVDA')} == {
        '260705_NVDA.pdf','260801_NVDA.pdf'}
    assert drive.source_cutoff(date(2026,5,31)) == date(2026,2,28)


def test_company_existing_recent_source_skips_network(tmp_path):
    root = tmp_path
    folder = root / '2. 기업분석/국내/삼성전자'
    folder.mkdir(parents=True)
    (folder / '260901_삼성전자_보고서.pdf').write_bytes(b'original')
    result = drive.bootstrap({'request_kind':'company','market':'KR','company':'삼성전자','code':'005930'}, root=root, today=date(2026,10,5))
    assert len(result['reused_sources']) == 1 and result['files'] == []


def test_us_resolves_only_unique_exact_sec_catalog():
    catalog = [{'ticker':'NVDA','name':'NVIDIA CORP','cik':'0001045810','exchange':'Nasdaq'},
               {'ticker':'GOOG','name':'Alphabet Inc.','cik':'0001652044','exchange':'Nasdaq'},
               {'ticker':'GOOGL','name':'Alphabet Inc.','cik':'0001652044','exchange':'Nasdaq'}]
    assert resolve_us('엔비디아',catalog)['ticker'] == 'NVDA'
    assert resolve_us('NVIDIA CORP',catalog)['ticker'] == 'NVDA'
    assert resolve_us('NVID',catalog) is None
    assert resolve_us('Alphabet Inc.',catalog) is None


def test_sec_parallel_array_truncation_is_rejected():
    with pytest.raises(ValueError,match='MISMATCH'):
        filing_rows({'form':['10-Q'], 'filingDate':[], 'accessionNumber':['a'], 'primaryDocument':['b']})
    assert archive_base('0001045810','0001045810-26-000001').endswith('/1045810/000104581026000001/')


def test_us_enqueue_has_no_krx_code(monkeypatch):
    client = Mock()
    monkeypatch.setattr('src.notify.kairos_requests.get_client', lambda: client)
    enqueue(1,{'chat':{'id':111},'from':{'id':111},'text':'NVDA'},
            AnalysisTarget('company','NVIDIA',market='US',ticker='NVDA'))
    payload = client.table.return_value.insert.call_args[0][0]
    assert payload['code'] is None and payload['ticker'] == 'NVDA' and payload['market'] == 'US'


def test_us_telegram_direct_input_is_enqueued(monkeypatch):
    monkeypatch.setattr(listen,'answer_drive_folder_confirmation',lambda *a:None)
    monkeypatch.setattr('src.collectors.sec_edgar.resolve_us',lambda text: {'name':'NVIDIA','ticker':'NVDA'})
    seen=[]
    monkeypatch.setattr(listen,'enqueue',lambda *a: seen.append(a[2]) or True)
    monkeypatch.setattr(listen,'record_receipt',lambda *a:None)
    client=Mock()
    client.send_message.return_value={'result':{'message_id':1}}
    msg={'chat':{'type':'private','id':111},'from':{'id':111},'text':'NVDA'}
    result=listen.handle_message(client,msg,{},analyze=False,chats={'111'},update_id=1)
    assert result['result']=='분석 접수' and seen[0].market=='US'


def test_deck_wrapper_result_and_files(tmp_path):
    directory=tmp_path
    for name in ('deck.pdf','deck.pptx','note.md'):
        (directory/name).write_bytes(b'complete')
    payload={'status':'ok','notion_url':'https://www.notion.so/'+'a'*32,
             'drive_dir':str(directory),'files':['deck.pdf','deck.pptx','note.md']}
    assert deck.parse_result(json.dumps({'result':'log\n'+json.dumps(payload)}))==payload
    deck.validate_success(payload)
    (directory/'deck.pdf').unlink()
    with pytest.raises(ValueError,match='FILE_MISSING'):
        deck.validate_success(payload)


def test_deck_fallback_only_same_fresh_request(tmp_path):
    work=tmp_path/'work/261005_target'
    work.mkdir(parents=True)
    (work/'result.json').write_text(json.dumps({'status':'ok','request_id':'D10'}),encoding='utf-8')
    assert deck.result_file(tmp_path,11,0) is None
    assert deck.result_file(tmp_path,10,0)['request_id']=='D10'


@pytest.mark.parametrize('attempts,expected',[(1,'pending'),(3,'pending'),(4,'failed')])
def test_deck_usage_retry_budget_and_manifest(tmp_path,monkeypatch,attempts,expected):
    (tmp_path/'SKILL.md').write_text('skill',encoding='utf-8')
    monkeypatch.setattr(deck,'SKILL',tmp_path)
    monkeypatch.setattr(deck,'STATE',tmp_path/'state')
    monkeypatch.setattr(deck.shutil,'which',lambda *a:'claude.exe')
    monkeypatch.setattr(deck.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0,stdout=json.dumps({'loggedIn':True,'authMethod':'claude.ai'})))
    monkeypatch.setattr(deck,'run_claude',lambda *a,**k:SimpleNamespace(returncode=1,stdout='You have hit your usage limit',stderr=''))
    client=Mock()
    client.rpc.return_value.execute.return_value.data={'id':10,'attempts':attempts,'analysis':{
        'company_name':'삼성전자','code':'005930','market':'KR','notion_url':'https://www.notion.so/'+'a'*32,
        'request_kind':'company','status':'sent'}}
    client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data=[{'id':10}]
    monkeypatch.setattr(deck,'get_client',lambda:client)
    result=deck.run_once()
    assert result['status']==expected
    if expected=='pending':
        delay=datetime.fromisoformat(result['retry_after'])-datetime.now(timezone.utc)
        assert timedelta(minutes=29)<delay<timedelta(minutes=31)
    assert (tmp_path/'state/D10.json').is_file()


def test_subscription_cli_removes_api_billing(monkeypatch):
    from src.utils.env import subscription_cli_env
    monkeypatch.setenv('ANTHROPIC_API_KEY','fixture')
    monkeypatch.setenv('ANTHROPIC_BASE_URL','fixture')
    env=subscription_cli_env()
    assert 'ANTHROPIC_API_KEY' not in env and 'ANTHROPIC_BASE_URL' not in env


def test_sql_runtime_budgets_match_constants():
    from src.config.constants import KAIROS_JARVIS_MAX_OPEN, KAIROS_REUSE_DAYS
    sql = Path("docs/migrations/kairos_jarvis.sql").read_text(encoding="utf-8")
    assert f"))>={KAIROS_JARVIS_MAX_OPEN} THEN" in sql
    assert f"interval '{KAIROS_REUSE_DAYS} days'" in sql


def test_us_exact_ticker_precedes_same_industry_label(monkeypatch):
    monkeypatch.setattr(listen, "answer_drive_folder_confirmation", lambda *a: None)
    monkeypatch.setattr("src.collectors.sec_edgar.resolve_us", lambda text: {"name": "GARTNER INC", "ticker": "IT"})
    seen = []
    monkeypatch.setattr(listen, "enqueue", lambda *a: seen.append(a[2]) or True)
    monkeypatch.setattr(listen, "record_receipt", lambda *a: None)
    client = Mock()
    client.send_message.return_value = {"result": {"message_id": 1}}
    message = {"chat": {"type": "private", "id": 111}, "from": {"id": 111}, "text": "IT"}
    assert listen.handle_message(client, message, {}, analyze=False, chats={"111"}, update_id=1)["result"] == "분석 접수"
    assert seen[0].kind == "company" and seen[0].ticker == "IT"
