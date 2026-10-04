"""Independent identity/export boundary probes, all local synthetic fixtures."""
import base64
from dataclasses import replace
import json
import time

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
import jwt
import pytest

from airlock.api import create_app
from conftest import call, count, decision


@pytest.fixture
def identity_scope(settings, tmp_path, monkeypatch):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    key.update(kid='boundary-key', alg='RS256', use='sig')
    (tmp_path / 'boundary-jwks.json').write_text(json.dumps({'keys': [key]}))
    config = {'issuer': 'https://boundary.example/issuer', 'audience': 'boundary-api',
              'jwks_file': 'boundary-jwks.json', 'subjects': {'human': 'reviewer:scope'}}
    identity = tmp_path / 'boundary-issuer.json'
    identity.write_text(json.dumps(config))
    reviewer = tmp_path / 'boundary-reviewers.json'
    reviewer.write_text(json.dumps({'reviewers': [{
        'id': 'reviewer:scope', 'credential_env': 'AIRLOCK_REVIEWER_BOUNDARY',
        'tools': ['sql'], 'resources': ['customers'], 'risks': ['low', 'high', 'blocked'],
    }]}))
    monkeypatch.setenv('AIRLOCK_REVIEWER_BOUNDARY', 'boundary-' + 'r' * 32)
    settings = replace(settings, oidc_file=identity, reviewer_file=reviewer, max_actions=2)

    def token(**changes):
        now = int(time.time())
        claims = {'iss': config['issuer'], 'aud': config['audience'], 'sub': 'human',
                  'iat': now, 'exp': now + 300, 'jti': 'boundary-token', 'client_id': 'boundary-client'}
        claims.update(changes)
        return jwt.encode(claims, private, algorithm='RS256', headers={'kid': 'boundary-key', 'typ': 'at+jwt'})

    return settings, token, reviewer


@pytest.mark.parametrize('claim', ['exp', 'iat', 'nbf'])
def test_nonfinite_numeric_date_is_structured_authentication_failure(identity_scope, claim):
    settings, token, _ = identity_scope
    value = token(**{claim: float('inf')})
    with TestClient(create_app(settings), base_url=settings.origin, raise_server_exceptions=False) as client:
        response = client.get('/v1/me', headers={'Authorization': 'Bearer ' + value})
        assert response.status_code == 401
        assert response.json()['error'] == 'authentication_required'
        assert value not in response.text
        assert count(client.app.state.gate) == 1206


def test_unsigned_deep_jwt_header_is_structured_authentication_failure(identity_scope):
    settings, _, _ = identity_scope
    header = '{"alg":"RS256","typ":"at+jwt","kid":"boundary-key","extra":' + '[' * 1100 + '0' + ']' * 1100 + '}'
    encoded = base64.urlsafe_b64encode(header.encode()).rstrip(b'=').decode()
    value = encoded + '.e30.eA'
    assert len(value) < 8192
    with TestClient(create_app(settings), base_url=settings.origin, raise_server_exceptions=False) as client:
        response = client.get('/v1/me', headers={'Authorization': 'Bearer ' + value})
        assert response.status_code == 401
        assert response.json()['error'] == 'authentication_required'
        assert value not in response.text
        assert count(client.app.state.gate) == 1206


@pytest.mark.parametrize('endpoint', ['/v1/audit', '/v1/audit/export'])
def test_scoped_audit_pagination_crosses_invisible_governance_prefix(identity_scope, endpoint):
    settings, token, _ = identity_scope
    with TestClient(create_app(settings), base_url=settings.origin) as client:
        gate = client.app.state.gate
        operator = {'Authorization': 'Bearer ' + settings.reviewer_token}
        # No action count is consumed by valid operator cache invalidations.
        # Exceed the former max_actions*4 raw scan window with invisible events.
        for _ in range(settings.max_actions * 4 + 1):
            assert client.post('/v1/semantic/cache/invalidate', headers=operator).status_code == 200
        action = gate.submit(call(key='visible-after-hidden-events'))
        auth = {'Authorization': 'Bearer ' + token()}
        first = client.get(endpoint, headers=auth)
        assert first.status_code == 200
        report = first.json()
        assert len(report['items']) == 1
        assert report['next_after'] == settings.max_actions * 4 + 2
        assert 'governance:cache' not in json.dumps(report)
        if endpoint == '/v1/audit':
            assert report['items'][0]['action_id'] == action['id']
        else:
            assert action['id'] not in json.dumps(report)
        again = client.get(endpoint, params={'after': report['next_after']}, headers=auth).json()
        assert again['items'] == [] and again['next_after'] == report['next_after']
        assert gate.get(action['id'])['state'] == 'pending'
        assert count(gate) == 1206 and gate.store.verify_audit()['valid']


def test_scoped_audit_page_limit_and_action_filter_do_not_expand_scope(identity_scope):
    settings, token, _ = identity_scope
    with TestClient(create_app(settings), base_url=settings.origin) as client:
        gate = client.app.state.gate
        small = gate.submit(call(key='scope-visible'))
        hidden = gate.submit(call('DELETE FROM customers', key='scope-invisible'))
        gate.decide(small['id'], decision(small, value='reject'), 'reviewer:scope')
        before = gate.store.audit_events(limit=100)
        first = gate.audit_events('reviewer:scope', limit=1)
        second = gate.audit_events('reviewer:scope', after=first[0]['seq'], limit=1)
        assert len(first) == len(second) == 1
        assert first[0]['seq'] < second[0]['seq']
        assert all(row['action_id'] == small['id'] for row in first + second)
        assert gate.audit_events('reviewer:scope', after=second[0]['seq'], limit=1) == []
        auth = {'Authorization': 'Bearer ' + token()}
        assert client.get('/v1/audit', params={'action_id': hidden['id']}, headers=auth).json()['items'] == []
        assert client.get('/v1/audit', params={'action_id': 'does-not-exist'}, headers=auth).json()['items'] == []
        assert gate.audit_events('reviewer:scope', action_id=small['id']) == first + second
        assert gate.store.audit_events(limit=100) == before
        assert gate.store.verify_audit()['valid'] and count(gate) == 1206


@pytest.mark.parametrize('change', ['resource', 'active'])
def test_scoped_export_reloads_revocation_before_next_page(identity_scope, change):
    settings, token, reviewer_path = identity_scope
    with TestClient(create_app(settings), base_url=settings.origin) as client:
        gate = client.app.state.gate
        gate.submit(call(key='revoke-before-export'))
        auth = {'Authorization': 'Bearer ' + token()}
        assert len(client.get('/v1/audit/export', headers=auth).json()['items']) == 1
        rows = json.loads(reviewer_path.read_text())
        if change == 'resource':
            rows['reviewers'][0]['resources'] = ['another-resource']
        else:
            rows['reviewers'][0]['active'] = False
        reviewer_path.write_text(json.dumps(rows))
        response = client.get('/v1/audit/export', headers=auth)
        if change == 'resource':
            assert response.status_code == 200 and response.json()['items'] == []
        else:
            assert response.status_code == 401
        assert gate.store.verify_audit()['valid'] and count(gate) == 1206
