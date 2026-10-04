from dataclasses import replace
import copy
import json
from airlock.audit_schema import completeness,STATES
from airlock.service import Gate
from conftest import call,decision
from test_upstream import upstream,request


def test_audit_schema_all_states_with_original_snapshot_and_explicit_na(settings,tmp_path,monkeypatch):
    with upstream(tmp_path,monkeypatch,drop=True) as (config,target,spec):
        clock=[1000.0];gate=Gate(replace(settings,upstream_file=config),clock=lambda:clock[0])
        gate.submit(call('DROP TABLE customers',key='schema-block'))
        gate.submit(call('SELECT 1',key='schema-read'))
        rejected=gate.submit(call(key='schema-reject'));gate.decide(rejected['id'],decision(rejected,'reject'))
        stale=gate.submit(call(key='schema-stale'));write=gate.submit(call('UPDATE customers SET balance=balance+1 WHERE id=1',key='schema-write'))
        gate.decide(write['id'],decision(write));gate.decide(stale['id'],decision(stale))
        failed=gate.submit(call('UPDATE customers SET balance=balance+1 WHERE id=2',key='schema-failed'))
        with gate.store.transaction() as conn:conn.execute("CREATE TRIGGER test_failure BEFORE UPDATE ON customers BEGIN SELECT RAISE(ABORT,'fixture'); END")
        gate.decide(failed['id'],decision(failed))
        with gate.store.transaction() as conn:conn.execute('DROP TRIGGER test_failure')
        remote=gate.submit(request());gate.decide(remote['id'],decision(remote));gate.remote.reconcile(gate.get(remote['id']))
        drifting=gate.submit(request('schema-remote-stale'));changing=gate.submit(request('schema-remote-change'))
        gate.decide(changing['id'],decision(changing));gate.remote.reconcile(gate.get(changing['id']))
        gate.decide(drifting['id'],decision(drifting));gate.remote.reconcile(gate.get(drifting['id']))
        assert gate.get(drifting['id'])['state']=='stale'
        expired=gate.submit(call(key='schema-expired'));clock[0]+=301;gate.get(expired['id'])
        events=gate.store.audit_events(limit=1000);report=completeness(events)
        assert report['completeness']==1,report
        assert set(report['states'])==STATES
        assert gate.store.verify_audit()['valid']
        # Independently damage replay evidence. Integrity and schema are different checks.
        damaged=copy.deepcopy(events);del damaged[0]['event']['detail']['snapshot']['policy_version']
        assert completeness(damaged)['completeness']<1
        without_claims=[e for e in events if e['event']['kind']!='action.executing']
        assert completeness(without_claims)['completeness']<1


def test_audit_completeness_access_and_empty(client,settings):
    assert client.get('/v1/audit/completeness',headers={'Authorization':'Bearer '+settings.agent_token}).status_code==403
    assert client.get('/v1/audit/completeness',headers={'Authorization':'Bearer '+settings.reviewer_token}).json()['completeness'] is None
