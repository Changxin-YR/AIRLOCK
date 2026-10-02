import pytest
from conftest import call
from test_api import auth

def test_server_filtered_pending_queue_survives_long_read_history(gate):
    pending=gate.submit(call(key='old-pending-action'))
    for i in range(105):
        gate.submit(call('SELECT 1',key=f'history-read-{i}'))
    assert not any(a['id']==pending['id'] for a in gate.list_actions(100))
    assert [a['id'] for a in gate.list_actions(100,state_filter='pending')]==[pending['id']]


def test_state_filter_is_validated_and_applied(client,settings):
    agent=auth(settings.agent_token);reviewer=auth(settings.reviewer_token)
    client.post('/v1/actions',json=call().model_dump(),headers=agent)
    client.post('/v1/actions',json=call('SELECT 1',key='read-filter-001').model_dump(),headers=agent)
    results=client.get('/v1/actions?state=pending',headers=reviewer).json()['items']
    assert len(results)==1 and results[0]['state']=='pending'
    assert client.get('/v1/actions?state=approved',headers=reviewer).status_code==422
    assert client.get('/v1/actions?before=NaN&before_id='+'a'*32,headers=reviewer).status_code==422


@pytest.mark.parametrize("literal", ["NaN", "Infinity"])
def test_nonfinite_json_fails_closed_without_breaking_error_response(client, settings, literal):
    body='{"sql":"SELECT ?","parameters":['+literal+'],"idempotency_key":"invalid-number-001"}'
    response=client.post('/v1/actions',content=body,headers=auth(settings.agent_token)|{'Content-Type':'application/json'})
    assert response.status_code==422
    assert response.json()['error']=='validation_error' and response.json()['execution_occurred'] is False
