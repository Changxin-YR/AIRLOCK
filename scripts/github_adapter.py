"""Run the isolated GitHub adapter or operate its separately authenticated relay.

Relay claim files contain a one-use credential: keep them in ignored var/, never
in the Git evidence archive. The relay operator must perform exactly the exported
creation once, then independently read the issue and attest the returned fields.
--out names a one-use reservation: claim.json is written inside the new private
directory claim.json.private/. Use stdout's output path for the next command.
"""
import argparse
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
import uvicorn
from airlock.github_adapter import AdapterConfig, ObservedIssue, create_app, secret
from airlock.private_files import reserve_private_output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    serve = commands.add_parser('serve')
    serve.add_argument('--config', required=True)
    serve.add_argument('--database', required=True)
    serve.add_argument('--port', type=int, required=True)
    serve.add_argument('--host', choices=['127.0.0.1', '0.0.0.0'], default='127.0.0.1')
    for name in ('relay-claim', 'relay-complete', 'direct-reconcile'):
        command = commands.add_parser(name)
        command.add_argument('--url', required=True, help='http://127.0.0.1:<port>; operate remote deployments over a private tunnel')
        command.add_argument('--credential-env', default='AIRLOCK_GITHUB_RELAY_TOKEN')
        command.add_argument('--out', required=True,
                             help='One-use reservation: NAME writes NAME.private/NAME with private permissions; stdout returns the actual path')
        if name in {'relay-claim', 'direct-reconcile'}:
            command.add_argument('--action-id', required=True)
            if name == 'direct-reconcile':
                command.add_argument('--issue-node-id', required=True)
        else:
            command.add_argument('--claim', required=True)
            command.add_argument('--observed', required=True, help='ObservedIssue JSON independently read back from GitHub')
            command.add_argument('--reference', required=True, help='Local evidence filename or trusted observation identifier')
    args = parser.parse_args()
    if args.command == 'serve':
        config = AdapterConfig.model_validate_json(Path(args.config).read_text(encoding='utf-8'))
        uvicorn.run(create_app(config, Path(args.database)), host=args.host, port=args.port, access_log=False)
        return
    parsed = urlparse(args.url)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port or parsed.path not in ('', '/') or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('relay CLI requires a fixed localhost origin')
    if not re.fullmatch(r'AIRLOCK_GITHUB_[A-Z0-9_]+', args.credential_env):
        raise ValueError('dedicated relay credential environment name required')
    body = None
    if args.command in {'relay-claim', 'direct-reconcile'}:
        action_id = args.action_id
        phase = 'claim' if args.command == 'relay-claim' else 'reconcile'
        if phase == 'reconcile':
            body = {'issue_node_id': args.issue_node_id}
    else:
        claim = json.loads(Path(args.claim).read_text(encoding='utf-8'))
        observed = ObservedIssue.model_validate_json(Path(args.observed).read_text(encoding='utf-8'))
        action_id = claim['action_id']
        phase = 'complete'
        body = {'claim_token': claim['claim_token'], 'binding_digest': claim['binding_digest'],
                'observed_issue': observed.model_dump(), 'observation_reference': args.reference}
    if not re.fullmatch(r'[a-f0-9]{32}', action_id):
        raise ValueError('invalid action identifier')
    token = secret(args.credential_env)
    # Reserve before claiming; an accidental rerun must not consume another claim.
    with reserve_private_output(args.out) as (output, destination):
        with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
            response = client.post(args.url.rstrip('/') + '/operator/' + phase + '/' + action_id,
                                   headers={'Authorization': 'Bearer ' + token}, json=body)
            if response.status_code != 200:
                raise RuntimeError('relay operation rejected: HTTP ' + str(response.status_code))
            result = response.json()
        destination.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': str(output), 'action_id': action_id, 'operation': phase,
                      'receipt_verification': 'github_readback' if phase == 'reconcile' else 'operator_attested'}))


if __name__ == '__main__':
    main()
