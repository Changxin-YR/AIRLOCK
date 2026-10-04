"""Operator health check; optional webhook delivery does not authorize actions.

Exit 0: healthy; exit 2: active health alerts; exit 3: enabled notification
configuration or delivery is blocked, failed, unknown or still pending.
Exit 4: server health could not be authenticated, fetched or validated. Such
failures never emit a healthy observation or a recovery notification.
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
from airlock.alert_delivery import AlertConfig, deliver_alerts, health_summary, health_observation_time


class HealthCheckFailure(Exception):
    pass


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate health key')
        result[key] = value
    return result


def fetch_health(origin):
    token = os.environ.get('AIRLOCK_REVIEWER_TOKEN')
    if not token or not 16 <= len(token) <= 4096 or any(not 33 <= ord(c) <= 126 for c in token):
        raise HealthCheckFailure('health_credential_missing_or_invalid')
    try:
        with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
            with client.stream('GET', origin.rstrip('/') + '/v1/operations/health',
                               headers={'Authorization': 'Bearer ' + token}) as response:
                if response.status_code != 200:
                    raise HealthCheckFailure('health_identity_rejected' if response.status_code in (401, 403)
                                             else 'health_http_unavailable')
                body = bytearray()
                for chunk in response.iter_bytes():
                    if len(body) + len(chunk) > 65536:
                        raise HealthCheckFailure('health_report_invalid')
                    body.extend(chunk)
        report = json.loads(body, object_pairs_hook=_unique_keys)
        status, _ = health_summary(report)
        if health_observation_time(report) is None:
            raise ValueError('server observation timestamp required')
        # Derive the process result from validated conditions, not a supplied
        # recommendation that could contradict the actual alert state.
        report['recommended_exit_code'] = 2 if status == 'alert' else 0
        return report
    except (httpx.HTTPError, OSError) as error:
        raise HealthCheckFailure('health_transport_unavailable') from error
    except (ValueError, TypeError, RecursionError) as error:
        raise HealthCheckFailure('health_report_invalid') from error


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
    try:
        report=fetch_health(args.url)
    except HealthCheckFailure as error:
        report={'status':'unknown','alerts':[],'error_code':str(error),
                'recommended_exit_code':4,'authorization_effect':'none; health was not confirmed'}
        if config is not None:
            report['notification']={'status':'not_attempted','error_code':'health_not_confirmed'}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'status':'unknown','error_code':str(error)}))
        raise SystemExit(4)
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
