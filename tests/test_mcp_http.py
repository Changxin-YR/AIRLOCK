import asyncio
from dataclasses import replace
import json
import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from scripts.support import server
from airlock.service import Gate
from conftest import decision
from test_upstream import upstream,request


def test_official_sdk_streamable_http_approval_denial_and_input_errors():
    with server() as (url,keys,client):
        reviewer={'Authorization':'Bearer '+keys['AIRLOCK_REVIEWER_TOKEN']}
        async def check():
            async with httpx.AsyncClient(headers={'Authorization':'Bearer '+keys['AIRLOCK_AGENT_TOKEN']},trust_env=False) as http:
                async with streamable_http_client(url+'/mcp',http_client=http) as (read,write,_):
                    async with ClientSession(read,write) as session:
                        await session.initialize()
                        assert {'sql_execute','action_status'}=={t.name for t in (await session.list_tools()).tools}
                        pending=await session.call_tool('sql_execute',{'sql':'UPDATE customers SET balance=1005 WHERE id=1','idempotency_key':'http-sdk-write'})
                        action=pending.structuredContent
                        assert action['state']=='pending' and action['execution_occurred'] is False
                        full=client.get('/v1/actions/'+action['id'],headers=reviewer).json()
                        rejected=client.post('/v1/actions/'+action['id']+'/decision',headers=reviewer,json=decision(full,'reject').model_dump())
                        assert rejected.json()['state']=='rejected'
                        status=await session.call_tool('action_status',{'action_id':action['id']})
                        assert status.isError and status.structuredContent['state']=='rejected'
                        unsafe=await session.call_tool('sql_execute',{'sql':'DROP TABLE customers','idempotency_key':'http-sdk-block'})
                        assert unsafe.isError and unsafe.structuredContent['state']=='blocked'
                        from mcp.shared.exceptions import McpError
                        with pytest.raises(McpError):await session.call_tool('sql_execute',{'sql':'SELECT 1','idempotency_key':'http-sdk-forged','approved':True})
                        result=await session.call_tool('sql_execute',{'sql':'SELECT balance FROM customers WHERE id=1','idempotency_key':'http-sdk-read'})
                        assert result.structuredContent['result']['rows']==[{'balance':1000}]
        asyncio.run(check())


def test_mcp_http_origin_auth_content_type_and_protocol(client,settings):
    headers={'Authorization':'Bearer '+settings.agent_token,'Accept':'application/json, text/event-stream'}
    body={'jsonrpc':'2.0','id':1,'method':'ping'}
    assert client.post('/mcp',json=body).status_code==401
    assert client.post('/mcp',json=body,headers=headers|{'Origin':'https://untrusted.invalid'}).status_code==403
    assert client.get('/mcp',headers=headers|{'Origin':'https://untrusted.invalid'}).status_code==403
    assert client.post('/mcp',json=body,headers=headers|{'MCP-Protocol-Version':'invalid'}).status_code==400
    assert client.post('/mcp',json=body,headers=headers|{'Accept':'application/json'}).status_code==406
    assert client.get('/mcp',headers=headers).status_code==405
    assert client.delete('/mcp',headers=headers).status_code==405


@pytest.mark.parametrize('drop',[False,True])
def test_registered_independent_mcp_upstream_cas_and_receipt(settings,tmp_path,monkeypatch,drop):
    with upstream(tmp_path,monkeypatch,drop=drop) as (config,target,spec):
        spec.update(transport='mcp_json',mcp_tools={p:'counter_'+p for p in ('preview','execute','receipt')})
        config.write_text(json.dumps({'tools':[spec]}))
        gate=Gate(replace(settings,upstream_file=config));action=gate.submit(request())
        assert action['state']=='pending' and target.get('/state').json()['value']==0
        result=gate.decide(action['id'],decision(action))
        assert result['state']==('unknown' if drop else 'executed')
        if drop:assert Gate(gate.settings).remote.reconcile(result)['state']=='executed'
        assert target.get('/state').json()=={'value':3,'version':1}
        assert gate.store.verify_audit()['valid']
