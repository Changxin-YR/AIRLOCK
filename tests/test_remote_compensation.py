from dataclasses import replace
import json
import pytest
from airlock.models import Invocation,GateError
from airlock.service import Gate
from test_upstream import upstream,request
from conftest import decision


def registered(config,spec):
    config.write_text(json.dumps({'tools':[spec,spec|{'name':'upstream:restore_counter',
        'compensates':spec['name'],'arguments':{'source_action_id':'string'}}]}))


def restore(source,key='restore-upstream'):
    return Invocation(tool='upstream:restore_counter',arguments={'source_action_id':source['id']},idempotency_key=key)


def test_remote_compensation_is_independent_bound_and_once(settings,tmp_path,monkeypatch):
    with upstream(tmp_path,monkeypatch) as (config,target,spec):
        registered(config,spec);gate=Gate(replace(settings,upstream_file=config))
        source=gate.submit(request())
        assert source['impact']['recovery_evidence']['registered_tools']==['upstream:restore_counter']
        with pytest.raises(GateError,match='not_executed'):gate.submit(restore(source))
        gate.decide(source['id'],decision(source))
        action=gate.submit(restore(source))
        assert action['state']=='pending' and target.get('/state').json()['value']==3
        assert action['impact']['preview']['after']=={'value':0}
        assert action['impact']['recovery_evidence']['source_action_id']==source['id']
        with pytest.raises(GateError):gate.decide(action['id'],decision(source))
        gate.decide(action['id'],decision(action))
        assert target.get('/state').json()=={'value':0,'version':2}
        restart=Gate(gate.settings)
        assert restart.submit(restore(source))['state']=='executed'
        assert restart.submit(restore(source,'restore-second'))['state']=='blocked'
        assert target.get('/state').json()['version']==2
        assert gate.store.verify_audit()['valid']


def test_compensation_drift_and_ownership_do_not_overwrite(settings,tmp_path,monkeypatch):
    with upstream(tmp_path,monkeypatch) as (config,target,spec):
        spec['principals']=['agent:demo','agent:other'];registered(config,spec)
        gate=Gate(replace(settings,upstream_file=config));source=gate.submit(request())
        gate.decide(source['id'],decision(source));comp=gate.submit(restore(source))
        with pytest.raises(GateError,match='unavailable'):gate.submit(restore(source),'agent:other')
        intervening=gate.submit(request('another-counter-write'));gate.decide(intervening['id'],decision(intervening))
        assert gate.decide(comp['id'],decision(comp))['state']=='stale'
        assert target.get('/state').json()=={'value':6,'version':2}
