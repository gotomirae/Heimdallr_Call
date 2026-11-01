import pytest

from telegram_bridge import intake_readiness as readiness


def limits(used=90, allowed=True):
    return {'ordinaryUsageAllowed': allowed, 'rateLimitsByLimitId': {
        'codex': {'primary': {'usedPercent': used, 'resetsAt': 123},
                  'secondary': {'usedPercent': 10, 'resetsAt': 456}},
    }}


@pytest.mark.parametrize('used,allowed,expected', [(90, True, True), (90.1, True, False),
    (0, False, False), (float('nan'), True, False), (True, True, False), (-1, True, False)])
def test_quota_boundary_and_invalid_values(used, allowed, expected):
    assert readiness.quota_summary(limits(used, allowed))['available'] is expected


def test_all_buckets_and_unknown_windows_block():
    data = limits(20)
    data['rateLimitsByLimitId']['other'] = {'primary': {'usedPercent': 95}}
    assert not readiness.quota_summary(data)['available']
    data['rateLimitsByLimitId']['other'] = {}
    assert not readiness.quota_summary(data)['available']
    assert not readiness.quota_summary({'ordinaryUsageAllowed': True})['available']
    data = limits(20)
    data['rateLimitsByLimitId']['codex']['spendControlReached'] = True
    assert not readiness.quota_summary(data)['available']


def test_working_priority_oldest_jarvis_and_delivery_barrier():
    jobs = [{'id': -2, 'created_at': '2026-10-02', 'status': 'pending'},
            {'id': -1, 'created_at': '2026-10-01', 'status': 'pending'}]
    assert readiness.select_job(jobs)['id'] == -1
    jobs.append({'id': 7, 'created_at': '2026-10-03', 'status': 'working'})
    assert readiness.select_job(jobs)['id'] == 7
    jobs.append({'id': 8, 'status': 'uncertain'})
    assert readiness.select_job(jobs) is None


def test_idle_never_starts_server_or_writes(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail('idle probe started a server')
    monkeypatch.setattr(readiness, 'ReadOnlyRpc', forbidden)
    proof = tmp_path / 'proof.json'
    assert readiness.inspect({'jobs': []}, 'unused', proof=proof)['status'] == 'idle'
    assert not proof.exists()


def test_work_probe_cached_and_failed_shared_still_preserves_heartbeat(monkeypatch, tmp_path):
    seen = []
    class Rpc:
        def __init__(self, executable, shared=False):
            self.shared = shared
            seen.append(shared)
        def initialize(self):
            if self.shared:
                raise RuntimeError('credential-containing error must not be logged')
        def call(self, method, params=None):
            if method == 'account/rateLimits/read':
                return limits(20)
            return {'thread': {'status': {'type': 'notLoaded'}}}
        def close(self):
            pass
    monkeypatch.setattr(readiness, 'ReadOnlyRpc', Rpc)
    snapshot = {'trigger_thread': 'existing', 'jobs': [{'id': 1, 'status': 'pending'}]}
    proof = tmp_path / 'proof.json'
    result = readiness.inspect(snapshot, 'unused', proof=proof)
    assert result['isolated_quota']['available']
    assert result['shared_error'] == 'RuntimeError'
    assert result['heartbeat_preserved'] and not result['dispatch_enabled']
    assert 'credential' not in proof.read_text()
    assert readiness.inspect(snapshot, 'unused', proof=proof)['status'] == 'cached'
    assert seen == [False, True]


def test_rpc_rejects_inference_before_sending():
    rpc = readiness.ReadOnlyRpc.__new__(readiness.ReadOnlyRpc)
    with pytest.raises(ValueError, match='READ_ONLY_RPC'):
        rpc.call('turn/start')
