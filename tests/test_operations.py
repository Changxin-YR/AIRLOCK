import json
from airlock.operations import health,prometheus
from conftest import call,count


def test_operational_alerts_are_read_only_and_operator_scoped(client,settings):
    gate=client.app.state.gate;action=gate.submit(call())
    assert client.get('/v1/operations/health',headers={'Authorization':'Bearer '+settings.agent_token}).status_code==403
    gate.clock=lambda:action['expires_at']+1
    original=gate.store.audit_events();report=health(gate)
    assert report['recommended_exit_code']==2 and any(a['code']=='pending_expiry_backlog' for a in report['alerts'])
    assert 'DELETE' not in json.dumps(report) and settings.reviewer_token not in prometheus(report)
    with gate.store.connection() as conn:
        assert conn.execute('SELECT state FROM actions WHERE id=?',(action['id'],)).fetchone()[0]=='pending'
    assert count(gate)==1206
    assert gate.store.audit_events()==original
    with gate.store.transaction() as conn:conn.execute("UPDATE audit SET signature=?",('0'*64,))
    assert any(a['code']=='audit_integrity_failed' for a in health(gate)['alerts'])
