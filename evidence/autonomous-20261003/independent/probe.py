import json, os, sqlite3, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
import httpx
from fastapi.testclient import TestClient
from airlock.github_adapter import AdapterConfig, IssueAdapter, IssueArguments, ExecuteRequest, ObservedIssue, create_app
from airlock.models import GateError

root = Path(tempfile.mkdtemp(prefix='github-review-', dir='var/github-security-review'))
cfg = AdapterConfig(repository_node_id='R_review01', repository_full_name='example/review', public_repository=True, mode='direct', api_pinned_addresses=['140.82.112.6'])
adapter = IssueAdapter(cfg, root/'direct.db')
args = IssueArguments(title='Independent synthetic safety probe', body='No external mutation.')
req = ExecuteRequest(action_id='1'*32, request_hash='2'*64, expected_version=adapter._plan_digest(args), arguments=args)
observed = []
sends = []
def send(row):
    sends.append(row['action_id'])
    value = ObservedIssue(repository_node_id=cfg.repository_node_id, repository_full_name=cfg.repository_full_name, issue_node_id='I_review01', number=11, url='https://github.com/example/review/issues/11', title=row['title'], body=row['body'])
    observed.append(value)
    time.sleep(.03)
    raise httpx.ReadTimeout('synthetic response loss after one recorded effect')
adapter.api.create = send
with ThreadPoolExecutor(max_workers=24) as pool:
    results = list(pool.map(lambda _: adapter.execute(req), range(24)))
assert len(sends)==1 and all(r['state']=='unknown' for r in results)
restart = IssueAdapter(cfg, root/'direct.db')
restart.api.create = lambda row: (_ for _ in ()).throw(AssertionError('duplicate send'))
assert restart.execute(req)['state']=='unknown'
restart.api.read_issue = lambda node: observed[0].model_copy(update={'body':'unbound effect'})
try:
    restart.reconcile_direct(req.action_id, 'I_review01')
except GateError as e:
    assert e.code=='github_observation_mismatch'
else:
    raise AssertionError('unbound evidence accepted')
assert restart.receipt(req.action_id)['state']=='unknown'
restart.api.read_issue = lambda node: observed[0]
assert restart.reconcile_direct(req.action_id, 'I_review01')['state']=='executed'
assert restart.execute(req)['state']=='executed' and len(sends)==1
for field, value in [('request_hash','3'*64), ('expected_version','4'*64), ('arguments', IssueArguments(title='changed',body='changed'))]:
    try:
        restart.execute(req.model_copy(update={field:value}))
    except GateError as e:
        assert e.code=='github_claim_binding_mismatch'
    else:
        raise AssertionError('binding substitution accepted: '+field)

os.environ['AIRLOCK_UPSTREAM_GITHUB_GATE_TOKEN']='g'*40
os.environ['AIRLOCK_GITHUB_RELAY_TOKEN']='r'*40
relay_cfg = cfg.model_copy(update={'mode':'relay'})
app = create_app(relay_cfg, root/'relay.db')
with TestClient(app) as client:
    for header in ({}, {'Authorization':'Bearer '+'a'*40}, {'Authorization':'Bearer '+'r'*40}):
        assert client.post('/execute',json=req.model_dump(),headers=header).status_code==403
    with sqlite3.connect(root/'relay.db') as conn:
        assert conn.execute('SELECT COUNT(*) FROM github_claims').fetchone()[0]==0
    gate_header={'Authorization':'Bearer '+'g'*40}
    for endpoint in ('claim','complete','reconcile'):
        payload = {'issue_node_id':'I_review01'} if endpoint=='reconcile' else {}
        result=client.post('/operator/'+endpoint+'/'+req.action_id,headers=gate_header,json=payload)
        assert result.status_code in (403,422)
report={'scope':'synthetic isolated journal/HTTP; no GitHub mutation', 'concurrent_calls':24, 'sends':len(sends), 'unknown_until_bound_readback':True, 'unauthorized_execute_rows':0, 'bindings_rejected':['request_hash','expected_version','arguments'], 'unfixed_p0_p1_found':False, 'boundary':'trusted gate and operator credentials; append-only create without target CAS; operator attestation is not independent server readback'}
Path('var/github-security-review/report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
