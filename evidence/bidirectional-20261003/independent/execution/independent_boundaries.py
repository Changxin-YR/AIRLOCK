"""Disposable synthetic process-crash and credential-role counterchecks."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from airlock.github_adapter import AdapterConfig, ExecuteRequest, IssueAdapter, IssueArguments, ObservedIssue, create_app


def config(mode):
    return AdapterConfig(repository_node_id='R_synthetic', repository_full_name='synthetic/counterexample',
                         public_repository=True, mode=mode, api_pinned_addresses=['140.82.112.6'] if mode == 'direct' else [])


def request(adapter):
    arguments = IssueArguments(title='Synthetic boundary', body='No real credentials or external writes')
    return ExecuteRequest(action_id='a' * 32, request_hash='b' * 64, arguments=arguments,
                          expected_version=adapter._plan_digest(arguments))


def observed(row):
    return ObservedIssue(repository_node_id='R_synthetic', repository_full_name='synthetic/counterexample',
                         issue_node_id='I_synthetic', number=9, url='https://github.com/synthetic/counterexample/issues/9',
                         title=row['title'], body=row['body'])


def child(directory, phase):
    directory = Path(directory)
    adapter = IssueAdapter(config('direct'), directory / 'adapter.db')
    def create(row):
        if phase == 'before_send':
            os._exit(73)
        with sqlite3.connect(directory / 'target.db') as conn:
            conn.execute('CREATE TABLE effects (observed TEXT NOT NULL)')
            conn.execute('INSERT INTO effects VALUES (?)', (observed(row).model_dump_json(),))
        os._exit(74)
    adapter.api.create = create
    adapter.execute(request(adapter))
    raise AssertionError('child must terminate abruptly')


def run():
    results = []
    for phase, expected_exit in [('before_send', 73), ('after_send', 74)]:
        with tempfile.TemporaryDirectory(prefix='crash-', dir=Path(__file__).parent) as directory:
            run = subprocess.run([sys.executable, __file__, '--child', directory, phase], capture_output=True, text=True)
            assert run.returncode == expected_exit, run.stderr
            adapter = IssueAdapter(config('direct'), Path(directory) / 'adapter.db')
            def never_send(_):
                raise AssertionError('a claimed action must never send again after process death')
            adapter.api.create = never_send
            assert adapter.execute(request(adapter))['state'] == 'unknown'
            assert adapter.execute(request(adapter))['state'] == 'unknown'
            effect_count = 0
            if phase == 'after_send':
                with closing(sqlite3.connect(Path(directory) / 'target.db')) as conn:
                    rows = conn.execute('SELECT observed FROM effects').fetchall()
                effect_count = len(rows)
                adapter.api.read_issue = lambda _: ObservedIssue.model_validate_json(rows[0][0])
                assert adapter.reconcile_direct('a' * 32, 'I_synthetic')['state'] == 'executed'
                assert adapter.execute(request(adapter))['state'] == 'executed'
                with closing(sqlite3.connect(Path(directory) / 'target.db')) as conn:
                    assert conn.execute('SELECT COUNT(*) FROM effects').fetchone()[0] == 1
            results.append({'probe': phase, 'child_exit_code': run.returncode, 'target_effects': effect_count,
                            'final_state': adapter.receipt('a' * 32)['state'], 'automatic_resends': 0})

    # Only throwaway fixture credentials are generated here, never read from the
    # current operator's environment or any existing database.
    os.environ['AIRLOCK_UPSTREAM_GITHUB_GATE_TOKEN'] = gate = secrets.token_urlsafe(32)
    os.environ['AIRLOCK_GITHUB_RELAY_TOKEN'] = relay = secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix='roles-', dir=Path(__file__).parent) as directory:
        app = create_app(config('relay'), Path(directory) / 'adapter.db')
        adapter = app.state.adapter
        call = request(adapter)
        with TestClient(app) as client:
            for token in [None, relay]:
                headers = {} if token is None else {'Authorization': 'Bearer ' + token}
                for route, payload in [('/preview', {'arguments': call.arguments.model_dump()}), ('/execute', call.model_dump())]:
                    assert client.post(route, json=payload, headers=headers).status_code == 403
            with adapter.connection() as conn:
                assert conn.execute('SELECT COUNT(*) FROM github_claims').fetchone()[0] == 0
            gate_headers = {'Authorization': 'Bearer ' + gate}
            assert client.post('/execute', json=call.model_dump(), headers=gate_headers).json()['state'] == 'unknown'
            changed = call.model_dump()
            changed['arguments']['title'] = 'Injected change'
            response = client.post('/execute', json=changed, headers=gate_headers)
            assert response.status_code == 409 and response.json()['error'] == 'github_claim_binding_mismatch'
            assert client.post('/operator/claim/' + call.action_id, headers=gate_headers).status_code == 403
            claim = client.post('/operator/claim/' + call.action_id, headers={'Authorization': 'Bearer ' + relay}).json()
            completion = {'claim_token': claim['claim_token'], 'binding_digest': claim['binding_digest'],
                          'observed_issue': observed(claim).model_dump(), 'observation_reference': 'synthetic-readback'}
            with adapter.connection() as conn:
                initial = conn.execute('SELECT document FROM github_claims').fetchone()[0]
            for token in [None, gate]:
                headers = {} if token is None else {'Authorization': 'Bearer ' + token}
                assert client.post('/operator/complete/' + call.action_id, json=completion, headers=headers).status_code == 403
            with adapter.connection() as conn:
                assert conn.execute('SELECT document FROM github_claims').fetchone()[0] == initial
            assert adapter.receipt(call.action_id)['state'] == 'unknown'
        results.append({'probe': 'unauthorized_and_role_confusion', 'credential_rejections': 7,
                        'binding_conflicts': 1, 'unauthorized_effects': 0, 'claim_preserved': True})
    print(json.dumps({'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                      'dirty': subprocess.check_output(['git', 'status', '--porcelain'], text=True).splitlines(),
                      'source_sha256': hashlib.sha256((ROOT / 'airlock/github_adapter.py').read_bytes()).hexdigest(),
                      'network_calls': 0, 'results': results}, indent=2))


if __name__ == '__main__':
    if len(sys.argv) > 1:
        child(sys.argv[2], sys.argv[3])
    else:
        run()
