import json
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from airlock.api import COOKIE, create_app
from airlock.contracts import ToolRequest
from airlock.runner_api import create_app as create_runner_app
from airlock.storage import principals
from conftest import AGENT_TOKEN, OTHER_TOKEN, PASSWORD


def client_for(system):
    return TestClient(create_app(system.settings, store=system.store, runner=system.service.runner,
                                service=system.service))


def human_client(system):
    client = client_for(system)
    client.cookies.set(COOKIE, system.cookie)
    client.headers.update({'origin': 'http://testserver', 'x-csrf-token': system.human['csrf']})
    return client


def proposal(**kw):
    return {'tool': 'db.update_rows', 'filters': [{'field': 'id', 'op': 'in', 'value': [1, 2]}],
            'values': {'status': 'archived'}, **kw}


def decision(op, **kw):
    return {'decision': 'approve', 'plan_digest': op['plan']['plan_digest'],
            'view_digest': op['plan']['view_digest'], 'expected_version': op['version'],
            'decision_key': 'decision-http-001', 'reason': '', **kw}


def test_real_http_roundtrip(system):
    agent = client_for(system)
    human = human_client(system)
    response = agent.post('/api/operations', json=proposal(), headers={
        'authorization': 'Bearer '+AGENT_TOKEN, 'idempotency-key': 'http-request-001'})
    assert response.status_code == 202, response.text
    op_id = response.json()['id']
    system.service.drain()
    op = human.get('/api/operations/'+op_id).json()
    assert op['state'] == 'PENDING_APPROVAL'
    response = human.post('/api/reviews/'+op_id+'/decision', json=decision(op))
    assert response.status_code == 200, response.text
    assert response.json()['state'] == 'READY'  # Approval is NOT execution success.
    system.service.drain()
    result = agent.get('/api/operations/'+op_id, headers={'authorization': 'Bearer '+AGENT_TOKEN})
    assert result.json()['state'] == 'SUCCEEDED'
    assert 'plan' not in result.json()
    assert human.get('/api/reviews/'+op_id+'/audit').json()['chain_valid']


def test_login_cookie_origin_csrf_and_logout(system):
    client = client_for(system)
    body = {'username': 'reviewer', 'password': PASSWORD}
    assert client.post('/api/session', json=body).status_code == 403
    response = client.post('/api/session', json=body, headers={'origin': 'http://testserver'})
    assert response.status_code == 200, response.text
    cookie = response.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=strict' in cookie and 'path=/' in cookie
    csrf = response.json()['csrf']
    assert client.get('/api/session').status_code == 200
    assert client.post('/api/session/logout', headers={'origin': 'http://testserver'}).status_code == 403
    assert client.post('/api/session/logout', headers={'origin': 'https://evil.example', 'x-csrf-token': csrf}).status_code == 403
    assert client.post('/api/session/logout', headers={'origin': 'http://testserver', 'x-csrf-token': csrf}).status_code == 200
    assert client.get('/api/session').status_code == 401


def test_agent_cannot_use_human_endpoints_even_with_cookie(system):
    client = human_client(system)
    client.headers['authorization'] = 'Bearer '+AGENT_TOKEN
    for path in ['/api/session', '/api/overview', '/api/policy', '/api/demo/scenarios']:
        assert client.get(path).status_code == 403
    assert client.post('/api/reviews/guess/decision', json={}).status_code in (403, 422)
    assert client.post('/api/session/logout').status_code == 403


@pytest.mark.parametrize('body', [
    '{"tool":"db.query_rows","tool":"db.delete_rows"}',
    '{"tool":"db.query_rows","limit":NaN}',
    '{"tool":"db.query_rows","task":"\\ud800"}',
])
def test_ambiguous_json_closed(system, body):
    response = client_for(system).post('/api/operations', content=body,
        headers={'authorization': 'Bearer '+AGENT_TOKEN, 'idempotency-key': 'json-validation-01',
                 'content-type': 'application/json'})
    assert response.status_code == 400
    assert response.json()['error']['code'] == 'INVALID_JSON'


@pytest.mark.parametrize('patch', [
    {'approved': True}, {'approver_id': 'reviewer'}, {'role': 'admin'}, {'resource_id': '../../target.db'},
    {'table': 'execution_receipts'}, {'tool': 'shell.exec'}, {'limit': True},
    {'values': {'version': '0'}}, {'columns': ['password']},
])
def test_strict_tools_reject_escalation(system, patch):
    response = client_for(system).post('/api/operations', json=proposal(**patch),
        headers={'authorization': 'Bearer '+AGENT_TOKEN, 'idempotency-key': 'http-invalid-001'})
    assert response.status_code == 422, response.text
    assert response.json()['error']['code'] == 'VALIDATION_ERROR'


def test_ingress_size_content_type_headers_and_hosts(system):
    client = client_for(system)
    assert client.post('/api/operations', content='x'*40000).status_code == 413
    assert client.post('/api/operations', content='{}').status_code == 415
    response = client.get('/api/overview', headers=[('authorization', 'Bearer a'), ('authorization', 'Bearer b')])
    assert response.status_code == 400
    assert client.get('/healthz', headers={'host': 'evil.example'}).status_code == 400
    response = client.get('/api/session')
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-frame-options'] == 'DENY'
    assert "script-src 'self'" in response.headers['content-security-policy']
    assert response.headers['referrer-policy'] == 'no-referrer'


def test_login_errors_do_not_echo_password_and_rate_limit(system):
    client = client_for(system)
    unknown_secret = 'not-a-real-secret-test-marker'
    for _ in range(10):
        response = client.post('/api/session', json={'username': 'missing', 'password': unknown_secret},
            headers={'origin': 'http://testserver'})
        assert response.status_code == 401
        assert unknown_secret not in response.text
    assert client.post('/api/session', json={'username': 'missing', 'password': unknown_secret},
        headers={'origin': 'http://testserver'}).status_code == 429
    invalid = client.post('/api/session', json={'username': 'reviewer', 'password': {'secret': unknown_secret}},
        headers={'origin': 'http://testserver'})
    assert invalid.status_code == 422 and unknown_secret not in invalid.text


def test_http_scope_events_and_revocation(system):
    own = system.service.submit(system.agent, ToolRequest(**proposal()), 'scope-events-001')
    system.service.drain()
    outsider = client_for(system)
    outsider.headers['authorization'] = 'Bearer '+OTHER_TOKEN
    assert outsider.get('/api/operations/'+own['id']).status_code == 404
    assert outsider.get('/api/operations').json()['total'] == 0
    assert outsider.get('/api/events/poll').json()['items'] == []
    human = human_client(system)
    events = human.get('/api/events/poll').json()['items']
    assert len(events) >= 2
    assert human.get('/api/events/poll', params={'after': events[-1]['seq']}).json()['items'] == []
    assert human.get('/api/events', headers={'last-event-id': 'invalid'}).status_code == 422
    with system.store.transaction() as conn:
        conn.execute(update(principals).where(principals.c.id=='reviewer').values(version=2))
    assert human.get('/api/session').status_code == 401


def test_demo_uses_real_proposal_and_no_bypass_or_reset(system):
    client = human_client(system)
    scenarios = client.get('/api/demo/scenarios').json()
    assert scenarios['source'] == 'synthetic_scripted_agent'
    assert len(scenarios['items']) == 5
    response = client.post('/api/demo/scenarios/review', headers={'idempotency-key': 'demo-http-001'})
    assert response.status_code == 202, response.text
    system.service.drain()
    assert client.get('/api/operations/'+response.json()['id']).json()['state'] == 'PENDING_APPROVAL'
    for path in ['/api/reset', '/api/bypass', '/api/unsafe', '/api/execute']:
        assert client.post(path).status_code == 404
    disabled = replace(system.settings, demo_enabled=False)
    closed = TestClient(create_app(disabled,store=system.store,runner=system.service.runner,service=system.service))
    closed.cookies.set(COOKIE,system.cookie)
    assert closed.post('/api/demo/scenarios/read',headers={'origin':'http://testserver',
        'x-csrf-token':system.human['csrf'],'idempotency-key':'disabled-demo-001'}).status_code == 404


def test_runner_private_auth_and_http_preview(system):
    client = TestClient(create_runner_app(system.target, system.settings.runner_secret))
    body = {'request': ToolRequest(tool='db.query_rows').model_dump(), 'scope': 'demo'}
    assert client.post('/internal/preview',json=body).status_code == 401
    assert client.post('/internal/preview',json=body,headers={'authorization':'Bearer '+AGENT_TOKEN}).status_code == 401
    response = client.post('/internal/preview',json=body,
        headers={'authorization':'Bearer '+system.settings.runner_secret})
    assert response.status_code == 200, response.text
    assert response.json()['coverage'] == 'exact_on_snapshot'


def test_telemetry_is_not_authorization(system):
    op = system.service.submit(system.agent,ToolRequest(**proposal()),'telemetry-http-001')
    system.service.drain()
    client=human_client(system)
    body={'visible_ms':1000,'diff_opened':True,'first_visible_at':'2026-09-30T11:00:00Z','event_id':'telemetry-event-001'}
    response=client.post('/api/reviews/'+op['id']+'/telemetry',json=body)
    assert response.status_code==202 and response.json()['trusted_for_security'] is False
    assert client.get('/api/operations/'+op['id']).json()['state']=='PENDING_APPROVAL'
