import hashlib,json,os,sys,sqlite3,tempfile,subprocess
from pathlib import Path
from contextlib import closing
sys.path.insert(0,str(Path.cwd()))
sys.path.insert(0,str(Path.cwd()/'tests'))
import airlock.alert_delivery as d
from test_alert_delivery import receiver,run_check,report,CODE,TOKEN
root=Path('var/bidirectional-20261003/operations')
result={'tested_commit_sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_hashes':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path('airlock/alert_delivery.py'),Path('scripts/operational_check.py')]},'probes':{}}
os.environ['AIRLOCK_ALERT_WEBHOOK_TOKEN']=TOKEN
with tempfile.TemporaryDirectory() as temp:
 p=Path(temp);cfg=d.AlertConfig(endpoint='http://127.0.0.1:1/airlock/events',allow_loopback_fixture=True)
 sent=[]
 d._post=lambda config,token,row:(sent.append(json.loads(row['payload'])) or ('delivered',204,None))
 business=p/'business.sqlite3'
 with closing(sqlite3.connect(business)) as c:c.execute('CREATE TABLE protected(value TEXT)');c.execute("INSERT INTO protected VALUES('untouched')");c.commit()
 before=business.read_bytes();r=d.deliver_alerts(cfg,report(CODE),business)
 with closing(sqlite3.connect(business)) as c:tables=[row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
 result['probes']['foreign_database']={'delivery_status':r['status'],'database_modified':business.read_bytes()!=before,'tables':tables,'sent_count':len(sent)}
 out=p/'outbox.sqlite3';sent.clear()
 d.deliver_alerts(cfg,dict(report(CODE),checked_at=200.0),out)
 stale=d.deliver_alerts(cfg,dict(report(),checked_at=100.0),out)
 result['probes']['stale_recovery']={'status':stale['status'],'kinds':[row['kind'] for row in sent]}
 with receiver() as server:
  server['report']=dict(report(CODE),recommended_exit_code=0)
  cli=run_check(server,p)
  result['probes']['false_success_exit']={'exit_code':cli.returncode,'stdout':cli.stdout.strip()}
 assert result['probes']['foreign_database']['database_modified']
 assert result['probes']['stale_recovery']['kinds']==['alert','recovery']
 assert result['probes']['false_success_exit']['exit_code']==0
 result['reproduced']=True
(root/'baseline-results.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
