"""One-shot authenticated readiness/alert check for an operator's scheduler."""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlparse
import httpx


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();url=urlparse(args.url)
    if url.username or url.password or url.query or url.fragment or url.path not in ('','/') or (url.scheme!='https' and not(url.scheme=='http' and url.hostname in {'127.0.0.1','::1','localhost'})):
        parser.error('HTTPS or loopback origin required')
    with httpx.Client(timeout=10,trust_env=False,follow_redirects=False) as client:
        response=client.get(args.url.rstrip('/')+'/v1/operations/health',headers={'Authorization':'Bearer '+os.environ['AIRLOCK_REVIEWER_TOKEN']})
        response.raise_for_status();report=response.json()
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':report['status'],'alert_codes':[a['code'] for a in report['alerts']]}))
    raise SystemExit(report['recommended_exit_code'])


if __name__=='__main__':main()
