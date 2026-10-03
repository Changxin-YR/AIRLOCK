"""Independent edge probes for persisted governance and live batch authority."""
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event

import pytest
from fastapi.testclient import TestClient
from airlock.api import create_app
from airlock import governance
from airlock.service import Gate
from conftest import call, count, decision
from test_governance import batch


@pytest.mark.parametrize('revocation_point', ['between_members', 'inside_member_decision'])
def test_batch_revalidates_cumulative_risk_route_before_each_member(settings, tmp_path, monkeypatch, revocation_point):
    path = tmp_path / 'reviewers.json'
    config = {'reviewers': [{'id': 'reviewer:batch', 'credential_env': 'AIRLOCK_REVIEWER_BATCH',
        'tools': ['sql'], 'resources': ['customers'], 'risks': ['high', 'critical']}]}
    path.write_text(json.dumps(config), encoding='utf-8')
    monkeypatch.setenv('AIRLOCK_REVIEWER_BATCH', 'synthetic-batch-reviewer-' + 'x' * 32)
    gate = Gate(replace(settings, reviewer_file=path, critical_rows=2), clock=lambda: 1000.0)
    # The target remains unchanged, so snapshot drift cannot hide the route defect.
    for number in range(2):
        action = gate.submit(call('UPDATE customers SET balance=balance WHERE id=1', f'batch-route-{number}'))
        assert action['risk'] == 'high' and action['impact']['matched_rows'] == 1
    group = gate.groups('reviewer:batch')[0]
    assert group['cumulative_units'] == 2
    decide = gate._decide
    calls = [0]

    def revoke():
        config['reviewers'][0]['risks'] = ['high']
        path.write_text(json.dumps(config), encoding='utf-8')

    def revoke_critical_after_first_member(*args, **kwargs):
        if revocation_point == 'inside_member_decision' and calls[0] == 1:
            revoke()
        result = decide(*args, **kwargs)
        calls[0] += 1
        if revocation_point == 'between_members':
            revoke()
        return result

    monkeypatch.setattr(gate, '_decide', revoke_critical_after_first_member)
    result = gate.decide_group(batch(group), 'reviewer:batch')
    assert result['receipts'][0]['state'] == 'executed'
    assert result['receipts'][1] == {'id': group['members'][1]['id'], 'state': 'conflict',
        'reason_code': 'group_risk_route_forbidden'}
    assert gate.get(group['members'][1]['id'])['state'] == 'pending'
    with gate.store.connection() as conn:
        assert dict(conn.execute('SELECT state,count(*) FROM risk_budget GROUP BY state')) == {'reserved': 1, 'settled': 1}
    assert count(gate) == 1206 and gate.store.verify_audit()['valid']


def test_batch_context_stays_in_its_thread_and_resets_after_conflict(settings, tmp_path, monkeypatch):
    path = tmp_path / 'thread-reviewers.json'
    config = {'reviewers': [{'id': 'reviewer:batch', 'credential_env': 'AIRLOCK_REVIEWER_BATCH',
        'tools': ['sql'], 'resources': ['customers'], 'risks': ['high', 'critical']}]}
    path.write_text(json.dumps(config), encoding='utf-8')
    monkeypatch.setenv('AIRLOCK_REVIEWER_BATCH', 'synthetic-batch-reviewer-' + 'x' * 32)
    settings = replace(settings, reviewer_file=path, critical_rows=2)
    gate = Gate(settings, clock=lambda: 1000.0)
    for number in range(2):
        gate.submit(call('UPDATE customers SET balance=balance WHERE id=1', f'thread-member-{number}'))
    independent = Gate(settings, clock=lambda: 1000.0)
    standalone = independent.submit(call('UPDATE customers SET balance=balance WHERE id=1', 'thread-independent'), 'agent:other')
    group = next(item for item in gate.groups('reviewer:batch') if len(item['members']) == 2)
    first_done, continue_batch = Event(), Event()
    decide = gate._decide
    observed = []

    def pause_after_first(*args, **kwargs):
        observed.append((governance.batch_context.get(), governance.batch_risk.get()))
        result = decide(*args, **kwargs)
        if not first_done.is_set():
            first_done.set()
            assert continue_batch.wait(10)
        return result

    def run_batch():
        result = gate.decide_group(batch(group), 'reviewer:batch')
        assert governance.batch_context.get() is None and governance.batch_risk.get() is None
        return result

    monkeypatch.setattr(gate, '_decide', pause_after_first)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run_batch)
        try:
            assert first_done.wait(10)
            assert governance.batch_context.get() is None and governance.batch_risk.get() is None
            config['reviewers'][0]['risks'] = ['high']
            path.write_text(json.dumps(config), encoding='utf-8')
            assert independent.decide(standalone['id'], decision(standalone), 'reviewer:batch')['state'] == 'executed'
        finally:
            continue_batch.set()
        result = future.result(timeout=10)
    assert [item['state'] for item in result['receipts']] == ['executed', 'conflict']
    assert observed == [(group['digest'], 'critical'), (group['digest'], 'critical')]
    assert gate.store.verify_audit()['valid'] and count(gate) == 1206


def test_batch_context_resets_after_unexpected_member_failure(gate, monkeypatch):
    gate.submit(call(key='context-reset'))
    group = gate.groups('reviewer:owner')[0]

    def fail(*args, **kwargs):
        assert governance.batch_context.get() == group['digest']
        raise RuntimeError('synthetic member boundary failure')

    monkeypatch.setattr(gate, '_decide', fail)
    with pytest.raises(RuntimeError, match='synthetic member boundary failure'):
        gate.decide_group(batch(group), 'reviewer:owner')
    assert governance.batch_context.get() is None and governance.batch_risk.get() is None
    assert gate.get(group['members'][0]['id'])['state'] == 'pending'
    assert count(gate) == 1206 and gate.store.verify_audit()['valid']


@pytest.mark.parametrize('reason', ['   ', '\t\r\n', 'review \ud800'])
def test_batch_invalid_reason_is_rejected_before_member_decisions(settings, reason):
    with TestClient(create_app(settings), base_url=settings.origin, raise_server_exceptions=False) as client:
        gate = client.app.state.gate
        gate.clock = lambda: 1000.0
        action = gate.submit(call())
        group = gate.groups('reviewer:owner')[0]
        body = batch(group).model_dump()
        body['reason'] = reason
        response = client.post('/v1/groups/decision', content=json.dumps(body),
            headers={'Authorization': 'Bearer ' + settings.reviewer_token, 'Content-Type': 'application/json'})
        assert response.status_code == 422
        assert response.json()['execution_occurred'] is False
        assert gate.get(action['id'])['state'] == 'pending'
        assert len(gate.store.audit_events(action['id'])) == 1
        assert count(gate) == 1206 and gate.store.verify_audit()['valid']


def test_budget_principals_expiry_and_restart_preserve_reservations(settings):
    now = [1000.0]
    settings = replace(settings, budget_units=1, seed_rows=3, ttl_seconds=10)
    gate = Gate(settings, clock=lambda: now[0])
    first = gate.submit(call(key='actor-budget'), 'agent:first')
    other = gate.submit(call(key='actor-budget'), 'agent:other')
    assert first['state'] == other['state'] == 'pending'
    assert first['budget']['scope'] != other['budget']['scope']
    restarted = Gate(settings, clock=lambda: now[0])
    assert restarted.submit(call(key='actor-overbudget'), 'agent:first')['reason_code'] == 'risk_budget_exhausted'
    now[0] += 10
    replacement = restarted.submit(call(key='actor-after-expiry'), 'agent:first')
    assert replacement['state'] == 'pending'
    assert restarted.get(first['id'])['state'] == restarted.get(other['id'])['state'] == 'expired'
    with restarted.store.connection() as conn:
        assert dict(conn.execute('SELECT state,count(*) FROM risk_budget GROUP BY state')) == {'released': 2, 'reserved': 1}
    assert count(restarted) == 3 and restarted.store.verify_audit()['valid']


def test_compensation_of_compensation_keeps_three_independent_approvals(gate):
    source = gate.submit(call('UPDATE customers SET balance=balance+5 WHERE id=1', 'nested-source'))
    assert gate.decide(source['id'], decision(source))['state'] == 'executed'
    undo = gate.submit(call(source['id'], 'nested-undo', tool='restore'))
    with gate.store.connection() as conn:
        assert conn.execute('SELECT balance FROM customers WHERE id=1').fetchone()[0] == 1005
    assert gate.decide(undo['id'], decision(undo))['state'] == 'executed'
    redo = gate.submit(call(undo['id'], 'nested-redo', tool='restore'))
    assert redo['state'] == 'pending'
    with gate.store.connection() as conn:
        assert conn.execute('SELECT balance FROM customers WHERE id=1').fetchone()[0] == 1000
    assert gate.decide(redo['id'], decision(redo))['state'] == 'executed'
    with gate.store.connection() as conn:
        assert conn.execute('SELECT balance FROM customers WHERE id=1').fetchone()[0] == 1005
        assert conn.execute("SELECT count(*) FROM risk_budget WHERE state='settled'").fetchone()[0] == 3
    assert all(len(gate.store.audit_events(item['id'])) == 2 for item in [source, undo, redo])
    assert gate.store.verify_audit()['valid']


def test_restore_rejects_target_trigger_added_after_review(gate):
    source = gate.submit(call('UPDATE customers SET balance=1005 WHERE id=1', 'trigger-source'))
    gate.decide(source['id'], decision(source))
    undo = gate.submit(call(source['id'], 'trigger-undo', tool='restore'))
    with gate.store.transaction() as conn:
        conn.execute('CREATE TRIGGER changed_target AFTER DELETE ON customers BEGIN UPDATE customers SET balance=1; END')
    result = gate.decide(undo['id'], decision(undo))
    assert result['state'] == 'failed' and result['reason_code'] == 'execution_failed'
    with gate.store.connection() as conn:
        assert conn.execute('SELECT balance FROM customers WHERE id=1').fetchone()[0] == 1005
        assert conn.execute('SELECT state FROM risk_budget WHERE action_id=?', (undo['id'],)).fetchone()[0] == 'released'
    assert count(gate) == 1206 and gate.store.verify_audit()['valid']
