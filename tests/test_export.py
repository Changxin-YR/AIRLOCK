import json
from fastapi.testclient import TestClient
from airlock.api import create_app
from airlock.export import redacted_export


def test_audit_export_omits_free_text_and_secrets_and_requires_reviewer(settings):
    sentinel='private.person@example.test'
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        agent={'Authorization':'Bearer '+settings.agent_token};reviewer={'Authorization':'Bearer '+settings.reviewer_token}
        client.post('/v1/actions',headers=agent,json={'sql':f"SELECT '{sentinel}' AS personal",'idempotency_key':'export-private-data'})
        raw=client.get('/v1/audit',headers=reviewer).json()
        assert sentinel in json.dumps(raw)
        assert client.get('/v1/audit/export',headers=agent).status_code==403
        first=client.get('/v1/audit/export',headers=reviewer).json()
        second=client.get('/v1/audit/export',headers=reviewer).json()
        assert sentinel not in json.dumps(first) and first['items']
        assert first['items'][0]['action_pseudonym']!=second['items'][0]['action_pseudonym']
        assert first['items'][0]['source_event_sha256']==second['items'][0]['source_event_sha256']
        assert client.get('/v1/audit',headers=reviewer).json()==raw


def test_export_does_not_copy_unknown_kind_or_state():
    report=redacted_export([{'seq':1,'action_id':'secret','event':{'kind':'private@example.test','state':'private','detail':'secret'}}])
    assert report['items'][0]['kind']==report['items'][0]['state']=='other'
    assert 'private' not in json.dumps(report['items'])
