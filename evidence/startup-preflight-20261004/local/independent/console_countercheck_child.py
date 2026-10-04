
from pathlib import Path
import json,sqlite3,sys
from fastapi.testclient import TestClient
from airlock import api
from airlock.models import Settings
root=Path(sys.argv[1]);mode=sys.argv[2];root.mkdir()
database=root/'fresh-synthetic.sqlite'
settings=Settings(database,'fixture-agent-'+'a'*32,'fixture-reviewer-'+'r'*32,'fixture-audit-'+'k'*32)
api.CONSOLE=root/'console'
if mode=='missing_console':
 app=api.create_app(settings)
 with TestClient(app,base_url=settings.origin) as client:
  health=client.get('/healthz');home=client.get('/')
 result={'case':mode,'health_status':health.status_code,'health_body':health.json(),'homepage_status':home.status_code,'homepage_body':home.json(),'database_created':database.exists()}
 assert health.status_code==200 and home.status_code==503
else:
 api.CONSOLE.mkdir();(api.CONSOLE/'csp.json').write_text('{"script_hashes":"invalid-build-shape"}')
 try:api.create_app(settings)
 except ValueError as error:reason=str(error)
 else:raise AssertionError('bad CSP unexpectedly accepted')
 result={'case':mode,'startup_failure':reason,'database_created':database.exists()}
 assert reason=='invalid console script hashes' and database.exists()
with sqlite3.connect(database) as conn:
 result['seeded_customer_rows']=conn.execute('SELECT count(*) FROM customers').fetchone()[0]
 result['seed_marker']=conn.execute("SELECT value FROM meta WHERE key='seeded'").fetchone()[0]
assert result['seeded_customer_rows']==1206
print(json.dumps(result))
