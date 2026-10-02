import json
import os
import subprocess
import sys
from scripts.support import server


def rpc(method, identifier=None, **params):
    message={'jsonrpc':'2.0','method':method,'params':params}
    if identifier is not None:
        message['id']=identifier
    return message


def exchange(url,token,messages):
    env={'PATH':os.environ.get('PATH',''),'PYTHONPATH':os.getcwd(),'AIRLOCK_URL':url,'AIRLOCK_AGENT_TOKEN':token}
    # Windows TLS needs SystemRoot; keep the environment allowlisted, without reviewer secrets.
    env.update({name: os.environ[name] for name in ('SYSTEMROOT','WINDIR','TEMP','TMP') if name in os.environ})
    result=subprocess.run([sys.executable,'-m','airlock.mcp'],input=''.join(json.dumps(m)+'\n' for m in messages),
                          text=True,encoding='utf-8',capture_output=True,env=env,timeout=15)
    assert result.returncode==0,result.stderr
    return [json.loads(line) for line in result.stdout.splitlines()]


def init():
    return [rpc('initialize',1,protocolVersion='2025-11-25',capabilities={},clientInfo={'name':'independent-stdio-test','version':'1'}),
            rpc('notifications/initialized')]


def test_real_stdio_to_real_http_and_resume_after_human_approval():
    with server() as (url,keys,client):
        rows=exchange(url,keys['AIRLOCK_AGENT_TOKEN'],init()+[
            rpc('tools/list',2),rpc('tools/call',3,name='sql_execute',arguments={'sql':'DELETE FROM customers WHERE id=1','idempotency_key':'live-stdio-001'})])
        assert len(rows)==3 and rows[0]['result']['protocolVersion']=='2025-11-25'
        assert {t['name'] for t in rows[1]['result']['tools']}=={'sql_execute','action_status'}
        receipt=rows[2]['result']['structuredContent']
        assert receipt['state']=='pending' and receipt['execution_occurred'] is False
        reviewer={'Authorization':'Bearer '+keys['AIRLOCK_REVIEWER_TOKEN']}
        detail=client.get('/v1/actions/'+receipt['id'],headers=reviewer).json()
        assert client.get('/v1/metrics',headers=reviewer).json()['customers']==1206
        approved=client.post('/v1/actions/'+receipt['id']+'/decision',headers=reviewer,json={
            'decision':'approve','review_digest':detail['review_digest'],'expected_version':detail['version'],
            'reason':'Independent reviewer verified one row','confirmation':''})
        assert approved.status_code==200 and approved.json()['state']=='executed'
        status=exchange(url,keys['AIRLOCK_AGENT_TOKEN'],init()+[
            rpc('tools/call',4,name='action_status',arguments={'action_id':receipt['id']})])
        assert status[-1]['result']['structuredContent']['state']=='executed'
        assert client.get('/v1/metrics',headers=reviewer).json()['customers']==1205
        assert keys['AIRLOCK_REVIEWER_TOKEN'] not in json.dumps(rows+status)


def test_real_sse_reconnect_cursor_only_delivers_newer_events():
    with server() as (url,keys,client):
        agent={'Authorization':'Bearer '+keys['AIRLOCK_AGENT_TOKEN']}
        reviewer={'Authorization':'Bearer '+keys['AIRLOCK_REVIEWER_TOKEN']}
        def event(after):
            with client.stream('GET','/v1/events',params={'after':after},headers=reviewer) as response:
                assert response.status_code==200
                for line in response.iter_lines():
                    if line.startswith('id: '):
                        return int(line[4:])
            raise AssertionError('No event received')
        client.post('/v1/actions',headers=agent,json={'sql':'SELECT 1','idempotency_key':'sse-first-001'})
        first=event(0)
        client.post('/v1/actions',headers=agent,json={'sql':'SELECT 2','idempotency_key':'sse-second-002'})
        assert event(first)>first
