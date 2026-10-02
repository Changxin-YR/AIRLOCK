"""Deterministic tool-using agent simulator. It owns ONLY the agent credential.
No LLM is used here; this is a reproducible interview/demo driver.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx

SCENARIOS={'read':'SELECT count(*) AS remaining FROM customers',
           'delete':'DELETE FROM customers',
           'update':'UPDATE customers SET balance=balance+1 WHERE id=1',
           'blocked':'DROP TABLE customers'}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--scenario',choices=SCENARIOS,default='delete')
    parser.add_argument('--key',default=None,help='Reuse this exact key after an uncertain response')
    parser.add_argument('--status',help='Resume polling a known action without submitting again')
    parser.add_argument('--wait',type=int,default=330)
    parser.add_argument('--allow-internal-http',action='store_true',help='Only for the isolated Compose service named airlock')
    args=parser.parse_args()
    if not 0<=args.wait<=900:
        parser.error('--wait must be between 0 and 900 seconds')
    token=os.environ.get('AIRLOCK_AGENT_TOKEN')
    if not token:
        parser.error('Set AIRLOCK_AGENT_TOKEN; do not provide the reviewer token.')
    url=os.getenv('AIRLOCK_URL','http://127.0.0.1:8000')
    parsed=urlparse(url)
    local=parsed.hostname in {'127.0.0.1','localhost','::1'}
    internal=args.allow_internal_http and parsed.hostname=='airlock'
    if parsed.scheme not in {'http','https'} or (parsed.scheme=='http' and not (local or internal)):
        parser.error('Use HTTPS except for loopback or the explicit isolated Compose service.')
    key=args.key or 'demo-'+uuid.uuid4().hex
    print('Simulator, not a live LLM. Idempotency key:',key,flush=True)
    with httpx.Client(base_url=url,headers={'Authorization':'Bearer '+token},timeout=10,trust_env=False,follow_redirects=False) as client:
        try:
            response=client.get('/v1/actions/'+args.status) if args.status else client.post('/v1/actions',json={'sql':SCENARIOS[args.scenario],'idempotency_key':key})
            response.raise_for_status()
            action=response.json()
            print(json.dumps(action,ensure_ascii=False,indent=2),flush=True)
            deadline=time.monotonic()+args.wait
            if action['state']=='pending':
                print('Waiting for a separately authenticated human. No write has executed.',flush=True)
            while action['state']=='pending' and time.monotonic()<deadline:
                time.sleep(1)
                response=client.get('/v1/actions/'+action['id']);response.raise_for_status();action=response.json()
            print('Final observed state:',action['state'],flush=True)
            if action['state'] in {'rejected','blocked'}:
                # A deterministic safe alternative demonstrates structured-denial handling.
                read=client.post('/v1/actions',json={'sql':SCENARIOS['read'],'idempotency_key':key+'-safe'})
                read.raise_for_status()
                print('Safe fallback:',json.dumps(read.json(),ensure_ascii=False),flush=True)
            if action['state']=='pending':
                print('Polling stopped; the server still owns the decision. Resume with --status',action['id'])
        except httpx.HTTPError as error:
            print('Transport failed; outcome may be unknown. Query status or retry with the SAME key:',key,file=sys.stderr)
            raise SystemExit(1) from error


if __name__=='__main__':
    main()
