"""Export an operator-authenticated checkpoint to separately controlled storage.

The destination must not be writable by the Agent or the server deployment.
This client never reads target databases or audit HMAC keys.
"""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse
import httpx


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();url=urlparse(args.url)
    if url.username or url.password or url.query or url.fragment or url.path not in ('','/') or (url.scheme!='https' and not(url.scheme=='http' and url.hostname in {'127.0.0.1','localhost','::1'})):
        parser.error('HTTPS or a loopback fixture origin required')
    with httpx.Client(timeout=10,trust_env=False,follow_redirects=False) as client:
        response=client.get(args.url.rstrip('/')+'/v1/audit/checkpoint',headers={'Authorization':'Bearer '+os.environ['AIRLOCK_REVIEWER_TOKEN']})
        response.raise_for_status();body=response.json()
    if set(body)!={'version','database_instance','seq','head','key_id','signature'}:raise ValueError('invalid checkpoint')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive creation preserves an earlier checkpoint; use timestamped files.
    with args.output.open('x',encoding='utf-8',newline='\n') as out:out.write(json.dumps(body,indent=2)+'\n')
    print(json.dumps({'events':body['seq'],'path':str(args.output),'storage_independence':'must be enforced by deployment permissions'}))


if __name__=='__main__':main()
