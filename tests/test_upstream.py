from contextlib import contextmanager
from dataclasses import replace
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import httpx
import pytest
from airlock.models import Invocation,GateError
from airlock.service import Gate,agent_view
from airlock.upstream import Tool
from airlock.mcp import Bridge
from fastapi.testclient import TestClient
from airlock.api import create_app
from conftest import decision
from scripts.support import stop_process_tree


@contextmanager
def upstream(tmp_path,monkeypatch,drop=False):
    token=secrets.token_urlsafe(32); monkeypatch.setenv('AIRLOCK_UPSTREAM_TEST_TOKEN',token)
    with socket.socket() as sock: sock.bind(('127.0.0.1',0)); port=sock.getsockname()[1]
    env={k:v for k,v in os.environ.items() if k in {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP'}}
    env.update(AIRLOCK_UPSTREAM_TEST_TOKEN=token,AIRLOCK_TEST_DROP_RESPONSE='1' if drop else '0')
    process=subprocess.Popen([sys.executable,'scripts/fixture_upstream.py','--port',str(port),'--database',str(tmp_path/'counter.sqlite')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    spec={'name':'upstream:counter','resource':'synthetic:counter','url':f'http://127.0.0.1:{port}',
          'credential_env':'AIRLOCK_UPSTREAM_TEST_TOKEN','allow_loopback':True,'arguments':{'delta':'integer'}}
    config=tmp_path/'upstream.json'; config.write_text(json.dumps({'tools':[spec]}))
    try:
        with httpx.Client(base_url=spec['url'],headers={'Authorization':'Bearer '+token},trust_env=False,timeout=1) as client:
            for _ in range(100):
                try:
                    if client.get('/state').status_code==200: break
                except httpx.HTTPError: pass
                time.sleep(.03)
            else: raise RuntimeError('fixture startup')
            yield config,client,spec
    finally:
        stop_process_tree(process)


def request(key='upstream-test-key'):
    return Invocation(tool='upstream:counter',arguments={'delta':3},idempotency_key=key)


def test_real_upstream_http_mcp_discovery_pending_approve_receipt(settings,tmp_path,monkeypatch):
    with upstream(tmp_path,monkeypatch) as (config,target,spec):
        settings=replace(settings,upstream_file=config)
        with TestClient(create_app(settings),base_url=settings.origin) as client:
            bridge=Bridge(client,settings.agent_token); bridge.ready=True
            discovered=bridge.handle({'jsonrpc':'2.0','id':1,'method':'tools/list'})
            assert 'upstream:counter' in {t['name'] for t in discovered['result']['tools']}
            reply=bridge.handle({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'upstream:counter','arguments':{'arguments':{'delta':3},'idempotency_key':'mcp-upstream-call'}}})
            receipt=reply['result']['structuredContent']; assert receipt['state']=='pending'
            assert target.get('/state').json()['value']==0
            gate=client.app.state.gate; action=gate.get(receipt['id']); result=gate.decide(action['id'],decision(action))
            assert result['state']=='executed' and target.get('/state').json()=={'value':3,'version':1}
            assert gate.remote.reconcile(result)['state']=='executed'
            assert gate.store.verify_audit()['valid']


def test_lost_remote_response_reconciles_without_duplicate_effect(settings,tmp_path,monkeypatch):
    with upstream(tmp_path,monkeypatch,drop=True) as (config,target,spec):
        gate=Gate(replace(settings,upstream_file=config)); action=gate.submit(request())
        result=gate.decide(action['id'],decision(action))
        assert result['state']=='unknown' and agent_view(result)['execution_occurred'] is None
        assert target.get('/state').json()['value']==3
        restart=Gate(gate.settings)
        assert restart.submit(request())['state']=='unknown'
        assert restart.remote.reconcile(restart.get(action['id']))['state']=='executed'
        assert target.get('/state').json()['version']==1


def test_remote_cas_drift_and_credential_scope(settings,tmp_path,monkeypatch):
    with upstream(tmp_path,monkeypatch) as (config,target,spec):
        gate=Gate(replace(settings,upstream_file=config))
        with pytest.raises(GateError): gate.submit(request(),'agent:outsider')
        a=gate.submit(request()); b=gate.submit(request('upstream-another'))
        gate.decide(a['id'],decision(a))
        assert gate.decide(b['id'],decision(b))['state']=='stale'
        assert target.get('/state').json()['value']==3


@pytest.mark.parametrize('url',['http://169.254.169.254','https://127.0.0.1','http://10.0.0.1','https://example.com','https://user:pass@8.8.8.8','https://8.8.8.8/path'])
def test_ssrf_origins_rejected(url):
    with pytest.raises(ValueError): Tool(name='upstream:test',resource='test',url=url,arguments={}).target()
