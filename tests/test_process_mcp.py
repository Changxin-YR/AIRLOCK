import asyncio
from datetime import timedelta
import importlib.metadata
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest
import httpx
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from airlock.client import AgentClient
from airlock.common import canonical
from airlock.contracts import ToolRequest
from airlock.config import Settings
from airlock.policy import Policy
from airlock.runner import LocalRunner
from airlock.service import Service
from airlock.storage import Store
from airlock.target import TargetStore
from process_support import LiveSystem,ROOT
from conftest import SECRET


def test_restart_real_gateway_keeps_pending_and_executes_only_after_human(tmp_path):
    with LiveSystem(tmp_path/'live') as live:
        live.login()
        with AgentClient(live.url,live.agent_config['AIRLOCK_AGENT_TOKEN']) as agent:
            op=agent.submit({'tool':'db.update_rows','filters':[{'field':'id','op':'in','value':[1,2]}],
                             'values':{'status':'archived'}},'process-restart-001')
        pending=live.wait(op['id'],{'PENDING_APPROVAL'})
        live.stop_role('gateway');live.start_role('gateway')
        same=live.http.get('/api/operations/'+op['id']).json()
        assert same['state']=='PENDING_APPROVAL' and same['plan']['plan_digest']==pending['plan']['plan_digest']
        with sqlite3.connect(live.root/'runner/target.db') as conn:
            assert conn.execute('SELECT status FROM customers WHERE id=1').fetchone()[0]=='active'
        result=live.http.post('/api/reviews/'+op['id']+'/decision',json={'decision':'approve',
            'plan_digest':same['plan']['plan_digest'],'view_digest':same['plan']['view_digest'],
            'expected_version':same['version'],'decision_key':'process-decision-001','reason':''})
        assert result.status_code==200,result.text
        assert live.wait(op['id'],{'SUCCEEDED'})['result']['total_changed']==2


def test_hard_process_exit_after_target_commit_recovers_receipt(system,tmp_path):
    """The subprocess calls os._exit(73): no exception handler or graceful cleanup."""
    s=system
    request=ToolRequest(tool='db.update_rows',filters=[{'field':'id','op':'eq','value':10}],values={'tag':'once'})
    op=s.service.submit(s.agent,request,'hard-crash-process-001')
    assert s.service.step()  # Preview only -> READY.
    config={'meta':str(s.store.path),'target':str(s.target.path),'clock':s.clock.value,'secret':SECRET}
    config_path=tmp_path/'private-config.json';config_path.write_text(json.dumps(config));config_path.chmod(0o600)
    code='''
import json,os,sys
from pathlib import Path
from airlock.storage import Store
from airlock.target import TargetStore
from airlock.runner import LocalRunner
from airlock.service import Service
from airlock.config import Settings
from airlock.policy import Policy
c=json.loads(Path(sys.argv[1]).read_text());clock=lambda:c['clock']
store=Store(Path(c['meta']),clock=clock);target=TargetStore(Path(c['target']),c['secret'],clock=clock)
class CrashAfterCommit(LocalRunner):
 def execute_once(self,envelope):
  result=super().execute_once(envelope)
  os._exit(73)
settings=Settings(meta_path=store.path,runner_url='http://runner',runner_secret='r'*48,execution_secret=c['secret'],worker_enabled=False,lease_seconds=2)
Service(store,CrashAfterCommit(target),settings,policy=Policy(approval_ttl_seconds=30)).step()
'''
    crashed=subprocess.run([sys.executable,'-c',code,str(config_path)],cwd=ROOT,capture_output=True,timeout=15)
    assert crashed.returncode==73,crashed.stderr.decode()
    with sqlite3.connect(s.target.path) as conn:
        assert conn.execute('SELECT version FROM customers WHERE id=10').fetchone()[0]==1
        assert conn.execute('SELECT COUNT(*) FROM execution_receipts').fetchone()[0]==1
    assert s.service.get(op['id'],s.human)['state']=='EXECUTING'
    s.clock.advance(3)
    recovered=Service(s.store,LocalRunner(s.target),s.settings,policy=Policy(approval_ttl_seconds=30))
    recovered.drain()
    assert recovered.get(op['id'],s.human)['state']=='SUCCEEDED'
    assert any(e['type']=='RECEIPT_RECOVERED' for e in recovered.audit(op['id'],s.human)['items'])
    with sqlite3.connect(s.target.path) as conn:
        assert conn.execute('SELECT version FROM customers WHERE id=10').fetchone()[0]==1


@pytest.mark.mcp
@pytest.mark.asyncio
async def test_actual_mcp_stdio_tools_and_pending_approval(tmp_path):
    with LiveSystem(tmp_path/'mcp-live') as live:
        live.login()
        params=StdioServerParameters(command=sys.executable,args=['-m','airlock.mcp_server'],cwd=str(ROOT),
            env={'AIRLOCK_BASE_URL':live.url,'AIRLOCK_AGENT_TOKEN':live.agent_config['AIRLOCK_AGENT_TOKEN']})
        log=(tmp_path/'mcp-stderr.txt').open('w')
        def content(result):
            assert not result.isError,str(result)
            return result.structuredContent or json.loads(result.content[0].text)
        async with stdio_client(params,errlog=log) as (read,write):
            async with ClientSession(read,write,read_timeout_seconds=timedelta(seconds=15)) as session:
                negotiated=await session.initialize()
                tools=await session.list_tools()
                names={tool.name for tool in tools.tools}
                assert names=={'db.query_rows','db.update_rows','db.delete_rows','airlock.operation_status'}
                result=content(await session.call_tool('db.query_rows',{'idempotency_key':'mcp-query-real-001','limit':2}))
                op_id=result['operation']['id']
                for _ in range(100):
                    query=content(await session.call_tool('airlock.operation_status',{'operation_id':op_id}))
                    if query['state']=='SUCCEEDED':break
                    await asyncio.sleep(.1)
                assert query['state']=='SUCCEEDED'
                assert len(query['result']['query_result']['rows'])==2
                changed=content(await session.call_tool('db.update_rows',{'idempotency_key':'mcp-update-real-001',
                    'filters':[{'field':'id','op':'in','value':[1,2]}],'values':{'status':'archived'}}))
                ident=changed['operation']['id'];pending=await asyncio.to_thread(live.wait,ident,{'PENDING_APPROVAL'})
                untrusted=httpx.post(live.url+'/api/reviews/'+ident+'/decision',json={},
                    headers={'Authorization':'Bearer '+live.agent_config['AIRLOCK_AGENT_TOKEN']},trust_env=False)
                assert untrusted.status_code==403
                response=live.http.post('/api/reviews/'+ident+'/decision',json={'decision':'approve',
                    'plan_digest':pending['plan']['plan_digest'],'view_digest':pending['plan']['view_digest'],
                    'expected_version':pending['version'],'decision_key':'mcp-human-decision-001','reason':''})
                assert response.status_code==200,response.text
                await asyncio.to_thread(live.wait,ident,{'SUCCEEDED'})
                final=content(await session.call_tool('airlock.operation_status',{'operation_id':ident}))
                assert final['state']=='SUCCEEDED' and final['result']['total_changed']==2
                print(json.dumps({'mcp_sdk':importlib.metadata.version('mcp'),'transport':'real stdio subprocess',
                    'protocol':negotiated.protocolVersion,'tools':sorted(names),'read_state':query['state'],
                    'write_state':final['state'],'agent_approval_status':untrusted.status_code},ensure_ascii=False))
        log.close()
