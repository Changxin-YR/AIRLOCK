"""Interop with the official MCP SDK, not our own JSON-RPC test helper."""
import asyncio
import json
import os
import sys

from scripts.support import ROOT, server


def test_official_mcp_sdk_pending_approval_and_result():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    with server() as (url, keys, client):
        params = StdioServerParameters(
            command=sys.executable,
            args=['-m', 'airlock.mcp'],
            env={'PATH': os.environ.get('PATH', ''), 'PYTHONPATH': str(ROOT),
                 'AIRLOCK_URL': url, 'AIRLOCK_AGENT_TOKEN': keys['AIRLOCK_AGENT_TOKEN']},
        )
        reviewer = {'Authorization': 'Bearer ' + keys['AIRLOCK_REVIEWER_TOKEN']}

        async def check():
            async with asyncio.timeout(20):
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        initialized = await session.initialize()
                        assert initialized.serverInfo.name == 'airlock'
                        tools = await session.list_tools()
                        assert {tool.name for tool in tools.tools} == {'sql_execute', 'action_status'}
                        response = await session.call_tool('sql_execute', {
                            'sql': 'UPDATE customers SET balance=balance+1 WHERE id=1',
                            'idempotency_key': 'official-sdk-001',
                        })
                        assert not response.isError
                        receipt = json.loads(response.content[0].text)
                        assert receipt['state'] == 'pending' and receipt['execution_occurred'] is False
                        detail = (await asyncio.to_thread(client.get, '/v1/actions/' + receipt['id'], headers=reviewer)).json()
                        approved = await asyncio.to_thread(client.post, '/v1/actions/' + receipt['id'] + '/decision',
                            headers=reviewer, json={'decision': 'approve', 'review_digest': detail['review_digest'],
                                'expected_version': detail['version'], 'reason': 'SDK test reviewer checked one row',
                                'confirmation': detail['confirmation_required']})
                        assert approved.status_code == 200 and approved.json()['state'] == 'executed'
                        result = await session.call_tool('action_status', {'action_id': receipt['id']})
                        assert json.loads(result.content[0].text)['state'] == 'executed'
                        readback = await session.call_tool('sql_execute', {
                            'sql': 'SELECT balance FROM customers WHERE id=1',
                            'idempotency_key': 'official-sdk-readback',
                        })
                        assert json.loads(readback.content[0].text)['result']['rows'] == [{'balance': 1001}]
        asyncio.run(check())


def test_official_sdk_discovers_and_calls_independent_upstream(tmp_path,monkeypatch):
    from mcp import ClientSession,StdioServerParameters
    from mcp.client.stdio import stdio_client
    from test_upstream import upstream
    with upstream(tmp_path,monkeypatch) as (config,target,spec):
        with server({'AIRLOCK_UPSTREAM_FILE':str(config),spec['credential_env']:os.environ[spec['credential_env']]}) as (url,keys,client):
            env={k:v for k,v in os.environ.items() if k in {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP'}}
            env.update(PYTHONPATH=str(ROOT),AIRLOCK_URL=url,AIRLOCK_AGENT_TOKEN=keys['AIRLOCK_AGENT_TOKEN'])
            params=StdioServerParameters(command=sys.executable,args=['-m','airlock.mcp'],env=env)
            reviewer={'Authorization':'Bearer '+keys['AIRLOCK_REVIEWER_TOKEN']}
            async def check():
                async with asyncio.timeout(25):
                    async with stdio_client(params) as (read,write):
                        async with ClientSession(read,write) as session:
                            await session.initialize()
                            assert 'upstream:counter' in {t.name for t in (await session.list_tools()).tools}
                            response=await session.call_tool('upstream:counter',{'arguments':{'delta':3},'idempotency_key':'sdk-upstream-real'})
                            receipt=json.loads(response.content[0].text)
                            assert receipt['state']=='pending' and target.get('/state').json()['value']==0
                            detail=client.get('/v1/actions/'+receipt['id'],headers=reviewer).json()
                            decision=client.post('/v1/actions/'+receipt['id']+'/decision',headers=reviewer,json={
                                'decision':'approve','review_digest':detail['review_digest'],'expected_version':detail['version'],
                                'reason':'Independent synthetic upstream review','confirmation':detail['confirmation_required']})
                            assert decision.status_code==200 and target.get('/state').json()=={'value':3,'version':1}
                            final=await session.call_tool('action_status',{'action_id':receipt['id']})
                            assert json.loads(final.content[0].text)['state']=='executed'
            asyncio.run(check())
