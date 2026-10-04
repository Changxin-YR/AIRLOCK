"""Replay the former SSE module against the fixed one, with disposable state.

The old module comes directly from Git, using current pinned dependencies.
Only fixture heartbeat sleep is accelerated; identity and event code is intact.
"""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from fastapi.testclient import TestClient
from airlock.api import create_app
from airlock.models import Settings,Invocation

old_sha='cc9d687c71effc77e317b12560bd23659c4bd0c0'
source=subprocess.run(['git','show',old_sha+':airlock/api.py'],check=True,capture_output=True,text=True).stdout
namespace={'__package__':'airlock','__name__':'airlock.old_sse_replay','__file__':str(Path('airlock/api.py').resolve())}
exec(compile(source,'git:'+old_sha+':airlock/api.py','exec'),namespace)
async def fast_sleep(seconds):await asyncio.sleep(0)
namespace['asyncio']=types.SimpleNamespace(to_thread=asyncio.to_thread,sleep=fast_sleep)
rows=[]
for label,factory in [('old_module',namespace['create_app']),('fixed_module',create_app)]:
    with tempfile.TemporaryDirectory(prefix='airlock-sse-replay-') as directory:
        settings=Settings(Path(directory)/'gate.sqlite','a'*32,'r'*32,'k'*32)
        app=factory(settings);gate=app.state.gate
        action=gate.submit(Invocation(sql='DELETE FROM customers WHERE id=1',idempotency_key='sse-role-change-replay'))
        identities=[]
        def identify(token):
            identity='reviewer:owner' if not identities else 'agent:demo';identities.append(identity);return identity
        gate.access.identify=identify
        with TestClient(app,base_url=settings.origin) as client:
            response=client.get('/v1/events',headers={'Authorization':'Bearer '+settings.reviewer_token})
        with gate.store.connection() as conn:count=conn.execute('SELECT count(*) FROM customers').fetchone()[0]
        rows.append({'implementation':label,'old_source_sha':old_sha if label=='old_module' else None,
            'identity_checks':identities,'action_id_notified_after_identity_change':action['id'] in response.text,
            'response_bytes':len(response.content),'rows_unchanged':count==1206,'decision_occurred':False})
assert rows[0]['action_id_notified_after_identity_change'] is True
assert rows[1]['action_id_notified_after_identity_change'] is False and rows[1]['identity_checks']==['reviewer:owner','agent:demo']
assert all(r['rows_unchanged'] for r in rows)
print(json.dumps({'status':'REGRESSION_REPRODUCED_AND_FIXED','rows':rows,'scope':'real ASGI event stream with a simulated trusted identity-map reload; no business effect'},indent=2))
