import sqlite3
import pytest
from airlock.models import GateError
from airlock.sql import snapshot,fingerprint
from conftest import call,decision,count


@pytest.mark.parametrize('sql',["DELETE FROM customers WHERE id=1","UPDATE customers SET balance=23 WHERE id=1","INSERT INTO customers VALUES(2000,'synthetic','standard',10)"])
def test_compensation_is_independent_approved_and_audited(gate,sql):
    with gate.store.connection() as conn: original=fingerprint(snapshot(conn))
    source=gate.submit(call(sql)); gate.decide(source['id'],decision(source))
    undo=gate.submit(call(source['id'],'compensation-action',tool='restore'))
    assert undo['state']=='pending' and undo['impact']['recovery_evidence']['restore_feasibility']=='rehearsed_in_clone'
    with gate.store.connection() as conn: assert fingerprint(snapshot(conn))!=original
    result=gate.decide(undo['id'],decision(undo)); assert result['state']=='executed'
    with gate.store.connection() as conn: assert fingerprint(snapshot(conn))==original
    assert gate.submit(call(source['id'],'compensation-action',tool='restore'))['id']==undo['id']
    assert gate.store.verify_audit()['valid']
    assert len(gate.store.audit_events(undo['id']))==2


def test_compensation_rejects_later_writes_and_other_principal(gate):
    source=gate.submit(call()); gate.decide(source['id'],decision(source))
    with pytest.raises(GateError,match='recovery_plan_unavailable'):
        gate.submit(call(source['id'],'wrong-owner',tool='restore'),'agent:other')
    undo=gate.submit(call(source['id'],'compensation-action',tool='restore'))
    change=gate.submit(call('UPDATE customers SET balance=2 WHERE id=2','later-write'))
    gate.decide(change['id'],decision(change))
    assert gate.decide(undo['id'],decision(undo))['state']=='stale'
    with pytest.raises(GateError,match='recovery_target_drift'):
        gate.submit(call(source['id'],'compensation-new',tool='restore'))
    assert count(gate)==1205


def test_compensation_audit_failure_rolls_back(gate,monkeypatch):
    source=gate.submit(call()); gate.decide(source['id'],decision(source))
    undo=gate.submit(call(source['id'],'compensation-action',tool='restore'))
    def fail(*args,**kwargs): raise sqlite3.OperationalError('disk full')
    monkeypatch.setattr(gate.store,'audit',fail)
    with pytest.raises(sqlite3.OperationalError): gate.decide(undo['id'],decision(undo))
    assert count(gate)==1205 and gate.get(undo['id'])['state']=='pending'
