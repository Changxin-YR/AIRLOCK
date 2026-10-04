from dataclasses import replace
import json
import os
import socket
import subprocess
import sys
import time
import httpx
import pytest
from airlock.service import Gate
from airlock.mcp_upstream import response_messages
from airlock.models import GateError
from test_upstream import upstream,request
from conftest import decision
from scripts.support import stop_process_tree


@pytest.mark.parametrize('drop',[False,True])
def test_official_stateful_sse_upstream_review_effect_and_reconcile(settings,tmp_path,monkeypatch,drop):
    with upstream(tmp_path,monkeypatch,drop=drop) as (config,target,spec):
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env={k:v for k,v in os.environ.items() if k in {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','AIRLOCK_UPSTREAM_TEST_TOKEN'}}
        with (tmp_path/'mcp.log').open('wb') as log:
            process=subprocess.Popen([sys.executable,'scripts/fixture_mcp_server.py','--port',str(port),'--counter-origin',spec['url']],env=env,stdout=log,stderr=log)
            try:
                with httpx.Client(trust_env=False,timeout=1) as probe:
                    for _ in range(150):
                        try:
                            if probe.get(f'http://127.0.0.1:{port}/mcp').status_code in {400,405,406}:break
                        except httpx.HTTPError:pass
                        time.sleep(.03)
                    else:raise RuntimeError('official MCP SDK fixture did not start')
                spec.update(url=f'http://127.0.0.1:{port}',transport='mcp_streamable',mcp_tools={p:'counter_'+p for p in ('preview','execute','receipt')})
                config.write_text(json.dumps({'tools':[spec]}))
                gate=Gate(replace(settings,upstream_file=config));action=gate.submit(request())
                assert action['state']=='pending' and target.get('/state').json()['value']==0
                result=gate.decide(action['id'],decision(action))
                assert result['state']==('unknown' if drop else 'executed')
                if drop:assert Gate(gate.settings).remote.reconcile(result)['state']=='executed'
                assert target.get('/state').json()=={'value':3,'version':1}
                assert gate.store.verify_audit()['valid']
            finally:stop_process_tree(process)


def test_sse_fragmented_unicode_notifications_and_bounds():
    data=': keepalive\r\n\r\nevent: message\r\ndata: {"jsonrpc":"2.0","method":"notifications/progress"}\r\n\r\ndata: {"jsonrpc":"2.0","id":1,"result":{"text":"中文"}}\r\n\r\n'.encode()
    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            for i in range(0,len(data),3):yield data[i:i+3]
    response=httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Chunks())
    rows=list(response_messages(response,time.monotonic()+5))
    assert len(rows)==2 and rows[-1]['result']['text']=='中文'
    with pytest.raises(ValueError,match='budget'):
        list(response_messages(httpx.Response(200,headers={'content-type':'text/event-stream'},content=b'x'*16385),time.monotonic()+5))
    with pytest.raises(ValueError,match='incomplete'):
        list(response_messages(httpx.Response(200,headers={'content-type':'text/event-stream'},content=b'data: {}'),time.monotonic()+5))


@pytest.mark.parametrize('attack',['session_swap','wrong_id','server_request','unregistered_tool','oversized_session'])
def test_mcp_untrusted_session_and_rpc_messages_cannot_execute(attack):
    from airlock.mcp_upstream import invoke
    calls=[]
    def respond(request):
        if request.method=='DELETE':return httpx.Response(200)
        body=json.loads(request.content);calls.append(body['method'])
        method=body['method'];headers={}
        if method=='initialize':
            result={'protocolVersion':'2025-11-25'};headers['Mcp-Session-Id']='x'*257 if attack=='oversized_session' else 'valid-session'
        elif method=='notifications/initialized':return httpx.Response(202)
        else:
            assert method=='tools/list'
            result={'tools':[{'name':'other' if attack=='unregistered_tool' else 'execute'}]}
            if attack=='session_swap':headers['Mcp-Session-Id']='changed'
        message={'jsonrpc':'2.0','id':body.get('id'),'result':result}
        if method=='tools/list' and attack=='wrong_id':message['id']=999
        if method=='tools/list' and attack=='server_request':message={'jsonrpc':'2.0','id':2,'method':'elicitation/create','params':{}}
        return httpx.Response(200,json=message,headers=headers)
    class Tool:
        transport='mcp_streamable';mcp_tools={'execute':'execute'};mcp_path='/mcp'
        def target(self):return 'https://fixture.example'
        def client(self):return httpx.Client(transport=httpx.MockTransport(respond))
    with pytest.raises(GateError,match='upstream_mcp_unavailable'):invoke(Tool(),'POST','/execute',{}, {})
    assert 'tools/call' not in calls
