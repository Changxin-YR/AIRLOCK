"""Real Envoy CEL subset and official OTel Collector, isolated Docker fixtures.

Only uniquely named containers created here are removed. No server secrets,
target volumes, Docker socket or user data are mounted inside these fixtures.
"""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
import yaml
from airlock.models import Settings,Invocation
from airlock.policy import Policy
from airlock.service import Gate
from airlock.telemetry import export

ENVOY='envoyproxy/envoy:v1.39.1'
OTEL='otel/opentelemetry-collector:0.162.0'


def docker(args,check=True):
    result=subprocess.run(['docker']+args,capture_output=True,text=True,timeout=240)
    if check and result.returncode:raise RuntimeError(f'Docker exit {result.returncode}: {result.stderr[-3000:]}')
    return result.stdout+result.stderr


@contextmanager
def container(image,config,container_port,extra,output,label):
    name='airlock-integration-'+uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix='airlock-integration-') as folder:
        path=Path(folder)/'config.yaml';path.write_text(yaml.safe_dump(config),encoding='utf-8');path.chmod(0o644)
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        try:
            docker(['run','-d','--name',name,'--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
                '-p',f'127.0.0.1:{port}:{container_port}','-v',str(path.resolve())+':/fixture.yaml:ro',image]+extra)
            yield name,port
        finally:
            logs=docker(['logs',name],False);(output/(label+'-container.log')).write_text(logs,encoding='utf-8')
            docker(['rm','-f',name],False)


def envoy(output):
    # The translation is explicit; it does not claim identical variable environments.
    rules=[('threshold','changed_rows >= 100',"int(request.headers['x-rows']) >= 100"),
        ('write_only','operation == "delete" && matched_rows != 0',"request.headers['x-operation'] == 'delete' && int(request.headers['x-rows']) != 0"),
        ('bounded','!(changed_rows > 5) || operation == "read"',"!(int(request.headers['x-rows']) > 5) || request.headers['x-operation'] == 'read'")]
    logs=[{'name':'envoy.access_loggers.stdout','filter':{'extension_filter':{'name':'envoy.access_loggers.extension_filters.cel',
        'typed_config':{'@type':'type.googleapis.com/envoy.extensions.access_loggers.filters.cel.v3.ExpressionFilter','expression':mapped}}},
        'typed_config':{'@type':'type.googleapis.com/envoy.extensions.access_loggers.stream.v3.StdoutAccessLog',
        'log_format':{'text_format_source':{'inline_string':f'AIRLOCK_CEL {name} %REQ(X-CASE-ID)%\n'}}}} for name,_,mapped in rules]
    hcm={'@type':'type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager',
        'stat_prefix':'fixture','route_config':{'name':'local','virtual_hosts':[{'name':'fixture','domains':['*'],
            'routes':[{'match':{'prefix':'/'},'direct_response':{'status':200,'body':{'inline_string':'fixture'}}}]}]},
        'http_filters':[{'name':'envoy.filters.http.router','typed_config':{'@type':'type.googleapis.com/envoy.extensions.filters.http.router.v3.Router'}}],
        'access_log':logs,'access_log_flush_interval':'0.1s'}
    config={'static_resources':{'listeners':[{'name':'fixture','address':{'socket_address':{'address':'0.0.0.0','port_value':8080}},
        'filter_chains':[{'filters':[{'name':'envoy.filters.network.http_connection_manager','typed_config':hcm}]}]}]}}
    cases=[('zero',0,'delete'),('small',3,'delete'),('high',100,'delete'),('read',200,'read')];expected={
        'threshold':{'high','read'},'write_only':{'small','high'},'bounded':{'zero','small','read'}}
    rows=[]
    with container(ENVOY,config,8080,['-c','/fixture.yaml','--disable-hot-restart','--concurrency','1','--log-level','error'],output,'envoy') as (name,port):
        with httpx.Client(base_url=f'http://127.0.0.1:{port}',trust_env=False,timeout=2) as client:
            for _ in range(100):
                try:
                    if client.get('/',headers={'x-case-id':'warmup','x-rows':'0','x-operation':'read'}).status_code==200:break
                except httpx.HTTPError:pass
                time.sleep(.1)
            else:raise RuntimeError('Envoy startup failed')
            for key,n,operation in cases:
                assert client.get('/',headers={'x-case-id':key,'x-rows':str(n),'x-operation':operation}).status_code==200
                for rule,expression,mapped in rules:
                    policy=Policy.parse(yaml.safe_dump({'version':'compat','rules':[{'id':rule,'expression':expression,'decision':'block'}]}))
                    outcome,hits=policy.evaluate({'tool':'sql_execute','resource':'customers','principal':'agent:demo','operation':operation,'changed_rows':n,'matched_rows':n},False)
                    rows.append({'case':key,'rule':rule,'airlock_expression':expression,'envoy_expression':mapped,'airlock_hit':bool(hits),'expected':key in expected[rule]})
            # Envoy access-log errors evaluate false; AIRLOCK invalid typed context blocks.
            client.get('/',headers={'x-case-id':'invalid'})
        for _ in range(50):
            raw=docker(['logs',name]);observed={tuple(line.split()[1:]) for line in raw.splitlines() if line.startswith('AIRLOCK_CEL ')}
            if all((r['rule'],r['case']) in observed for r in rows if r['expected']):break
            time.sleep(.1)
        for row in rows:
            row['envoy_hit']=(row['rule'],row['case']) in observed
            assert row['airlock_hit']==row['envoy_hit']==row['expected'],row
        assert not any(case=='invalid' for rule,case in observed)
        digest=docker(['image','inspect',ENVOY,'--format','{{json .RepoDigests}}']).strip()
    return {'image':ENVOY,'repo_digests':digest,'rows':rows,'status':'PASS',
        'scope':'Boolean/equality/ordering subset with explicit header-to-variable mapping; access-log filter, not Envoy authorization deployment.',
        'error_difference':'Missing/invalid Envoy attributes suppress its log. AIRLOCK rejects invalid typed activation and blocks authorization.'}


def collector(output):
    config={'receivers':{'otlp':{'protocols':{'http':{'endpoint':'0.0.0.0:4318'}}}},
        'exporters':{'debug':{'verbosity':'detailed'}},'service':{'pipelines':{'traces':{'receivers':['otlp'],'exporters':['debug']}}}}
    with container(OTEL,config,4318,['--config=/fixture.yaml'],output,'otel') as (name,port):
        with tempfile.TemporaryDirectory(prefix='airlock-otel-') as folder:
            gate=Gate(Settings(Path(folder)/'gate.db','a'*32,'r'*32,'k'*32,otlp_url=f'http://127.0.0.1:{port}/v1/traces',otlp_allow_loopback=True))
            action=gate.submit(Invocation(sql='UPDATE customers SET balance=0 WHERE id=1',idempotency_key='collector-real-test'))
            for _ in range(50):
                result=export(gate.store)
                if result['status']=='ok':break
                time.sleep(.1)
            assert result=={'status':'ok','exported':1},result
            for _ in range(50):
                raw=docker(['logs',name])
                if action['trace_id'] in raw:break
                time.sleep(.1)
            assert action['trace_id'] in raw and 'action.evaluated' in raw
            assert 'UPDATE customers' not in raw
            assert gate.get(action['id'])['state']=='pending'
            digest=docker(['image','inspect',OTEL,'--format','{{json .RepoDigests}}']).strip()
    return {'status':'PASS','image':OTEL,'repo_digests':digest,'trace_id':action['trace_id'],'result':result,'scope':'Official Collector accepts OTLP JSON and debug exporter records the actual trace; no production backend claim.'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=Path('evidence'));a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    report={}
    for label,check in [('envoy',envoy),('otel',collector)]:
        report[label]=check(a.output)
        (a.output/'container-integrations.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
