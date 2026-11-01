# PRD Ref: §8.7 M · SC: 전환 검증 중 모델 생성·큐 변경 없이 기존 heartbeat 보존
"""Read-only readiness checks for event-driven desktop intake. Never starts a turn."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import queue
import subprocess
import threading
import time

from src.config.constants import (
    KAIROS_INTAKE_MIN_REMAINING_PERCENT,
    KAIROS_INTAKE_PROBE_INTERVAL_SECONDS,
    KAIROS_INTAKE_RPC_TIMEOUT_SECONDS,
)

PROOF = Path(__file__).parent / 'state' / 'intake-readiness.json'


class ReadOnlyRpc:
    """Owned subprocess only; no auth token access and no inference methods."""
    def __init__(self, executable: str, shared: bool = False):
        self.process = subprocess.Popen(
            [executable, 'app-server', 'proxy' if shared else '--stdio'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        self.messages = queue.Queue()
        self.sequence = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.process.stdout:
            try:
                self.messages.put(json.loads(line))
            except ValueError:
                pass
        self.messages.put(None)

    def call(self, method: str, params=None):
        if method not in {'initialize', 'account/rateLimits/read', 'thread/read'}:
            raise ValueError('READ_ONLY_RPC')
        self.sequence += 1
        item = {'id': self.sequence, 'method': method}
        if params is not None:
            item['params'] = params
        self.process.stdin.write(json.dumps(item) + '\n')
        self.process.stdin.flush()
        deadline = time.monotonic() + KAIROS_INTAKE_RPC_TIMEOUT_SECONDS
        while True:
            message = self.messages.get(timeout=max(0, deadline - time.monotonic()))
            if message is None:
                raise RuntimeError('RPC_DISCONNECTED')
            if message.get('id') == self.sequence:
                if 'error' in message:
                    raise RuntimeError('RPC_REJECTED')
                return message['result']

    def initialize(self):
        self.call('initialize', {
            'clientInfo': {'name': 'heimdallr_intake_readiness', 'version': '1'},
            'capabilities': {'experimentalApi': True},
        })
        self.process.stdin.write('{"method":"initialized"}\n')
        self.process.stdin.flush()

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=KAIROS_INTAKE_RPC_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=KAIROS_INTAKE_RPC_TIMEOUT_SECONDS)
        for pipe in (self.process.stdin, self.process.stdout):
            pipe.close()


def quota_summary(data: dict) -> dict:
    """Missing/invalid limits never mean available; all published windows must pass."""
    buckets = data.get('rateLimitsByLimitId') or {'legacy': data.get('rateLimits')}
    windows = []
    valid = isinstance(buckets, dict) and bool(buckets)
    blocked = data.get('ordinaryUsageAllowed') is not True
    for name, bucket in buckets.items() if isinstance(buckets, dict) else []:
        if not isinstance(bucket, dict):
            valid = False
            continue
        blocked |= bool(bucket.get('spendControlReached') or bucket.get('rateLimitReachedType'))
        before = len(windows)
        for key in ('primary', 'secondary'):
            window = bucket.get(key)
            if window is None:
                continue
            used = window.get('usedPercent') if isinstance(window, dict) else None
            if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used) or not 0 <= used <= 100:
                valid = False
                continue
            windows.append({'bucket': name, 'window': key, 'remaining_percent': 100 - used,
                            'resets_at': window.get('resetsAt')})
        if len(windows) == before:
            valid = False
    available = valid and bool(windows) and not blocked and all(
        w['remaining_percent'] >= KAIROS_INTAKE_MIN_REMAINING_PERCENT for w in windows
    )
    return {'available': available, 'ordinary_usage_allowed': data.get('ordinaryUsageAllowed'),
            'windows': windows}


def select_job(jobs: list[dict]):
    # Preserve sending/uncertain/folder-wait barriers and oldest created_at ordering.
    if any(j['status'] in {'sending', 'uncertain', 'awaiting_input'} for j in jobs):
        return None
    working = [j for j in jobs if j['status'] == 'working']
    if len(working) > 1:
        return None
    candidates = working or [j for j in jobs if j['status'] == 'pending']
    return min(candidates, key=lambda j: (j.get('created_at', ''), -j['id'])) if candidates else None


def inspect(snapshot: dict, executable: str, *, force=False, proof=PROOF) -> dict:
    now = datetime.now(timezone.utc)
    job = select_job(snapshot['jobs'])
    if not job and not force:
        return {'status': 'idle', 'model_calls': 0, 'heartbeat_preserved': True}
    if not force:
        try:
            previous = json.loads(proof.read_text(encoding='utf-8'))
            age = (now - datetime.fromisoformat(previous['checked_at'])).total_seconds()
            if previous.get('request_id') == job['id'] and 0 <= age < KAIROS_INTAKE_PROBE_INTERVAL_SECONDS:
                return {'status': 'cached', 'model_calls': 0, 'heartbeat_preserved': True}
        except (OSError, ValueError, KeyError, TypeError):
            pass
    result = {'checked_at': now.isoformat(), 'request_id': job['id'] if job else None,
              'model_calls': 0, 'heartbeat_preserved': True, 'dispatch_enabled': False}
    for shared in (False, True):
        rpc = None
        label = 'shared' if shared else 'isolated'
        try:
            rpc = ReadOnlyRpc(executable, shared=shared)
            rpc.initialize()
            result[label + '_quota'] = quota_summary(rpc.call('account/rateLimits/read'))
            thread = rpc.call('thread/read', {
                'threadId': snapshot['trigger_thread'], 'includeTurns': False,
            })['thread']
            result[label + '_thread_status'] = thread.get('status', {}).get('type')
        except Exception as exc:
            # Never record raw protocol errors containing credentials or message contents.
            result[label + '_error'] = type(exc).__name__
        finally:
            if rpc is not None:
                rpc.close()
    result['status'] = 'validation_only'
    proof.parent.mkdir(parents=True, exist_ok=True)
    temporary = proof.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(proof)
    return result


def main():
    from telegram_bridge.bridge import connect, find_codex, poll
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Probe even when the queue is empty; no generation.')
    parser.add_argument('--enable-shadow', action='store_true', help='Enable work-only diagnostics in the existing collector; retain heartbeat.')
    args = parser.parse_args()
    if args.enable_shadow:
        from telegram_bridge.bridge import save_setting
        db = connect()
        try:
            save_setting(db, 'intake_readiness_enabled', '1')
        finally:
            db.close()
    db = connect(read_only=True)
    try:
        snapshot = poll(db)
    finally:
        db.close()
    executable = find_codex()
    if not executable:
        raise RuntimeError('CODEX_NOT_FOUND')
    print(json.dumps(inspect(snapshot, executable, force=args.check), ensure_ascii=False))


if __name__ == '__main__':
    main()
