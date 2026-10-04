from dataclasses import replace
import json
import sqlite3
import pytest
from airlock.service import Gate
from conftest import call,decision,count


def key_settings(settings,tmp_path,monkeypatch):
    path=tmp_path/'keys.json';path.write_text(json.dumps({'keys':{'v2':'AIRLOCK_AUDIT_KEY_V2'}}))
    monkeypatch.setenv('AIRLOCK_AUDIT_KEY_V2','new-key-'+'n'*40)
    return replace(settings,audit_key_file=path)


def test_rotation_preserves_old_events_and_existing_worker(settings,tmp_path,monkeypatch):
    settings=key_settings(settings,tmp_path,monkeypatch)
    first,second=Gate(settings),Gate(settings)
    action=first.submit(call())
    before=first.store.audit_events()
    assert first.store.rotate_key('v2',first.clock())['changed']
    assert second.decide(action['id'],decision(action))['state']=='executed'
    events=second.store.audit_events()
    assert events[0]==before[0] and events[-1]['key_id']=='v2'
    assert Gate(settings).store.verify_audit()['valid'] and count(second)==1205
    monkeypatch.setenv('AIRLOCK_AUDIT_KEY_V2','another-key-'+'z'*40)
    with pytest.raises(ValueError,match='audit key changed'):Gate(settings)


def test_rotation_audit_failure_is_atomic(settings,tmp_path,monkeypatch):
    gate=Gate(key_settings(settings,tmp_path,monkeypatch))
    def fail(*args):raise sqlite3.OperationalError('injected')
    monkeypatch.setattr(gate.store,'audit',fail)
    with pytest.raises(sqlite3.OperationalError):gate.store.rotate_key('v2',gate.clock())
    with gate.store.connection() as conn:assert conn.execute("SELECT value FROM meta WHERE key='audit_active_key'").fetchone()[0]=='legacy'


@pytest.mark.parametrize('tamper',['delete','insert','reorder','replace','truncate','remove_all'])
def test_independent_checkpoint_detects_audit_tampering(settings,tmp_path,tamper):
    gate=Gate(settings)
    for i in range(3):gate.submit(call('SELECT 1',key=f'audit-tamper-{i}'))
    checkpoint=gate.store.checkpoint()
    # This path represents separately retained operator evidence, outside the server DB.
    outside=tmp_path/'external-retention'/'checkpoint.json';outside.parent.mkdir();outside.write_text(json.dumps(checkpoint))
    assert gate.store.verify_audit(json.loads(outside.read_text()))['valid']
    with gate.store.transaction() as conn:
        if tamper=='delete':conn.execute('DELETE FROM audit WHERE seq=2')
        elif tamper=='insert':conn.execute("INSERT INTO audit(seq,action_id,previous_hash,event,signature) VALUES(4,'fake',?, '{}',?)",('0'*64,'0'*64))
        elif tamper=='reorder':
            conn.execute('UPDATE audit SET seq=99 WHERE seq=1');conn.execute('UPDATE audit SET seq=1 WHERE seq=2');conn.execute('UPDATE audit SET seq=2 WHERE seq=99')
        elif tamper=='replace':conn.execute("UPDATE audit SET event='{}' WHERE seq=2")
        elif tamper=='truncate':conn.execute('DELETE FROM audit WHERE seq=3')
        else:conn.execute('DELETE FROM audit')
    verdict=gate.store.verify_audit(json.loads(outside.read_text()))
    assert not verdict['valid']


def test_checkpoint_authentication_and_wrong_database(settings,tmp_path):
    gate=Gate(settings);gate.submit(call('SELECT 1'))
    anchor=gate.store.checkpoint()
    other=Gate(replace(settings,database=tmp_path/'other.db'))
    assert not other.store.verify_audit(anchor)['valid']
    anchor['head']='0'*64
    assert not gate.store.verify_audit(anchor)['valid']


def test_checkpoint_and_rotation_are_operator_only(client,settings):
    headers={'Authorization':'Bearer '+settings.agent_token}
    assert client.get('/v1/audit/checkpoint',headers=headers).status_code==403
    assert client.post('/v1/audit/keys/legacy/rotate',headers=headers).status_code==403
