import json,os,hashlib
from pathlib import Path
import airlock.alert_delivery as module
root=Path('var/bidirectional-20261003/ops-review')
os.environ[module.CREDENTIAL_ENV]='synthetic-webhook-key-only'
def unexpected(*args):raise AssertionError('No outbound send is allowed in this synthetic schema probe')
module._post=unexpected
result=module.deliver_alerts(module.AlertConfig(endpoint='http://127.0.0.1:9/airlock/events',allow_loopback_fixture=True),{'status':'alert','alerts':[{'code':'pending_expiry_backlog'}],'checked_at':201},root/'schema-lookalike.sqlite3')
print(json.dumps({'synthetic_only':True,'schema_lookalike_alert_result':result,'source_hash':hashlib.sha256(Path('airlock/alert_delivery.py').read_bytes()).hexdigest()},indent=2))
