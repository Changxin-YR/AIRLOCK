"""Independent synthetic loopback chain; never uses configured operator credentials."""
import hashlib,json,os,socket,sqlite3,subprocess,sys,tempfile,threading,time
from contextlib import closing
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import httpx,uvicorn
from fastapi.testclient import TestClient
from airlock.alert_inbox import create_app
from airlock.alert_delivery import AlertConfig,deliver_alerts

BASE=Path('var/bidirectional-20261003/operations')
READ='synthetic-closure-read-'+'r'*32
WRITE='synthetic-closure-write-'+'w'*32
REVIEW='synthetic-closure-review-'+'p'*32
CODE='pending_expiry_backlog'
checks=[]
source_paths=['airlock/alert_delivery.py','airlock/alert_inbox.py','airlock/operations.py','scripts/operational_check.py']
meta={'tested_commit_sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
      'working_tree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),
      'source_hashes':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in source_paths}}
with tempfile.TemporaryDirectory() as temporary:
 root=Path(temporary)
 healthy={'status':'alert','alerts':[{'code':CODE}],'checked_at':100.0,'recommended_exit_code':2}
 status={'http':200,'report':healthy}
 class Health(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_GET(self):
   assert self.path=='/v1/operations/health' and self.headers['Authorization']=='Bearer '+REVIEW
   body=json.dumps(status['report']).encode()
   self.send_response(status['http']);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 health=ThreadingHTTPServer(('127.0.0.1',0),Health)
 thread=threading.Thread(target=health.serve_forever,daemon=True);thread.start()
 listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();port=listener.getsockname()[1]
 origin=f'http://127.0.0.1:{port}'
 database=root/'inbox.sqlite3'
 app=create_app(database,write_token=WRITE,read_token=READ,port=port)
 server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,access_log=False,log_level='error',proxy_headers=False))
 webthread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);webthread.start()
 configuration=AlertConfig(endpoint=origin+'/airlock/events',allow_loopback_fixture=True)
 cfg=root/'webhook.json';cfg.write_text(configuration.model_dump_json())
 env={key:os.environ[key] for key in ('SystemRoot','WINDIR','PATH','TEMP','TMP') if key in os.environ}
 env.update(AIRLOCK_REVIEWER_TOKEN=REVIEW,AIRLOCK_ALERT_WEBHOOK_TOKEN=WRITE,PYTHONUTF8='1')
 outbox=root/'outbox.sqlite3'
 def check(name,expected):
  command=[sys.executable,'scripts/operational_check.py','--url',f'http://127.0.0.1:{health.server_port}',
           '--output',str(root/'report.json'),'--alert-config',str(cfg),'--alert-state',str(outbox)]
  run=subprocess.run(command,env=env,capture_output=True,text=True,timeout=20)
  parsed=json.loads(run.stdout)
  assert run.returncode==expected,(name,run.returncode,run.stdout,run.stderr)
  assert not run.stderr and all(token not in run.stdout for token in (READ,WRITE,REVIEW))
  with httpx.Client(base_url=origin,trust_env=False) as client:
   rows=client.get('/api/events',headers={'Authorization':'Bearer '+READ}).json()['events']
  checks.append({'name':name,'exit_code':run.returncode,'result':parsed,'receiver_kinds':[r['kind'] for r in rows]})
  return rows
 try:
  assert len(check('fresh_alert_persists_and_is_readable',2))==1
  status['http']=403;status['report']={'status':'ok','alerts':[],'checked_at':101.0,'recommended_exit_code':0}
  assert len(check('invalid_identity_cannot_recover',4))==1
  status['http']=200;status['report']['checked_at']=99.0
  assert len(check('stale_healthy_cannot_recover',3))==1
  status['report']['checked_at']=101.0
  rows=check('confirmed_new_health_recovers_after_restarts',0)
  assert [r['kind'] for r in rows]==['recovery','alert']
  assert len(check('repeat_is_persistent_noop',0))==2
  status['report']={'status':'alert','alerts':[{'code':CODE}],'checked_at':102.0,'recommended_exit_code':0}
  assert [r['kind'] for r in check('forged_success_hint_still_exits_alert',2)]==['alert','recovery','alert']
  with httpx.Client(base_url=origin,trust_env=False) as client:
   before=client.get('/api/events',headers={'Authorization':'Bearer '+READ}).json()
   payload={k:before['events'][0][k] for k in ('version','event_id','kind','status','alert_codes','resolved_codes')}
   replay=client.post('/airlock/events',json=payload,headers={'Authorization':'Bearer '+WRITE,'Idempotency-Key':payload['event_id']})
   assert replay.status_code==200 and replay.json()['duplicate'] is True
   rejected=client.post('/airlock/events',json=payload,headers={'Authorization':'Bearer '+READ,'Idempotency-Key':payload['event_id']})
   assert rejected.status_code==401
   assert client.get('/api/events',headers={'Authorization':'Bearer '+READ}).json()==before
   checks.append({'name':'exact_replay_deduplicated_reader_cannot_forge','replay_http':200,'reader_write_http':401,'event_count':3})
 finally:
  server.should_exit=True;webthread.join(5);listener.close()
  health.shutdown();health.server_close();thread.join(3)
  assert not webthread.is_alive() and not thread.is_alive()
 with TestClient(create_app(database,write_token=WRITE+'-next',read_token=READ+'-next',port=8767),base_url='http://127.0.0.1:8767') as restarted:
  assert restarted.get('/api/events',headers={'Authorization':'Bearer '+READ}).status_code==401
  assert len(restarted.get('/api/events',headers={'Authorization':'Bearer '+READ+'-next'}).json()['events'])==3
  checks.append({'name':'receiver_restart_identity_rotation_retains_history','old_read_http':401,'event_count':3})
 business=root/'business.sqlite3'
 with closing(sqlite3.connect(business)) as conn:
  conn.execute('CREATE TABLE protected(value TEXT)');conn.execute("INSERT INTO protected VALUES('untouched')");conn.commit()
 before=business.read_bytes();os.environ['AIRLOCK_ALERT_WEBHOOK_TOKEN']=WRITE
 blocked=deliver_alerts(configuration,healthy,business)
 assert blocked['status']=='blocked' and business.read_bytes()==before
 checks.append({'name':'foreign_database_untouched','result':blocked,'hash_unchanged':True})
result=dict(meta,status='PASS',scope='isolated synthetic localhost HTTP; no real operator/person/cloud identity',checks=checks)
(BASE/'independent-chain.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
