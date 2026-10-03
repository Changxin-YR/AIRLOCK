"""Second-author batch scope checks; isolated synthetic fixtures only."""
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

from airlock import governance
from airlock.models import Settings, Invocation, BatchDecision
from airlock.service import Gate


@pytest.mark.parametrize('revocation', ['critical', 'resource', 'account'])
def test_first_member_authority_snapshot_enforces_live_revocation(tmp_path, monkeypatch, revocation):
    path = tmp_path / 'accounts.json'
    document = {'reviewers': [{'id': 'reviewer:cross', 'credential_env': 'AIRLOCK_REVIEWER_CROSS',
        'tools': ['sql'], 'resources': ['customers'], 'risks': ['high', 'critical']}]}
    path.write_text(json.dumps(document))
    monkeypatch.setenv('AIRLOCK_REVIEWER_CROSS', 'cross-' + 's' * 32)
    settings = Settings(tmp_path / 'cross.db', 'agent-' + 'a' * 32, 'owner-' + 'o' * 32, 'audit-' + 'h' * 32)
    gate = Gate(replace(settings, reviewer_file=path, critical_rows=2), clock=lambda: 1000.0)
    for index in range(2):
        gate.submit(Invocation(sql='UPDATE customers SET balance=balance WHERE id=1', idempotency_key=f'cross-member-{index}'))
    group = gate.groups('reviewer:cross')[0]
    request = BatchDecision(group_id=group['id'], group_digest=group['digest'],
        member_ids=[item['id'] for item in group['members']], decision='approve',
        reason='Second author independent boundary check', confirmation=group['confirmation_required'])
    accounts = gate.access.accounts
    boundary_reads = []

    def current_accounts():
        if governance.batch_context.get() is not None:
            boundary_reads.append(governance.batch_risk.get())
            if revocation == 'critical':
                document['reviewers'][0]['risks'] = ['high']
            elif revocation == 'resource':
                document['reviewers'][0]['resources'] = ['elsewhere']
            else:
                document['reviewers'][0]['active'] = False
            path.write_text(json.dumps(document))
        return accounts()

    monkeypatch.setattr(gate.access, 'accounts', current_accounts)
    response = gate.decide_group(request, 'reviewer:cross')
    assert [item['state'] for item in response['receipts']] == ['conflict', 'conflict']
    assert boundary_reads == ['critical', 'critical']
    assert all(gate.get(item['id'])['state'] == 'pending' for item in group['members'])
    assert len(gate.store.audit_events()) == 2 and gate.store.verify_audit()['valid']
    assert governance.batch_context.get() is None and governance.batch_risk.get() is None
    with gate.store.connection() as conn:
        assert conn.execute('SELECT count(*) FROM customers').fetchone()[0] == 1206
        assert dict(conn.execute('SELECT state,count(*) FROM risk_budget GROUP BY state')) == {'reserved': 2}


def test_rejection_never_requires_critical_approval_authority(tmp_path, monkeypatch):
    path = tmp_path / 'accounts.json'
    document = {'reviewers': [{'id': 'reviewer:reject', 'credential_env': 'AIRLOCK_REVIEWER_REJECT',
        'tools': ['sql'], 'resources': ['customers'], 'risks': ['high']}]}
    path.write_text(json.dumps(document))
    monkeypatch.setenv('AIRLOCK_REVIEWER_REJECT', 'cross-' + 'x' * 32)
    settings = Settings(tmp_path / 'reject.db', 'agent-' + 'a' * 32, 'owner-' + 'o' * 32, 'audit-' + 'h' * 32)
    gate = Gate(replace(settings, reviewer_file=path, critical_rows=2), clock=lambda: 1000.0)
    for index in range(2):
        gate.submit(Invocation(sql='UPDATE customers SET balance=balance WHERE id=1', idempotency_key=f'reject-{index}'))
    group = gate.groups('reviewer:reject')[0]
    request = BatchDecision(group_id=group['id'], group_digest=group['digest'],
        member_ids=[item['id'] for item in group['members']], decision='reject',
        reason='Second author independent rejection check', confirmation=group['confirmation_required'])
    response = gate.decide_group(request, 'reviewer:reject')
    assert [item['state'] for item in response['receipts']] == ['rejected', 'rejected']
    assert len(gate.store.audit_events()) == 4 and gate.store.verify_audit()['valid']
    assert governance.batch_context.get() is None and governance.batch_risk.get() is None
    with gate.store.connection() as conn:
        assert conn.execute('SELECT count(*) FROM customers').fetchone()[0] == 1206
        assert dict(conn.execute('SELECT state,count(*) FROM risk_budget GROUP BY state')) == {'released': 2}


def test_remote_batch_revocation_prevents_any_http_effect(tmp_path, monkeypatch):
    # Reuse only the existing isolated loopback process launcher, not its assertions.
    sys.path.insert(0, str(Path(__file__).resolve().parents[4] / 'tests'))
    from test_upstream import upstream
    path = tmp_path / 'remote-accounts.json'
    document = {'reviewers': [{'id': 'reviewer:remote', 'credential_env': 'AIRLOCK_REVIEWER_CROSS_REMOTE',
        'tools': ['upstream:counter'], 'resources': ['synthetic:counter'], 'risks': ['high', 'critical']}]}
    path.write_text(json.dumps(document))
    monkeypatch.setenv('AIRLOCK_REVIEWER_CROSS_REMOTE', 'cross-remote-' + 's' * 32)
    settings = Settings(tmp_path / 'remote.db', 'agent-' + 'a' * 32, 'owner-' + 'o' * 32, 'audit-' + 'h' * 32)
    with upstream(tmp_path, monkeypatch) as (configuration, target, _):
        gate = Gate(replace(settings, upstream_file=configuration, reviewer_file=path, critical_rows=2), clock=lambda: 1000.0)
        for index in range(2):
            item = gate.submit(Invocation(tool='upstream:counter', arguments={'delta': 3}, idempotency_key=f'remote-cross-{index}'))
            assert item['risk'] == 'high' and item['state'] == 'pending'
        group = gate.groups('reviewer:remote')[0]
        assert group['cumulative_units'] == 2
        request = BatchDecision(group_id=group['id'], group_digest=group['digest'],
            member_ids=[item['id'] for item in group['members']], decision='approve',
            reason='Second author remote transaction check', confirmation=group['confirmation_required'])
        accounts = gate.access.accounts

        def revoked_snapshot():
            if governance.batch_context.get() is not None:
                document['reviewers'][0]['risks'] = ['high']
                path.write_text(json.dumps(document))
            return accounts()

        monkeypatch.setattr(gate.access, 'accounts', revoked_snapshot)
        response = gate.decide_group(request, 'reviewer:remote')
        assert [item['state'] for item in response['receipts']] == ['conflict', 'conflict']
        assert all(item['reason_code'] == 'group_risk_route_forbidden' for item in response['receipts'])
        assert target.get('/state').json() == {'value': 0, 'version': 0}
        assert all(gate.get(item['id'])['state'] == 'pending' for item in group['members'])
        assert len(gate.store.audit_events()) == 2 and gate.store.verify_audit()['valid']
        assert governance.batch_context.get() is None and governance.batch_risk.get() is None
