"""Real isolated-network proof for the registered synthetic remote adapter.

Build the project image with docker_smoke first. Only unique containers/networks
created here are removed; state is disposable tmpfs and credentials are scoped.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import uuid
import httpx

ROOT=Path(__file__).resolve().parents[1]
PROBE=r'''
import json,os,socket
from pathlib import Path
import httpx
assert os.getuid()==10001
assert not any(os.getenv(k) for k in ('AIRLOCK_REVIEWER_TOKEN','AIRLOCK_AUDIT_KEY','AIRLOCK_UPSTREAM_TEST_TOKEN'))
assert not any(Path(p).exists() for p in ('/config/upstream.json','/data/gate.db','/var/run/docker.sock'))
assert len([n for n in os.listdir('/sys/class/net') if n!='lo'])==1
try:socket.getaddrinfo('protected-upstream',9000)
except socket.gaierror:pass
else:raise AssertionError('Agent resolved the protected upstream')
try:socket.create_connection((os.environ['TEST_TARGET_IP'],9000),timeout=1)
except OSError:pass
else:raise AssertionError('Agent connected directly to the protected upstream')
with httpx.Client(base_url='http://airlock:8000',headers={'Authorization':'Bearer '+os.environ['AIRLOCK_AGENT_TOKEN']},trust_env=False,timeout=10) as c:
    action=c.post('/v1/actions',json={'tool':'upstream:counter','arguments':{'delta':3},'idempotency_key':'network-isolation-write'}).json()
    assert action['state']=='pending',action
    assert c.post('/v1/actions/'+action['id']+'/decision',json={'decision':'approve','review_digest':'0'*64,'expected_version':1,'reason':'forged approval'}).status_code==403
    print(json.dumps({'action_id':action['id'],'checks':['no_upstream_dns','no_direct_ip_access','no_upstream_or_review_secret','no_server_volume_or_socket','single_internal_agent_network','write_waits_for_reviewer']}))
'''


def main():
    p=argparse.ArgumentParser();p.add_argument('--image');p.add_argument('--docker-report',type=Path,default=ROOT/'evidence/docker-report.json');p.add_argument('--output',type=Path,default=ROOT/'evidence/upstream-isolation.json');args=p.parse_args()
    image=args.image or json.loads(args.docker_report.read_text())['runtime_image_id']
    prefix='airlock-remote-'+uuid.uuid4().hex[:12];names=[];networks=[]
    def run(command,timeout=40):
        result=subprocess.run(['docker']+command,text=True,capture_output=True,timeout=timeout)
        if result.returncode:raise RuntimeError('Docker operation failed: '+command[0]+' '+result.stderr[-1000:])
        return result.stdout.strip()
    common=['--user','10001:10001','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--tmpfs','/tmp:rw,noexec,nosuid,size=32m,mode=1777','--tmpfs','/data:rw,noexec,nosuid,size=32m,uid=10001,gid=10001']
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    keys={k:secrets.token_urlsafe(32) for k in ('AIRLOCK_AGENT_TOKEN','AIRLOCK_REVIEWER_TOKEN','AIRLOCK_AUDIT_KEY','AIRLOCK_UPSTREAM_TEST_TOKEN')}
    with tempfile.TemporaryDirectory(prefix='airlock-remote-') as folder:
        folder=Path(folder)
        def envfile(name,values):
            path=folder/name;path.write_text(''.join(k+'='+v+'\n' for k,v in values.items()),encoding='utf-8');return str(path)
        try:
            for name,internal in [('agent',True),('target',True),('ingress',False)]:
                full=prefix+'-'+name;run(['network','create']+(['--internal'] if internal else [])+[full]);networks.append(full)
            upstream=prefix+'-upstream';names.append(upstream)
            run(['run','-d','--name',upstream,'--network',networks[1],'--network-alias','protected-upstream']+common+
                ['--env-file',envfile('upstream.env',{'AIRLOCK_UPSTREAM_TEST_TOKEN':keys['AIRLOCK_UPSTREAM_TEST_TOKEN']}),image,
                 'python','scripts/fixture_upstream.py','--host','0.0.0.0','--port','9000','--database','/data/counter.sqlite'])
            ip=json.loads(run(['inspect',upstream]))[0]['NetworkSettings']['Networks'][networks[1]]['IPAddress']
            spec={'name':'upstream:counter','resource':'synthetic:counter','url':'http://protected-upstream:9000',
                  'credential_env':'AIRLOCK_UPSTREAM_TEST_TOKEN','allow_private_network':True,'pinned_addresses':[ip],'arguments':{'delta':'integer'}}
            config=folder/'upstream.json';config.write_text(json.dumps({'tools':[spec,spec|{'name':'upstream:restore_counter','compensates':spec['name'],'arguments':{'source_action_id':'string'}}]}))
            gate=prefix+'-gate';names.append(gate)
            run(['create','--name',gate,'--network',networks[0],'--network-alias','airlock','-p',f'127.0.0.1:{port}:8000']+common+
                ['--env-file',envfile('gate.env',keys|{'AIRLOCK_DB':'/data/gate.db','AIRLOCK_UPSTREAM_FILE':'/config/upstream.json','AIRLOCK_ORIGIN':f'http://127.0.0.1:{port}','AIRLOCK_INTERNAL_HOST':'airlock'}),
                 '--mount',f'type=bind,source={config},target=/config/upstream.json,readonly',image])
            run(['network','connect',networks[1],gate]);run(['network','connect',networks[2],gate]);run(['start',gate])
            with httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False,timeout=10) as client:
                for _ in range(100):
                    try:
                        if client.get('/healthz').status_code==200:break
                    except httpx.HTTPError:pass
                    time.sleep(.1)
                else:raise RuntimeError('isolated gate startup failed')
                probe=json.loads(run(['run','--rm','--network',networks[0]]+common+['--env-file',envfile('agent.env',{'AIRLOCK_AGENT_TOKEN':keys['AIRLOCK_AGENT_TOKEN'],'TEST_TARGET_IP':ip}),image,'python','-c',PROBE]))
                review={'Authorization':'Bearer '+keys['AIRLOCK_REVIEWER_TOKEN']};agent={'Authorization':'Bearer '+keys['AIRLOCK_AGENT_TOKEN']}
                def decide(identifier,value):
                    a=client.get('/v1/actions/'+identifier,headers=review).json()
                    response=client.post('/v1/actions/'+identifier+'/decision',headers=review,json={'decision':value,'review_digest':a['review_digest'],'expected_version':a['version'],'confirmation':a['confirmation_required'],'reason':'Automated isolated network contract review'})
                    response.raise_for_status();return response.json()
                rejected=decide(probe['action_id'],'reject');assert rejected['state']=='rejected'
                action=client.post('/v1/actions',headers=agent,json={'tool':'upstream:counter','arguments':{'delta':3},'idempotency_key':'explicit-second-task'}).json()
                detail=client.get('/v1/actions/'+action['id'],headers=review).json();assert detail['impact']['preview']['before']=={'value':0}
                result=decide(action['id'],'approve');assert result['state']=='executed' and result['result']['value']==3
                restore=client.post('/v1/actions',headers=agent,json={'tool':'upstream:restore_counter','arguments':{'source_action_id':action['id']},'idempotency_key':'independent-compensation'}).json()
                assert restore['state']=='pending'
                restored=decide(restore['id'],'approve');assert restored['state']=='executed' and restored['result']['value']==0 and restored['result']['version']==2
                assert client.get('/v1/audit/verify',headers=review).json()['valid']
                report={'status':'PASS','mode':'real_docker_protected_upstream','image':image,'probe':probe,
                    'checks':['rejection_preserves_remote_value','separate_approval_executes_once','separate_compensation_restores_value','audit_chain_valid'],
                    'network_boundary':'Agent only on internal ingress; upstream only on distinct internal target network; gate on both; no upstream published port',
                    'limitations':['Synthetic remote CAS counter, scripted reviewer; not a human study','Dedicated pinned private HTTP in isolated fixture; production untrusted networks require TLS','Host administrator and container escape outside tested boundary']}
                args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
        finally:
            for name in reversed(names):subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=30)
            for name in reversed(networks):subprocess.run(['docker','network','rm',name],capture_output=True,timeout=30)


if __name__=='__main__':main()
