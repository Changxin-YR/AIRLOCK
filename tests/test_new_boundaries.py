from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import sqlite3
import pytest
from airlock.models import GateError,Invocation
from airlock.service import Gate
from conftest import call,decision,count
from test_upstream import upstream,request


def test_clock_rollback_across_restart_cannot_extend_approval(settings):
    now=[1000.0];gate=Gate(settings,clock=lambda:now[0]);action=gate.submit(call())
    now[0]=900.0;restart=Gate(settings,clock=lambda:now[0])
    with pytest.raises(GateError,match='clock_regression'): restart.decide(action['id'],decision(action))
    assert count(restart)==1206
    now[0]=action['expires_at']+1
    assert restart.get(action['id'])['state']=='expired'


def test_audited_reload_is_atomic_and_prior_approval_stale(settings,tmp_path,monkeypatch):
    path=tmp_path/'policy.yaml';path.write_text('version: first\nrules: []\n')
    gate=Gate(replace(settings,policy_file=path));action=gate.submit(call())
    path.write_text('version: second\nrules: []\n')
    audit=gate.store.audit
    def fail(*args,**kwargs):raise sqlite3.OperationalError('injected')
    monkeypatch.setattr(gate.store,'audit',fail)
    with pytest.raises(GateError):gate.reload_policy()
    assert gate.policy_version==action['policy_version']
    monkeypatch.setattr(gate.store,'audit',audit);gate.reload_policy()
    assert gate.decide(action['id'],decision(action))['state']=='stale'
    assert gate.store.verify_audit()['valid'] and count(gate)==1206


def test_remote_effect_survives_receipt_audit_failure_reconciles(settings,tmp_path,monkeypatch):
    with upstream(tmp_path,monkeypatch) as (config,target,spec):
        gate=Gate(replace(settings,upstream_file=config));action=gate.submit(request())
        audit=gate.store.audit
        def fail(conn,identifier,event):
            if event['kind']=='action.executed':raise sqlite3.OperationalError('injected receipt audit failure')
            return audit(conn,identifier,event)
        monkeypatch.setattr(gate.store,'audit',fail)
        with pytest.raises(sqlite3.OperationalError):gate.decide(action['id'],decision(action))
        assert target.get('/state').json()=={'value':3,'version':1}
        restart=Gate(gate.settings)
        assert restart.get(action['id'])['state']=='executing'
        assert restart.remote.reconcile(restart.get(action['id']))['state']=='executed'
        assert target.get('/state').json()['version']==1


def test_server_policy_reload_requires_operator(client,settings):
    assert client.post('/v1/policy/reload',headers={'Authorization':'Bearer '+settings.agent_token}).status_code==403


def test_argument_unicode_and_boolean_validation():
    with pytest.raises(ValueError):Invocation(sql='SELECT \ud800',idempotency_key='invalid-unicode')
    assert Invocation(tool='upstream:boolean',arguments={'enabled':True},idempotency_key='boolean-request').arguments['enabled'] is True


def test_model_disabled_ablation_keeps_all_four_arms():
    from benchmark.ablation import evaluate
    report=evaluate('dev',tuning=True)
    assert len(report['arms'])==4 and report['arms']['keyword']['metrics']['n']==120
    assert all(report['arms'][a]['status']=='BLOCKED_EXTERNAL' for a in ('pure_llm','hybrid_no_preview','hybrid_with_preview'))


def test_stored_expiry_tampering_invalidates_bound_review(gate):
    action=gate.submit(call())
    with gate.store.transaction() as conn:
        modified=dict(action,expires_at=action['expires_at']+1000);gate.store.save(conn,modified)
    assert gate.decide(action['id'],decision(action))['state']=='failed'
    assert count(gate)==1206
