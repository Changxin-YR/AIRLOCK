"""Operator health check; optional webhook delivery does not authorize actions.

Exit 0: healthy; exit 2: active health alerts; exit 3: enabled notification
configuration or delivery is blocked, failed, unknown or still pending.
No notification is sent unless both --alert-config and --alert-state are given.
"""
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from airlock.alert_delivery import AlertConfig, deliver_alerts


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--url',required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--alert-config',type=Path,help='Operator-owned fixed endpoint/pins JSON; uses AIRLOCK_ALERT_WEBHOOK_TOKEN')
    parser.add_argument('--alert-state',type=Path,help='Dedicated persistent notification outbox, outside server volumes')
    args=parser.parse_args(argv);url=urlparse(args.url)
    if (args.alert_config is None)!=(args.alert_state is None):
        parser.error('--alert-config and --alert-state must be supplied together')
    if args.alert_state is not None and len({args.alert_config.resolve(),args.alert_state.resolve(),args.output.resolve()})!=3:
        parser.error('alert config, notification state and report output must be separate files')
    if url.username or url.password or url.query or url.fragment or url.path not in ('','/') or (url.scheme!='https' and not(url.scheme=='http' and url.hostname in {'127.0.0.1','::1','localhost'})):
        parser.error('HTTPS or loopback origin required')
    config=None
    if args.alert_config is not None:
        try:config=AlertConfig.model_validate_json(args.alert_config.read_text(encoding='utf-8'))
        except (OSError,ValueError):
            print(json.dumps({'status':'notification_blocked','error_code':'alert_configuration_invalid'}))
            raise SystemExit(3)
    with httpx.Client(timeout=10,trust_env=False,follow_redirects=False) as client:
        response=client.get(args.url.rstrip('/')+'/v1/operations/health',headers={'Authorization':'Bearer '+os.environ['AIRLOCK_REVIEWER_TOKEN']})
        response.raise_for_status();report=response.json()
    summary={'status':report['status'],'alert_codes':[a['code'] for a in report['alerts']]}
    exit_code=report['recommended_exit_code']
    if config is not None:
        report['notification']=deliver_alerts(config,report,args.alert_state)
        summary['notification']=report['notification']
        if report['notification']['status'] not in {'delivered','unchanged'}:exit_code=3
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary))
    raise SystemExit(exit_code)


if __name__=='__main__':main()
