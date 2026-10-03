"""Second-author audit scan probes: linked hidden rows, snapshot reads and cursor integrity."""
import json
import ast
import os
from pathlib import Path
import textwrap
from dataclasses import replace

import pytest

from airlock.models import Decision, Invocation, Settings
from airlock.service import Gate
from airlock.sql import snapshot


@pytest.fixture(autouse=True)
def original_method_only(monkeypatch):
    if os.getenv('AIRLOCK_AUDIT_COUNTERCHECK_BASELINE') != '1':
        return
    text = (Path(__file__).parent / 'baseline-service.py').read_text(encoding='utf-8')
    gate_class = next(node for node in ast.parse(text).body if isinstance(node, ast.ClassDef) and node.name == 'Gate')
    method = next(node for node in gate_class.body if isinstance(node, ast.FunctionDef) and node.name == 'audit_events')
    namespace = {'json': json}
    exec(compile(textwrap.dedent(ast.get_source_segment(text, method)), 'baseline-service.py:audit_events', 'exec'), namespace)
    monkeypatch.setattr(Gate, 'audit_events', namespace['audit_events'])


@pytest.fixture
def scoped(tmp_path, monkeypatch):
    config = {'reviewers': [
        {'id': 'reviewer:small', 'credential_env': 'AIRLOCK_REVIEWER_SECOND_SMALL',
         'tools': ['sql'], 'resources': ['customers'], 'risks': ['high']},
        {'id': 'reviewer:large', 'credential_env': 'AIRLOCK_REVIEWER_SECOND_LARGE',
         'tools': ['sql'], 'resources': ['customers'], 'risks': ['critical']},
    ]}
    path = tmp_path / 'second-author-reviewers.json'
    path.write_text(json.dumps(config), encoding='utf-8')
    monkeypatch.setenv('AIRLOCK_REVIEWER_SECOND_SMALL', 'synthetic-small-' + 's' * 32)
    monkeypatch.setenv('AIRLOCK_REVIEWER_SECOND_LARGE', 'synthetic-large-' + 'l' * 32)
    settings = Settings(tmp_path / 'second-author.db', 'synthetic-agent-' + 'a' * 32,
        'synthetic-owner-' + 'b' * 32, 'synthetic-audit-' + 'c' * 32,
        reviewer_file=path, max_actions=2, seed_rows=5, critical_rows=3)
    gate = Gate(settings, clock=lambda: 1000.0)
    return gate, path, config


def request(key, sql='UPDATE customers SET balance=balance WHERE id=1'):
    return Invocation(idempotency_key=key, sql=sql)


def append_event(gate, action_id, kind='action.countercheck'):
    with gate.store.transaction() as conn:
        gate.store.audit(conn, action_id, {'kind': kind, 'at': 1000.0, 'state': 'synthetic_probe',
            'detail': {'countercheck': True}})


def test_linked_invisible_action_prefix_does_not_starve_page(scoped):
    gate, _, _ = scoped
    hidden = gate.submit(request('counter-hidden', 'UPDATE customers SET balance=balance+1'))
    assert hidden['risk'] == 'critical'
    for _ in range(12):
        append_event(gate, hidden['id'])
    visible = gate.submit(request('counter-visible'))
    gate.decide(visible['id'], Decision(decision='reject', review_digest=visible['review_digest'],
        expected_version=visible['version'], reason='Synthetic independent countercheck'), 'reviewer:small')
    original = gate.store.audit_events(limit=100)
    with gate.store.connection() as conn:
        before = snapshot(conn)
    page1 = gate.audit_events('reviewer:small', after=0, limit=1)
    assert len(page1) == 1
    page2 = gate.audit_events('reviewer:small', after=page1[0]['seq'], limit=1)
    assert page1 + page2 == [event for event in original if event['action_id'] == visible['id']]
    assert gate.audit_events('reviewer:small', after=page2[0]['seq'], limit=1) == []
    assert gate.audit_events('reviewer:small', action_id=hidden['id']) == []
    assert gate.store.audit_events(limit=100) == original
    with gate.store.connection() as conn:
        assert snapshot(conn) == before
    assert gate.store.verify_audit()['valid']


def test_scan_uses_one_database_read_snapshot_during_concurrent_append(scoped, monkeypatch):
    gate, _, _ = scoped
    visible = gate.submit(request('counter-snapshot'))
    append_event(gate, visible['id'])
    original = gate.store.audit_events(limit=100)
    can_review = gate.access.can_review
    appended = []

    def concurrent_append(who, action):
        if not appended:
            append_event(gate, action['id'])
            appended.append(True)
        return can_review(who, action)

    monkeypatch.setattr(gate.access, 'can_review', concurrent_append)
    scanned = gate.audit_events('reviewer:small', limit=100)
    assert scanned == original
    next_page = gate.audit_events('reviewer:small', after=scanned[-1]['seq'], limit=100)
    assert len(next_page) == 1 and next_page[0]['seq'] == scanned[-1]['seq'] + 1
    assert next_page[0]['action_id'] == visible['id']
    assert next_page[0]['previous_hash'] == scanned[-1]['signature']
    assert gate.get(visible['id'])['state'] == 'pending' and gate.store.verify_audit()['valid']


def test_route_revocation_during_scan_stops_later_visible_events(scoped, monkeypatch):
    gate, path, config = scoped
    visible = gate.submit(request('counter-revoke'))
    append_event(gate, visible['id'])
    original = gate.store.audit_events(limit=100)
    can_review = gate.access.can_review
    calls = []

    def revoke_on_second(who, action):
        calls.append(True)
        if len(calls) == 2:
            config['reviewers'][0]['active'] = False
            path.write_text(json.dumps(config), encoding='utf-8')
        return can_review(who, action)

    monkeypatch.setattr(gate.access, 'can_review', revoke_on_second)
    assert gate.audit_events('reviewer:small', limit=100) == original[:1]
    assert gate.audit_events('reviewer:small', after=original[0]['seq'], limit=100) == []
    assert gate.store.audit_events(limit=100) == original
    assert gate.store.verify_audit()['valid']


def test_owner_sees_governance_but_not_orphan_action_events(tmp_path):
    gate = Gate(Settings(tmp_path / 'owner.db', 'a' * 32, 'b' * 32, 'c' * 32, max_actions=1, seed_rows=3))
    for index in range(6):
        append_event(gate, f'governance:second-author-{index}', kind='governance.changed')
    append_event(gate, 'nonexistent-action')
    original = gate.store.audit_events(limit=100)
    assert gate.audit_events('reviewer:owner', limit=100) == original[:6]
    assert gate.audit_events('reviewer:owner', action_id='nonexistent-action', limit=100) == []
    assert gate.store.audit_events(limit=100) == original and gate.store.verify_audit()['valid']


@pytest.mark.parametrize('missing', ["' OR 1=1 --", 'unknown-action', 'governance:cache'])
def test_action_filter_does_not_broaden_scope(scoped, missing):
    gate, _, _ = scoped
    visible = gate.submit(request('counter-filter'))
    original = gate.store.audit_events(limit=100)
    assert len(gate.audit_events('reviewer:small', action_id=visible['id'])) == 1
    assert gate.audit_events('reviewer:small', action_id=missing) == []
    assert gate.audit_events('reviewer:small', after=10000) == []
    assert gate.store.audit_events(limit=100) == original and gate.store.verify_audit()['valid']
