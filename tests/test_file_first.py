import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from telegram_bridge import bridge, deck_runner, file_first as f
from src.notify import kairos_followups as followups


@pytest.fixture
def package(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, 'STATE', tmp_path / 'queue.sqlite3')
    monkeypatch.setattr(deck_runner, 'STATE', tmp_path / 'decks')
    deck_runner.STATE.mkdir()
    draft = tmp_path / 'draft.md'
    draft.write_text('# 개요\n사업과 성장 근거\n# 가치평가\nPER/F.PER와 촉매', encoding='utf-8')
    template = tmp_path / 'template.json'
    template.write_text(json.dumps({'page': {'id': 'actual-template'},
        'blocks': {'results': [{'id': 'block'}], 'has_more': False}}), encoding='utf-8')
    source = tmp_path / 'source.txt'
    source.write_text('official source excerpt')
    item = lambda path: {'path': str(path), 'sha256': f.digest(path)}
    data = {'request_id': 7, 'pipeline': f.PIPELINE, 'draft': item(draft),
            'template': {**item(template), 'section_titles': ['개요', '가치평가']},
            'facts': [], 'gaps': [], 'thesis': {'base': '근거와 반대 논거'},
            'artifacts': [item(source)]}
    path = f.package_path(7)
    path.parent.mkdir()
    path.write_text(json.dumps(data), encoding='utf-8')
    return data


def test_full_draft_template_files_verified_and_immutable(package):
    assert f.validate_files(package, 7) is package
    from pathlib import Path
    Path(package['artifacts'][0]['path']).write_text('changed source')
    with pytest.raises(ValueError, match='HASH_MISMATCH'):
        f.validate_files(package, 7)


@pytest.mark.parametrize('change,error', [('missing_section','SECTION_MISSING'),
    ('out_of_order','SECTION_MISSING'), ('relative_path','ABSOLUTE_PATH'),
    ('incomplete_template','TEMPLATE_READBACK'), ('no_thesis','THESIS_REQUIRED')])
def test_incomplete_handoff_blocks_auto_analysis(package, change, error):
    from pathlib import Path
    if change in {'missing_section', 'out_of_order'}:
        path = Path(package['draft']['path'])
        path.write_text('가치평가\n개요' if change == 'out_of_order' else '개요만 있음', encoding='utf-8')
        package['draft']['sha256'] = f.digest(path)
    elif change == 'relative_path':
        package['draft']['path'] = 'draft.md'
    elif change == 'incomplete_template':
        path = Path(package['template']['path'])
        path.write_text(json.dumps({'page': {'id': 'template'}, 'blocks': {'results': [1], 'has_more': True}}))
        package['template']['sha256'] = f.digest(path)
    else:
        package['thesis'] = {}
    with pytest.raises(ValueError, match=error):
        f.validate_files(package, 7)


def owner():
    return {'update_id': 7, 'source': 'telegram', 'chat_id': 111, 'user_id': 111,
            'status': 'working', 'stage': 'claude', 'notion_url': None, 'request_kind': 'company',
            'target_name': '실제 요청', 'company_name': '실제 요청', 'market': 'KR', 'code': '005930'}


def test_submit_no_notion_or_completion_and_replay_reuses_same_job(package, monkeypatch):
    db = bridge.connect()
    db.execute("INSERT INTO jobs(id,code,company,raw_text,chat_id,status,source) VALUES(7,'005930','실제 요청','실제 요청',111,'working','telegram')")
    db.commit()
    monkeypatch.setattr(followups, 'request_row', lambda *args: owner())
    monkeypatch.setattr(followups, 'latest_job', lambda *args: None)
    sequence = []
    monkeypatch.setattr(followups, 'notify_codex', lambda owner, event: sequence.append(event))
    enqueue = Mock(return_value={'id': 80, 'status': 'pending', 'mode': 'analysis'})
    enqueue.side_effect = lambda *args: sequence.append('queued') or {'id': 80, 'status': 'pending', 'mode': 'analysis'}
    monkeypatch.setattr(followups, 'enqueue_followup', enqueue)
    notify = Mock()
    monkeypatch.setattr(followups, 'notify_progress', notify)
    remote = Mock(return_value=True)
    monkeypatch.setattr(bridge, 'change_remote', remote)
    result = f.submit(db, 7, '반도체')
    assert result['status'] == 'claude' and not result['notion_published']
    assert db.execute('SELECT status,notion_url FROM jobs WHERE id=7').fetchone()[:] == ('claude', None)
    assert remote.call_args.args == (7, 'working', 'working')
    assert sequence == ['completed', 'queued']
    assert bridge.poll(db)['jobs'] == []  # no competing Codex restart
    assert f.submit(db, 7, '반도체')['claude_job_id'] == 80
    enqueue.assert_called_with({**owner(), 'industry': '반도체'}, 'analysis')
    db.close()


def test_codex_started_after_claim_before_bootstrap(package, monkeypatch):
    db = bridge.connect()
    db.execute("INSERT INTO jobs(id,code,company,raw_text,chat_id,status,telegram_message_id) VALUES(7,'005930','대상','대상',111,'pending',1)")
    db.commit()
    sequence = []
    monkeypatch.setattr(bridge, 'change_remote', lambda *args, **kwargs: True)
    monkeypatch.setattr(bridge, 'set_progress', lambda *args: None)
    monkeypatch.setattr(bridge, 'ensure_checkpoint', lambda *args: f.package_path(7))
    monkeypatch.setattr(bridge, 'prepare_drive', lambda *args: sequence.append('bootstrap') or {})
    monkeypatch.setattr(followups, 'notify_codex', lambda row, event: sequence.append((event, row['status'])))
    assert bridge.claim(db, 7)['status'] == 'claimed'
    assert sequence == [('started', 'working'), 'bootstrap']
    assert bridge.claim(db, 7)['status'] == 'not_claimed'
    assert len(sequence) == 2
    db.close()


def test_failed_claude_is_not_silently_requeued(package, monkeypatch):
    db = bridge.connect()
    db.execute("INSERT INTO jobs(id,code,company,raw_text,chat_id,status) VALUES(7,'005930','대상','대상',111,'working')")
    db.commit()
    monkeypatch.setattr(followups, 'latest_job', lambda *args: {'status': 'failed'})
    with pytest.raises(RuntimeError, match='TERMINAL_NEEDS_RECOVERY'):
        f.submit(db, 7, '반도체')
    assert db.execute('SELECT status FROM jobs WHERE id=7').fetchone()[0] == 'working'
    db.close()


def test_prompt_uses_files_without_fake_codex_notion(package, monkeypatch):
    monkeypatch.setattr(deck_runner, 'local_context', lambda *args: (bridge.checkpoint_path(7), None, None))
    prompt = deck_runner.build_prompt({'id': 80, 'mode': 'analysis', 'request_id': 7, 'analysis': owner()})
    assert '--codex-md ' in prompt and '--handoff ' in prompt
    assert '--codex ' not in prompt and 'Notion URL은 없습니다' in prompt
    assert 'comparison_review_path' in prompt and '모든 gap' in prompt
    assert 'PPT 버튼 발송을 하지' in prompt


def test_final_marker_required_before_parent_completed(package):
    job = {'id': 80, 'mode': 'analysis', 'request_id': 7, 'status': 'sent',
           'notion_url': 'https://www.notion.so/' + 'a' * 32}
    with pytest.raises(FileNotFoundError):
        f.finalize(job, owner())


def test_final_marker_and_parent_cas_then_replay_without_generation(package, tmp_path, monkeypatch):
    from pathlib import Path
    from src.db import supabase_client
    proof = tmp_path / 'readback.json'; proof.write_text('validated actual readback fixture')
    comparison = tmp_path / 'comparison.json'
    comparison.write_text(json.dumps({'request_id': 'A80', 'comparisons': [
        {'topic': '촉매', 'codex_view': '기준', 'claude_view': '유지', 'reason': '원문 대조', 'source_urls': ['https://official.example/ir']}]}, ensure_ascii=False), encoding='utf-8')
    url = 'https://www.notion.so/' + 'a' * 32
    job = {'id': 80, 'request_id': 7, 'mode': 'analysis', 'status': 'sent', 'notion_url': url,
           'completed_at': '2026-10-11T12:00:00+00:00'}
    result = {'notion_url': url, 'proof_path': str(proof), 'comparison_review_path': str(comparison)}
    f.validate_comparison(result, 'A80')
    f.record_validation(job, result, deck_runner.STATE)
    client = Mock()
    client.table.return_value.update.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = SimpleNamespace(data=[{'update_id': 7}])
    monkeypatch.setattr(supabase_client, 'get_client', lambda: client)
    done = f.finalize(job, owner())
    assert done['status'] == 'sent' and done['notion_url'] == url
    assert client.table.return_value.update.call_args.args[0]['status'] == 'sent'
    assert f.finalize(job, done)['status'] == 'sent'
    client.table.return_value.update.assert_called_once()
    proof.write_text('tampered readback')
    with pytest.raises(ValueError, match='FINAL_HASH_MISMATCH'):
        f.finalize(job, owner())


def test_legacy_sent_not_auto_converted_or_enqueued(monkeypatch):
    monkeypatch.setattr(f, 'is_file_first', lambda *args: False)
    original = {'update_id': 7, 'status': 'sent'}
    assert f.finalize({'mode': 'analysis'}, original) is original


def test_crash_during_handoff_syncs_terminal_parent_without_requeue(package):
    db = bridge.connect()
    db.execute("INSERT INTO jobs(id,code,company,raw_text,chat_id,status,progress_stage) VALUES(7,'005930','대상','대상',111,'working','claude')")
    db.commit()
    done = {**owner(), 'status': 'sent', 'stage': 'complete', 'notion_url': 'https://www.notion.so/'+'a'*32}
    assert f.finalize({'mode': 'analysis', 'status': 'sent'}, done) == done
    assert db.execute('SELECT status,notion_url FROM jobs WHERE id=7').fetchone()[:] == ('sent', done['notion_url'])
    db.close()


@pytest.mark.parametrize('complete_comparison', [True, False])
def test_worker_accepts_working_parent_and_requires_review_before_finalizing(package, tmp_path, monkeypatch, complete_comparison):
    from telegram_bridge import notion_readback
    from pathlib import Path
    skill = tmp_path / 'skill'; skill.mkdir(); (skill / 'SKILL.md').write_text('fixture')
    monkeypatch.setattr(deck_runner, 'SKILL', skill)
    monkeypatch.setattr(deck_runner.shutil, 'which', lambda *args: 'claude.exe')
    monkeypatch.setattr(deck_runner, 'probe_subscription', lambda *args: {'loggedIn': True})
    monkeypatch.setattr(deck_runner, 'login_notice', lambda *args: {})
    recover_interrupted = deck_runner.recover_interrupted
    monkeypatch.setattr(deck_runner, 'recover_interrupted', lambda *args: None)
    monkeypatch.setattr(deck_runner, 'local_context', lambda *args: (bridge.checkpoint_path(7), None, None))
    monkeypatch.setattr(followups, 'notify_progress', lambda *args: 0)
    # Separate tests cover real Notion readback; this test covers worker ordering.
    monkeypatch.setattr(notion_readback, 'validate_readback', lambda *args: None)
    job = {'id': 80, 'request_id': 7, 'mode': 'analysis', 'attempts': 1, 'analysis': owner()}
    client = Mock(); client.rpc.return_value.execute.return_value.data = job
    client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [{'id': 80}]
    monkeypatch.setattr(deck_runner, 'get_client', lambda: client)
    md = tmp_path / 'final.md'; md.write_text('Final reviewed analysis')
    gaps = tmp_path / 'gaps.json'; gaps.write_text(json.dumps({'request_id': 'A80', 'gaps': []}))
    proof = tmp_path / 'proof.json'; proof.write_text('readback fixture')
    comparison = tmp_path / 'comparison.json'
    if complete_comparison:
        comparison.write_text(json.dumps({'request_id': 'A80', 'comparisons': [{
            'topic': '촉매', 'codex_view': '초기 판단', 'claude_view': '검증 판단',
            'reason': '원문 독립 대조', 'source_urls': ['https://official.example/ir']}]}))
    result = {'status': 'ok', 'mode': 'analysis', 'request_id': 'A80',
        'notion_url': 'https://www.notion.so/'+'a'*32, 'drive_dir': str(tmp_path),
        'files': [str(md)], 'analysis_md': str(md), 'gap_review_path': str(gaps),
        'proof_path': str(proof), 'comparison_review_path': str(comparison)}
    from telegram_bridge import pro_followups as pro
    monkeypatch.setattr(pro, 'execute', lambda *args, **kwargs: result)
    finalized = []
    def finalize(updated, parent):
        if updated['status'] == 'sent':
            assert (deck_runner.STATE / 'A80-final-validation.json').is_file()
            finalized.append(updated)
        return parent
    monkeypatch.setattr(f, 'finalize', finalize)
    output = deck_runner.run_once()
    assert output['status'] == ('sent' if complete_comparison else 'pending')
    assert len(finalized) == int(complete_comparison)
    if complete_comparison:
        # Simulate the narrow crash window before the successful DB update.
        identity = '9cbc0129-97a3-446d-aed2-b65d19925aa0'
        (deck_runner.STATE / 'A80-session.json').write_text(json.dumps({'session_id': identity}))
        (deck_runner.STATE / f'{identity}-execution.json').write_text(json.dumps({'worker_pid': 1, 'claude_pid': 2}))
        monkeypatch.setattr(deck_runner, 'process_alive', lambda *args: False)
        monkeypatch.setattr(followups, 'request_row', lambda *args: owner())
        client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [job]
        model = Mock(side_effect=AssertionError('must not rerun model'))
        monkeypatch.setattr(deck_runner, 'run_claude', model)
        assert recover_interrupted(client)['status'] == 'sent'
        model.assert_not_called()


@pytest.fixture(autouse=True)
def isolated_pro_execution_store(tmp_path, monkeypatch):
    import src.llm.subscription as subscription
    from telegram_bridge import pro_followups
    monkeypatch.setattr(subscription, "STATE", tmp_path / "pro-execution")
    monkeypatch.setattr(pro_followups, "STATE", tmp_path / "pro-execution")
