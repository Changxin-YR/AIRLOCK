from dataclasses import replace
import json
import pytest
from fastapi.testclient import TestClient
from airlock.api import create_app
from airlock.models import GateError
from airlock.service import Gate
from conftest import call,decision,count


def configured(settings,tmp_path,monkeypatch):
    rows=[{'id':'reviewer:small','credential_env':'AIRLOCK_REVIEWER_SMALL','tools':['sql'],'resources':['customers'],'risks':['low','high','blocked']},
          {'id':'reviewer:large','credential_env':'AIRLOCK_REVIEWER_LARGE','tools':['sql'],'resources':['customers'],'risks':['critical']}]
    path=tmp_path/'reviewers.json'; path.write_text(json.dumps({'reviewers':rows}))
    monkeypatch.setenv('AIRLOCK_REVIEWER_SMALL','s'*32); monkeypatch.setenv('AIRLOCK_REVIEWER_LARGE','l'*32)
    return replace(settings,reviewer_file=path),rows,path


def test_two_reviewers_route_view_decide_and_revocation(settings,tmp_path,monkeypatch):
    settings,rows,path=configured(settings,tmp_path,monkeypatch)
    with TestClient(create_app(settings),base_url=settings.origin) as client:
        gate=client.app.state.gate
        small=gate.submit(call()); large=gate.submit(call('DELETE FROM customers','large-request'))
        auth=lambda token:{'Authorization':'Bearer '+token}
        assert client.get('/v1/actions',headers=auth('s'*32)).json()['items'][0]['id']==small['id']
        assert client.get('/v1/actions/'+large['id'],headers=auth('s'*32)).status_code==403
        assert client.post('/v1/actions/'+large['id']+'/decision',headers=auth('s'*32),json=decision(large).model_dump()).status_code==403
        assert len(client.get('/v1/audit',headers=auth('s'*32)).json()['items'])==1
        rows[0]['active']=False; path.write_text(json.dumps({'reviewers':rows}))
        assert client.get('/v1/me',headers=auth('s'*32)).status_code==401
        with pytest.raises(GateError,match='review_scope_forbidden'):
            gate.decide(small['id'],decision(small),'reviewer:small')
        assert count(gate)==1206
        assert client.post('/v1/actions/'+large['id']+'/decision',headers=auth('l'*32),json=decision(large).model_dump()).json()['state']=='executed'
        assert count(gate)==0 and gate.store.verify_audit()['valid']


def test_missing_route_and_route_tamper_fail_closed(settings,tmp_path,monkeypatch):
    settings,rows,path=configured(settings,tmp_path,monkeypatch)
    gate=Gate(settings); action=gate.submit(call())
    with gate.store.transaction() as conn:
        action['reviewers'].append('reviewer:large'); gate.store.save(conn,action)
    with pytest.raises(GateError): gate.decide(action['id'],decision(action),'reviewer:large')
    rows[0]['active']=False; path.write_text(json.dumps({'reviewers':rows}))
    assert gate.submit(call(key='missing-route'))['reason_code']=='review_route_missing'
    assert count(gate)==1206
