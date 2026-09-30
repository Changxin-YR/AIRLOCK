"""Run within a checkout with a started Compose deployment. No secrets printed."""
import json
import subprocess
import time
from pathlib import Path
import httpx


def run(code):
    result=subprocess.run(['docker','compose','--profile','agent','run','--rm','-T','agent','-c',code],
        capture_output=True,text=True,timeout=45)
    if result.returncode:raise AssertionError('Agent container check failed:\n'+result.stdout+'\n'+result.stderr)
    return result.stdout

checks=run('''
import os,pathlib,socket,httpx,json
assert not pathlib.Path('/data').exists()
assert not pathlib.Path('/var/run/docker.sock').exists()
assert not pathlib.Path('/app/runtime').exists()
assert 'AIRLOCK_RUNNER_SECRET' not in os.environ
assert 'AIRLOCK_EXECUTION_SECRET' not in os.environ
assert 'DEEPSEEK_API_KEY' not in os.environ
try:
 socket.create_connection(('runner',8090),timeout=2)
except OSError:pass
else:raise AssertionError('Agent reached private executor network')
url=os.environ['AIRLOCK_BASE_URL'];token=os.environ['AIRLOCK_AGENT_TOKEN']
with httpx.Client(base_url=url,headers={'Authorization':'Bearer '+token},trust_env=False,timeout=10) as c:
 assert c.post('/api/reviews/not-an-operation/decision',json={}).status_code==403
 result=c.post('/api/operations',json={'tool':'db.query_rows','limit':2},headers={'Idempotency-Key':'compose-boundary-001'})
 assert result.status_code==202,result.text
 ident=result.json()['id']
 for _ in range(100):
  r=c.get('/api/operations/'+ident).json()
  if r['state']=='SUCCEEDED':break
  __import__('time').sleep(.1)
 assert r['state']=='SUCCEEDED'
 assert len(r['result']['query_result']['rows'])==2
print(json.dumps({'agent_target_volume':'absent','agent_execution_secret':'absent','executor_direct_network':'denied','agent_approval_http':403,'real_gateway_read':'SUCCEEDED'}))
''')
Path('Evidence').mkdir(exist_ok=True)
Path('Evidence/compose-boundary.json').write_text(checks)
print(checks)
