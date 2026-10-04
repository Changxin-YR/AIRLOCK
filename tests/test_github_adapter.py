from contextlib import contextmanager
from dataclasses import replace
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from airlock.github_adapter import (AdapterConfig, ExecuteRequest, GitHubAPI, IssueAdapter,
                                    IssueArguments, ObservedIssue, RelayCompletion, create_app)
from airlock.models import GateError, Invocation
from airlock.service import Gate
from airlock.upstream import Registry, Tool
from conftest import decision
from scripts.support import stop_process_tree


def config(mode='relay', **kwargs):
    return AdapterConfig(repository_node_id='R_test123', repository_full_name='example/project',
                         public_repository=True, mode=mode,
                         api_pinned_addresses=['140.82.112.6'] if mode == 'direct' else [], **kwargs)


def request(adapter, key='a' * 32):
    arguments = IssueArguments(title='Actual project task', body='Acceptance details')
    return ExecuteRequest(action_id=key, request_hash='b' * 64,
                          expected_version=adapter._plan_digest(arguments), arguments=arguments)


def observed(row, **overrides):
    fields = dict(repository_node_id='R_test123', repository_full_name='example/project',
                  issue_node_id='I_test123', number=7, url='https://github.com/example/project/issues/7',
                  title=row['title'], body=row['body'])
    fields.update(overrides)
    return ObservedIssue(**fields)


def completion(claim, **overrides):
    return RelayCompletion(claim_token=claim['claim_token'], binding_digest=claim['binding_digest'],
                           observed_issue=observed(claim, **overrides), observation_reference='readback.json')


def test_github_append_only_plan_has_no_cas_or_rollback_claim(tmp_path):
    adapter = IssueAdapter(config(), tmp_path / 'adapter.db')
    preview = adapter.preview(IssueArguments(title='Task', body='Details'))
    assert preview['impact_units'] == 1 and preview['after']['target_cas'] is False
    assert preview['after']['notification_count'] == 'unknown'
    assert preview['after']['restore'] == 'not fully reversible'
    with pytest.raises(ValidationError):
        IssueArguments(title='Title\nInvalid', body='text')
    with pytest.raises(ValidationError):
        IssueArguments(title='Valid', body='<!-- AIRLOCK action_id=forged -->')
    with pytest.raises(ValidationError):
        IssueArguments(title='Valid', body='x', url='https://attacker.invalid')
    with pytest.raises(ValueError):
        Tool(name='upstream:issue', resource='github', url='http://127.0.0.1:8001', allow_loopback=True,
             execution_model='append_only_create', compensates='upstream:other', arguments={}).target()


def test_github_direct_durable_send_once_concurrent_and_restart(tmp_path, monkeypatch):
    adapter = IssueAdapter(config('direct'), tmp_path / 'adapter.db')
    sends = []
    def create(row):
        # A separate connection observes the committed claim before the send.
        with sqlite3.connect(adapter.database) as conn:
            assert conn.execute('SELECT COUNT(*) FROM github_claims').fetchone()[0] == 1
        sends.append(row['action_id'])
        time.sleep(.02)
        return observed(row)
    monkeypatch.setattr(adapter.api, 'create', create)
    call = request(adapter)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: adapter.execute(call), range(5)))
    assert len(sends) == 1
    assert {r['state'] for r in results} <= {'unknown', 'executed'}
    restart = IssueAdapter(config('direct'), adapter.database)
    monkeypatch.setattr(restart.api, 'create', lambda _: pytest.fail('must never replay send'))
    receipt = restart.execute(call)
    assert receipt['state'] == 'executed'
    assert receipt['result']['receipt_verification'] == 'github_response'
    changed = call.model_copy(update={'arguments': IssueArguments(title='Changed', body='Acceptance details')})
    with pytest.raises(GateError, match='binding_mismatch'):
        restart.execute(changed)


def test_github_unknown_timeout_and_crash_never_resend(tmp_path, monkeypatch):
    adapter = IssueAdapter(config('direct'), tmp_path / 'adapter.db')
    sends = []
    def fail(row):
        sends.append(row['action_id'])
        raise httpx.ReadTimeout('response lost after possible creation')
    monkeypatch.setattr(adapter.api, 'create', fail)
    call = request(adapter)
    assert adapter.execute(call)['state'] == 'unknown'
    assert adapter.execute(call)['state'] == 'unknown'
    restart = IssueAdapter(config('direct'), adapter.database)
    monkeypatch.setattr(restart.api, 'create', lambda _: pytest.fail('no retry'))
    assert restart.execute(call)['state'] == 'unknown' and len(sends) == 1
    # A process crash before its network send is also ambiguous on restart.
    crash = request(adapter, 'c' * 32)
    monkeypatch.setattr(adapter.api, 'create', lambda _: (_ for _ in ()).throw(SystemExit(1)))
    with pytest.raises(SystemExit):
        adapter.execute(crash)
    assert restart.execute(crash)['state'] == 'unknown'


def test_github_unknown_direct_result_requires_bound_independent_readback(tmp_path, monkeypatch):
    adapter = IssueAdapter(config('direct'), tmp_path / 'adapter.db')
    claimed = []
    def lose_response(row):
        claimed.append(row)
        raise httpx.ReadTimeout('lost response')
    monkeypatch.setattr(adapter.api, 'create', lose_response)
    call = request(adapter)
    assert adapter.execute(call)['state'] == 'unknown'
    monkeypatch.setattr(adapter.api, 'read_issue', lambda _: observed(claimed[0], body='other issue'))
    with pytest.raises(GateError, match='observation_mismatch'):
        adapter.reconcile_direct(call.action_id, 'I_test123')
    assert adapter.receipt(call.action_id)['state'] == 'unknown'
    monkeypatch.setattr(adapter.api, 'read_issue', lambda _: observed(claimed[0]))
    receipt = adapter.reconcile_direct(call.action_id, 'I_test123')
    assert receipt['state'] == 'executed' and receipt['result']['receipt_verification'] == 'github_readback'
    assert adapter.execute(call) == receipt and len(claimed) == 1
    with pytest.raises(GateError, match='observation_mismatch'):
        adapter.reconcile_direct(call.action_id, 'I_other')


@pytest.mark.parametrize('first', ['response', 'readback'])
@pytest.mark.parametrize('conflicting_issue', [False, True])
def test_github_direct_response_readback_race_preserves_first_receipt(tmp_path, monkeypatch, first, conflicting_issue):
    adapter = IssueAdapter(config('direct'), tmp_path / 'adapter.db')
    call = request(adapter)
    mutation_done, allow_response, read_started, allow_readback = (Event() for _ in range(4))
    effects = []

    def create(row):
        effects.append(observed(row))
        mutation_done.set()
        assert allow_response.wait(5)
        return effects[0]

    def read_issue(_):
        read_started.set()
        assert allow_readback.wait(5)
        return effects[0].model_copy(update={'issue_node_id': 'I_other'}) if conflicting_issue else effects[0]

    monkeypatch.setattr(adapter.api, 'create', create)
    monkeypatch.setattr(adapter.api, 'read_issue', read_issue)
    with ThreadPoolExecutor(max_workers=2) as pool:
        execution = pool.submit(adapter.execute, call)
        try:
            assert mutation_done.wait(5)
            readback = pool.submit(adapter.reconcile_direct, call.action_id, 'I_other' if conflicting_issue else 'I_test123')
            assert read_started.wait(5)
            first_future, second_future = (execution, readback) if first == 'response' else (readback, execution)
            first_signal, second_signal = (allow_response, allow_readback) if first == 'response' else (allow_readback, allow_response)
            first_signal.set()
            receipt = first_future.result(timeout=5)
            assert receipt['state'] == 'executed'
            assert receipt['result']['receipt_verification'] == 'github_' + first
            with adapter.connection() as conn:
                original_document = conn.execute('SELECT document FROM github_claims').fetchone()[0]
            second_signal.set()
            if conflicting_issue:
                with pytest.raises(GateError, match='receipt_conflict'):
                    second_future.result(timeout=5)
            else:
                assert second_future.result(timeout=5) == receipt
        finally:
            allow_response.set()
            allow_readback.set()
    assert len(effects) == 1
    with adapter.connection() as conn:
        assert conn.execute('SELECT document FROM github_claims').fetchone()[0] == original_document
    restart = IssueAdapter(config('direct'), adapter.database)
    monkeypatch.setattr(restart.api, 'create', lambda _: pytest.fail('must not resend a completed mutation'))
    assert restart.execute(call) == receipt


def test_github_plan_configuration_drift_and_capacity_fail_closed(tmp_path):
    adapter = IssueAdapter(config(max_claims=1), tmp_path / 'adapter.db')
    call = request(adapter)
    adapter.execute(call)
    with pytest.raises(GateError, match='capacity'):
        adapter.execute(request(adapter, 'c' * 32))
    drift = IssueAdapter(config(max_claims=2), adapter.database)
    with pytest.raises(GateError, match='binding_mismatch'):
        drift.execute(call)
    with pytest.raises(GateError, match='claim_unavailable'):
        drift.claim(call.action_id)


def test_github_relay_requires_unique_claim_and_exact_readback(tmp_path):
    adapter = IssueAdapter(config(), tmp_path / 'adapter.db')
    call = request(adapter)
    assert adapter.execute(call)['state'] == 'unknown'
    claim = adapter.claim(call.action_id)
    assert claim['must_not_retry_mutation'] and claim['receipt_verification'] == 'operator_attested'
    with pytest.raises(GateError, match='claim_unavailable'):
        adapter.claim(call.action_id)
    for change in ({'title': 'other'}, {'body': 'missing marker'}, {'repository_node_id': 'R_other'},
                   {'url': 'https://attacker.invalid/issues/7'}, {'number': 8}):
        with pytest.raises(GateError, match='observation_mismatch'):
            adapter.complete_relay(call.action_id, completion(claim, **change))
    invalid = completion(claim).model_copy(update={'claim_token': 'x' * 40})
    with pytest.raises(GateError, match='binding_mismatch'):
        adapter.complete_relay(call.action_id, invalid)
    result = adapter.complete_relay(call.action_id, completion(claim))
    assert result['state'] == 'executed' and result['result']['receipt_verification'] == 'operator_attested'
    assert adapter.complete_relay(call.action_id, completion(claim)) == result
    assert adapter.execute(call) == result
    with pytest.raises(GateError, match='receipt_conflict'):
        adapter.complete_relay(call.action_id, completion(claim, issue_node_id='I_other'))


def test_github_no_claim_before_approval_stale_or_expired(tmp_path, monkeypatch):
    adapter = IssueAdapter(config(), tmp_path / 'adapter.db')
    call = request(adapter)
    with pytest.raises(GateError, match='not_found'):
        adapter.claim(call.action_id)
    assert adapter.execute(call.model_copy(update={'expected_version': 'f' * 64}))['state'] == 'stale'
    with pytest.raises(GateError, match='not_found'):
        adapter.claim(call.action_id)
    adapter.execute(call)
    monkeypatch.setattr('airlock.github_adapter.time.time', lambda: 9999999999)
    with pytest.raises(GateError, match='expired'):
        adapter.claim(call.action_id)


def test_github_adapter_credentials_and_body_boundaries(tmp_path, monkeypatch):
    monkeypatch.setenv('AIRLOCK_UPSTREAM_GITHUB_GATE_TOKEN', 'g' * 40)
    monkeypatch.setenv('AIRLOCK_GITHUB_RELAY_TOKEN', 'r' * 40)
    app = create_app(config(), tmp_path / 'adapter.db')
    with TestClient(app) as client:
        args = {'arguments': {'title': 'Real task', 'body': 'details'}}
        assert client.post('/preview', json=args).status_code == 403
        assert client.post('/preview', json=args, headers={'Authorization': 'Bearer ' + 'r' * 40}).status_code == 403
        headers = {'Authorization': 'Bearer ' + 'g' * 40}
        assert client.post('/preview', json=args, headers=headers).status_code == 200
        assert client.post('/operator/claim/' + 'a' * 32, headers=headers).status_code == 403
        assert client.post('/preview', content=b'x' * 8193, headers=headers).status_code == 413
        assert client.post('/preview', json=args, headers={**headers, 'Origin': 'http://attacker.invalid'}).status_code == 403
        assert client.post('/preview', json={'arguments': {'title': 'x', 'body': 'x', 'repository': 'other'}}, headers=headers).status_code == 422
    monkeypatch.setenv('AIRLOCK_GITHUB_RELAY_TOKEN', 'g' * 40)
    with pytest.raises(ValueError, match='distinct'):
        create_app(config(), tmp_path / 'other.db')


def test_github_graphql_fixed_origin_node_id_and_response_binding(tmp_path, monkeypatch):
    monkeypatch.setenv('AIRLOCK_GITHUB_API_TOKEN', 'p' * 40)
    calls = []
    config_value = config('direct')
    adapter = IssueAdapter(config_value, tmp_path / 'adapter.db')
    def handler(req):
        assert str(req.url) == 'https://api.github.com/graphql'
        assert req.headers['authorization'] == 'Bearer ' + 'p' * 40
        data = json.loads(req.content)
        calls.append(data)
        if 'query' in data['query']:
            assert data['variables'] == {'id': 'R_test123'}
            return httpx.Response(200, json={'data': {'node': {'id': 'R_test123', 'nameWithOwner': 'example/project', 'isPrivate': False, 'isArchived': False, 'hasIssuesEnabled': True}}})
        mutation = data['variables']['input']
        assert mutation['repositoryId'] == 'R_test123'
        assert set(mutation) == {'repositoryId', 'title', 'body', 'clientMutationId'}
        return httpx.Response(200, json={'data': {'createIssue': {'clientMutationId': mutation['clientMutationId'],
            'issue': {'id': 'I_test123', 'number': 7, 'url': 'https://github.com/example/project/issues/7',
                      'title': mutation['title'], 'body': mutation['body'], 'repository': {'id': 'R_test123', 'nameWithOwner': 'example/project'}}}}})
    monkeypatch.setattr('airlock.github_adapter.network.client', lambda *a, **k: httpx.Client(transport=httpx.MockTransport(handler)))
    preview = adapter.preview(IssueArguments(title='Actual project task', body='Acceptance details'))
    result = adapter.execute(request(adapter))
    assert preview['after']['target_cas'] is False and result['state'] == 'executed'
    assert len([c for c in calls if 'mutation' in c['query']]) == 1
    adapter.execute(request(adapter))
    assert len(calls) == 3  # preview read, execution preflight read, one create


@contextmanager
def relay_server(tmp_path, monkeypatch):
    gate_token, relay_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    monkeypatch.setenv('AIRLOCK_UPSTREAM_GITHUB_GATE_TOKEN', gate_token)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    cfg = tmp_path / 'github.json'
    cfg.write_text(config().model_dump_json(), encoding='utf-8')
    env = {k: v for k, v in os.environ.items() if k in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP'}}
    env.update(AIRLOCK_UPSTREAM_GITHUB_GATE_TOKEN=gate_token, AIRLOCK_GITHUB_RELAY_TOKEN=relay_token)
    process = subprocess.Popen([sys.executable, 'scripts/github_adapter.py', 'serve', '--config', str(cfg),
                                '--database', str(tmp_path / 'adapter.db'), '--port', str(port)],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f'http://127.0.0.1:{port}'
    try:
        with httpx.Client(base_url=url, timeout=2, trust_env=False) as client:
            for _ in range(100):
                try:
                    if client.get('/receipts/absent').status_code == 403:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(.03)
            else:
                raise RuntimeError('adapter failed to start')
            yield url, relay_token, client
    finally:
        stop_process_tree(process)


def test_github_real_http_gate_review_relay_receipt_and_audit(settings, tmp_path, monkeypatch):
    with relay_server(tmp_path, monkeypatch) as (url, relay_token, client):
        upstream = tmp_path / 'upstreams.json'
        upstream.write_text(json.dumps({'tools': [{'name': 'upstream:github_issue', 'resource': 'github:issues',
            'url': url, 'allow_loopback': True, 'credential_env': 'AIRLOCK_UPSTREAM_GITHUB_GATE_TOKEN',
            'execution_model': 'append_only_create', 'arguments': {'title': 'string', 'body': 'string'}}]}))
        gate = Gate(replace(settings, upstream_file=upstream))
        invocation = Invocation(tool='upstream:github_issue', arguments={'title': 'Actual project task', 'body': 'Acceptance details'}, idempotency_key='github-review-001')
        action = gate.submit(invocation)
        assert action['state'] == 'pending'
        assert action['impact']['source'] == 'upstream_create_plan_without_target_cas'
        assert action['impact']['is_estimate'] and action['impact']['concurrency_control'] == 'no_target_cas'
        assert action['impact']['recovery_evidence']['technical_reversibility'] == 'not_fully_reversible'
        operator = {'Authorization': 'Bearer ' + relay_token}
        assert client.post('/operator/claim/' + action['id'], headers=operator).status_code == 404
        rejected = gate.decide(action['id'], decision(action, 'reject'))
        assert rejected['state'] == 'rejected'
        assert client.post('/operator/claim/' + action['id'], headers=operator).status_code == 404
        approved = gate.submit(invocation.model_copy(update={'idempotency_key': 'github-review-002'}))
        result = gate.decide(approved['id'], decision(approved))
        assert result['state'] == 'unknown'
        claim = client.post('/operator/claim/' + approved['id'], headers=operator).json()
        response = client.post('/operator/complete/' + approved['id'], headers=operator, json=completion(claim).model_dump())
        assert response.status_code == 200
        final = gate.remote.reconcile(gate.get(approved['id']))
        assert final['state'] == 'executed' and final['result']['receipt_verification'] == 'operator_attested'
        assert gate.submit(invocation.model_copy(update={'idempotency_key': 'github-review-002'}))['state'] == 'executed'
        assert gate.store.verify_audit()['valid']
