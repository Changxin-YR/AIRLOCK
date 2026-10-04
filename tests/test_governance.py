from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import pytest
from airlock.models import BatchDecision,GateError
from airlock.service import Gate
from conftest import call,decision,count


def test_budget_reservation_concurrency_restart_and_settlement(settings):
    settings=replace(settings,budget_units=2)
    gate=Gate(settings)
    def submit(i): return Gate(settings).submit(call(key=f'budget-{i:04}'))
    with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(submit,range(4)))
    assert sum(r['state']=='pending' for r in results)==2
    assert count(gate)==1206
    first=next(r for r in results if r['state']=='pending')
    gate.decide(first['id'],decision(first))
    assert Gate(settings).submit(call(key='different-id'))['reason_code']=='risk_budget_exhausted'
    with gate.store.connection() as conn:
        assert conn.execute("SELECT sum(units) FROM risk_budget WHERE state IN ('reserved','settled')").fetchone()[0]==2


def batch(group):
    return BatchDecision(group_id=group['id'],group_digest=group['digest'],member_ids=[a['id'] for a in group['members']],
        decision='approve',reason='Reviewed each explicit snapshot',confirmation=group['confirmation_required'])


def test_group_new_members_require_reconfirmation_and_no_hidden_execution(gate):
    gate.submit(call()); old=gate.groups('reviewer:owner')[0]
    gate.submit(call('DELETE FROM customers WHERE id=2','second-member'))
    with pytest.raises(GateError,match='group_membership_changed'):
        gate.decide_group(batch(old),'reviewer:owner')
    assert count(gate)==1206
    group=gate.groups('reviewer:owner')[0]
    receipts=gate.decide_group(batch(group),'reviewer:owner')['receipts']
    assert sorted(r['state'] for r in receipts)==['executed','stale']
    assert count(gate)==1205 and gate.store.verify_audit()['valid']


def test_rejected_reservation_releases_but_no_automatic_permission(settings):
    gate=Gate(replace(settings,budget_units=1))
    action=gate.submit(call()); gate.decide(action['id'],decision(action,'reject'))
    next_action=gate.submit(call(key='next-budget-action'))
    assert next_action['state']=='pending' and count(gate)==1206
