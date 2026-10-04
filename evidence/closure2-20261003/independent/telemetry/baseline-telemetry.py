"""Bounded transactional OTLP/HTTP JSON outbox; never an authorization source."""
import hashlib
import ipaddress
import json
from urllib.parse import urlparse
import httpx
from .models import canonical


def endpoint(settings):
    if not settings.otlp_url:return None
    parsed=urlparse(settings.otlp_url)
    address=ipaddress.ip_address(parsed.hostname or '')
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path!='/v1/traces':raise ValueError('OTLP endpoint must end in /v1/traces')
    if not address.is_global and not (address.is_loopback and settings.otlp_allow_loopback):raise ValueError('OTLP private target rejected')
    if parsed.scheme!='https' and not(parsed.scheme=='http' and address.is_loopback and settings.otlp_allow_loopback):raise ValueError('OTLP requires HTTPS')
    return settings.otlp_url


def enqueue(conn,seq,action_id,event):
    trace=event.get('trace_id') or hashlib.sha256(action_id.encode()).hexdigest()[:32]
    span=hashlib.sha256(f'{trace}:{seq}'.encode()).hexdigest()[:16]
    at=event.get('at',0);end=max(1,int(at*1_000_000_000))
    snapshot=event.get('detail',{}).get('snapshot',{})
    duration=max(0,float(snapshot.get('evaluation_ms',0)))*1_000_000
    payload={'traceId':trace,'spanId':span,'name':event.get('kind','audit.event'),
        'kind':1,'startTimeUnixNano':str(max(1,end-int(duration))),'endTimeUnixNano':str(end),
        'attributes':[{'key':'airlock.action_id','value':{'stringValue':action_id}},
            {'key':'airlock.state','value':{'stringValue':event.get('state','unknown')}},
            {'key':'airlock.request_id','value':{'stringValue':event.get('request_id') or ''}}]}
    if conn.execute('SELECT count(*) FROM telemetry_outbox').fetchone()[0]>=1000:
        conn.execute("INSERT INTO meta VALUES('telemetry_dropped','1') ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1")
        return
    conn.execute('INSERT INTO telemetry_outbox(seq,payload) VALUES(?,?)',(seq,canonical(payload)))


def export(store):
    url=endpoint(store.settings)
    if not url:return {'status':'not_configured','exported':0}
    with store.connection() as conn:rows=conn.execute('SELECT seq,payload FROM telemetry_outbox ORDER BY seq LIMIT 100').fetchall()
    if not rows:return {'status':'ok','exported':0}
    body={'resourceSpans':[{'resource':{'attributes':[{'key':'service.name','value':{'stringValue':'airlock'}}]},
        'scopeSpans':[{'scope':{'name':'airlock.audit','version':'1'},'spans':[json.loads(r['payload']) for r in rows]}]}]}
    try:
        with httpx.Client(timeout=3,trust_env=False,follow_redirects=False) as client:
            with client.stream('POST',url,json=body) as response:
                if response.status_code!=200:raise ValueError('collector rejected')
                raw=bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw)>4096:raise ValueError('collector output bound')
                result=json.loads(raw or b'{}')
                if not isinstance(result,dict):raise ValueError('collector response type')
                partial=result.get('partialSuccess',{})
                if not isinstance(partial,dict) or str(partial.get('rejectedSpans',0))!='0':raise ValueError('collector partial rejection')
    except (ValueError,httpx.HTTPError,TypeError):
        return {'status':'retryable_error','exported':0,'retained':len(rows)}
    with store.transaction() as conn:
        conn.executemany('DELETE FROM telemetry_outbox WHERE seq=?',[(r['seq'],) for r in rows])
        conn.execute("INSERT INTO meta VALUES('telemetry_exported',?) ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+excluded.value",(str(len(rows)),))
    return {'status':'ok','exported':len(rows)}


def metrics(store):
    with store.connection() as conn:
        pending=conn.execute('SELECT count(*) FROM telemetry_outbox').fetchone()[0]
        values=dict(conn.execute("SELECT key,value FROM meta WHERE key IN ('telemetry_dropped','telemetry_exported')"))
    return {'pending_spans':pending,'dropped_spans':int(values.get('telemetry_dropped',0)),
        'exported_spans':int(values.get('telemetry_exported',0)),'delivery':'at_least_once; deterministic span IDs',
        'configured':bool(store.settings.otlp_url)}
