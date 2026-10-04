import hashlib,json,os,subprocess,sys,threading,sqlite3
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from contextlib import closing
from airlock.alert_delivery import AlertConfig,deliver_alerts,_connect,CREDENTIAL_ENV
root=Path('var/bidirectional-20261003/ops-review')
state={'health_status':200,'health':{'status':'alert','alerts':[{'code':'pending_expiry_backlog'}],'checked_at':200},'posts':[]}
class Receiver(BaseHTTPRequestHandler):
 def log_message(self,*_):pass
 def do_GET(self):
  raw=json.dumps(state['health']).encode();self.send_response(state['health_status']);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def do_POST(self):
  raw=self.rfile.read(int(self.headers['Content-Length']));state['posts'].append(json.loads(raw));self.send_response(204);self.send_header('Content-Length','0');self.end_headers()
server=ThreadingHTTPServer(('127.0.0.1',0),Receiver);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
try:
 origin=f'http://127.0.0.1:{server.server_port}'
 config=AlertConfig(endpoint=origin+'/airlock/events',allow_loopback_fixture=True)
 cfg=root/'synthetic-alert-config.json';cfg.write_text(config.model_dump_json(),encoding='utf-8')
 outbox=root/'local.outbox.sqlite3';output=root/'report.json'
 env={'AIRLOCK_REVIEWER_TOKEN':'synthetic-reviewer-key-only','AIRLOCK_ALERT_WEBHOOK_TOKEN':'synthetic-webhook-key-only','PYTHONUTF8':'1','SYSTEMROOT':r'C:\Windows'}
 cmd=[sys.executable,'scripts/operational_check.py','--url',origin,'--output',str(output),'--alert-config',str(cfg),'--alert-state',str(outbox)]
 checks=[]
 for label,http_status,health,code,expected_posts in [
  ('alert_delivery',200,{'status':'alert','alerts':[{'code':'pending_expiry_backlog'}],'checked_at':200},2,1),
  ('identity_failure_no_recovery',401,{'status':'ok','alerts':[],'checked_at':300},4,1),
  ('stale_recovery_rejected',200,{'status':'ok','alerts':[],'checked_at':100},3,1),
  ('fresh_recovery',200,{'status':'ok','alerts':[],'checked_at':400},0,2),
 ]:
  state['health_status']=http_status;state['health']=health
  r=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=20)
  checks.append({'check':label,'exit_code':r.returncode,'expected_exit_code':code,'status':json.loads(output.read_text())['status'],'posts':len(state['posts']),'passed':r.returncode==code and len(state['posts'])==expected_posts})
  assert checks[-1]['passed'],checks[-1]
 assert [r['kind'] for r in state['posts']]==['alert','recovery']
 # Synthetic lookalike: expected names/order, intentionally no uniqueness or PK constraints.
 impostor=root/'schema-lookalike.sqlite3'
 with closing(sqlite3.connect(impostor)) as conn:
  conn.execute('CREATE TABLE notification_meta (key TEXT,value TEXT)')
  conn.execute('CREATE TABLE notification_targets (target_id TEXT,status TEXT,codes TEXT)')
  conn.execute('CREATE TABLE notification_events (seq INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT,target_id TEXT,payload TEXT,delivery_state TEXT,attempts INTEGER,response_status INTEGER,failure_code TEXT)')
 before=hashlib.sha256(impostor.read_bytes()).hexdigest()
 try:
  opened=_connect(impostor);opened.close();impostor_result='ACCEPTED'
 except (ValueError,sqlite3.Error):impostor_result='REJECTED'
 after=hashlib.sha256(impostor.read_bytes()).hexdigest()
 # Only generated synthetic token in this process; never load real env credential.
 os.environ[CREDENTIAL_ENV]='synthetic-webhook-key-only'
 with closing(sqlite3.connect(outbox)) as conn:
  conn.execute("UPDATE notification_meta SET value='null' WHERE key LIKE 'checked_at:%'");conn.commit()
 try:
  invalid=deliver_alerts(config,{'status':'alert','alerts':[{'code':'pending_expiry_backlog'}],'checked_at':500},outbox)
  corrupt_result={'result':invalid}
 except Exception as error:
  corrupt_result={'exception':type(error).__name__}
 report={'tested_commit_sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_hashes':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in ['airlock/alert_delivery.py','scripts/operational_check.py']},'synthetic_only':True,'real_http_chain':checks,'schema_lookalike':{'result':impostor_result,'file_changed':before!=after},'invalid_high_water':corrupt_result,'source_dirty':True}
 (root/'independent.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,indent=2))
finally:
 server.shutdown();server.server_close();thread.join()
