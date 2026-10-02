from airlock.models import GovernanceChange
from airlock.observability import distribution
from conftest import call,decision,count


def test_metrics_unknown_cost_and_correlated_audit(client,settings):
    auth={'Authorization':'Bearer '+settings.agent_token}; reviewer={'Authorization':'Bearer '+settings.reviewer_token}
    response=client.post('/v1/actions',json=call().model_dump(),headers=auth)
    action=client.app.state.gate.get(response.json()['id'])
    assert action['request_id']==response.headers['x-request-id']
    event=client.app.state.gate.store.audit_events(action['id'])[0]['event']
    assert event['trace_id']==action['trace_id']
    metrics=client.get('/v1/metrics',headers=reviewer).json()
    assert metrics['semantic']['cost_usd'] is None and metrics['semantic']['input_tokens'] is None
    assert metrics['stages_ms']['preview_ms']['n']==1
    assert client.get('/v1/metrics',headers=auth).status_code==403


def test_percentiles_empty_and_known_sample():
    assert distribution([])['p95'] is None
    assert distribution([1,2,3,4])=={'n':4,'p50':2,'p95':4,'p99':4}


def test_shadow_suggestion_requires_explicit_versioned_activation(gate):
    for i in range(3):
        action=gate.submit(call('UPDATE customers SET balance=balance+1 WHERE id=1',f'shadow-{i:04}'))
        gate.decide(action['id'],decision(action))
    suggestion=gate.suggestions()[0]
    assert suggestion['mode']=='shadow' and gate.governance_preference()=={'version':0}
    change=GovernanceChange(candidate_digest=suggestion['digest'],expected_version=0,expires_at=gate.clock()+100,reason='Explicit operator experiment')
    assert gate.change_governance(change)['version']==1
    assert gate.submit(call(key='shadow-not-approved'))['state']=='pending'
    assert count(gate)==1206 and gate.store.verify_audit()['valid']
    assert gate.change_governance(change.model_copy(update={'expected_version':1}),True)['revoked']
