"""Exercise one explicitly supplied GitHub task through an isolated approval gate.

This operator-run harness uses distinct ephemeral role credentials, never a model
decision. An external connector operator creates the exact exported issue once
and supplies independently read-back ObservedIssue JSON. It is an operator
attestation, not a direct server GitHub credential or independent human study.
Raw output may contain task text: keep it in ignored var/.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from airlock.github_adapter import AdapterConfig, IssueArguments, ObservedIssue
from scripts.support import server, stop_process_tree


def save(path, value):
    with path.open('x', encoding='utf-8') as destination:
        json.dump(value, destination, ensure_ascii=False, indent=2)
        destination.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--task', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    config = AdapterConfig.model_validate_json(args.config.read_text(encoding='utf-8'))
    if config.mode != 'relay':
        raise ValueError('explicit relay mode required')
    task = IssueArguments.model_validate_json(args.task.read_text(encoding='utf-8'))
    args.output.mkdir(parents=True, exist_ok=False)
    gate_token, relay_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    endpoint = f'http://127.0.0.1:{port}'
    env = {k: v for k, v in os.environ.items() if k in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP'}}
    env.update({config.gate_credential_env: gate_token, config.relay_credential_env: relay_token})
    upstream = args.output / 'upstreams.json'
    save(upstream, {'tools': [{'name': 'upstream:github_issue', 'resource': 'github:issues',
         'url': endpoint, 'allow_loopback': True, 'credential_env': config.gate_credential_env,
         'execution_model': 'append_only_create', 'arguments': {'title': 'string', 'body': 'string'}}]})
    with (args.output / 'adapter.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, 'scripts/github_adapter.py', 'serve', '--config', str(args.config),
                    '--database', str(args.output / 'adapter.db'), '--port', str(port)], env=env, stdout=log, stderr=log)
        try:
            with httpx.Client(base_url=endpoint, timeout=5, trust_env=False) as adapter:
                for _ in range(100):
                    try:
                        if adapter.get('/receipts/absent').status_code == 403: break
                    except httpx.HTTPError: pass
                    time.sleep(.05)
                else: raise RuntimeError('adapter startup failed')
                operator = {'Authorization': 'Bearer ' + relay_token}
                with server({'AIRLOCK_UPSTREAM_FILE': str(upstream.resolve()), config.gate_credential_env: gate_token,
                             'AIRLOCK_TTL': '600'}) as (_, keys, client):
                    agent = {'Authorization': 'Bearer ' + keys['AIRLOCK_AGENT_TOKEN']}
                    reviewer = {'Authorization': 'Bearer ' + keys['AIRLOCK_REVIEWER_TOKEN']}
                    request = {'tool': 'upstream:github_issue', 'arguments': task.model_dump(),
                               'idempotency_key': 'live-rejected-' + secrets.token_hex(8)}
                    def submit():
                        response = client.post('/v1/actions', json=request, headers=agent)
                        response.raise_for_status()
                        return client.get('/v1/actions/' + response.json()['id'], headers=reviewer).json()
                    def decision(action, value):
                        return {'decision': value, 'review_digest': action['review_digest'],
                                'expected_version': action['version'], 'confirmation': action['confirmation_required'],
                                'reason': 'User-authorized project task; isolated scripted review of the exact issue payload'}
                    rejected = submit()
                    assert rejected['state'] == 'pending'
                    route = '/v1/actions/' + rejected['id'] + '/decision'
                    assert client.post(route, json=decision(rejected, 'approve'), headers=agent).status_code == 403
                    assert adapter.post('/operator/claim/' + rejected['id'], headers=operator).status_code == 404
                    assert client.post(route, json=decision(rejected, 'reject'), headers=reviewer).json()['state'] == 'rejected'
                    assert adapter.post('/operator/claim/' + rejected['id'], headers=operator).status_code == 404
                    request['idempotency_key'] = 'live-approved-' + secrets.token_hex(8)
                    approved = submit()
                    save(args.output / 'review-snapshot.json', approved)
                    assert approved['state'] == 'pending' and approved['impact']['is_estimate']
                    response = client.post('/v1/actions/' + approved['id'] + '/decision',
                                           json=decision(approved, 'approve'), headers=reviewer)
                    response.raise_for_status(); assert response.json()['state'] == 'unknown'
                    response = adapter.post('/operator/claim/' + approved['id'], headers=operator)
                    response.raise_for_status(); claim = response.json()
                    save(args.output / 'connector-task.json', {k: claim[k] for k in
                         ('repository_node_id', 'repository_full_name', 'title', 'body', 'action_id', 'request_hash', 'valid_until')})
                    assert adapter.post('/operator/claim/' + approved['id'], headers=operator).status_code == 409
                    print(json.dumps({'status': 'AWAITING_OPERATOR_CREATE_ONCE_AND_READBACK',
                                      'task': str(args.output / 'connector-task.json')}, ensure_ascii=False), flush=True)
                    observed_file = args.output / 'observed.json'
                    while not observed_file.exists():
                        if time.time() >= claim['valid_until']: raise TimeoutError('operator observation absent; do not resend mutation')
                        time.sleep(.2)
                    observed = ObservedIssue.model_validate_json(observed_file.read_text(encoding='utf-8'))
                    completion = {'claim_token': claim['claim_token'], 'binding_digest': claim['binding_digest'],
                                  'observed_issue': observed.model_dump(), 'observation_reference': 'connector GitHub REST readback / observed.json'}
                    response = adapter.post('/operator/complete/' + approved['id'], json=completion, headers=operator)
                    response.raise_for_status(); save(args.output / 'adapter-receipt.json', response.json())
                    final = client.post('/v1/actions/' + approved['id'] + '/reconcile', headers=agent)
                    final.raise_for_status(); assert final.json()['state'] == 'executed'
                    assert client.post('/v1/actions', json=request, headers=agent).json()['state'] == 'executed'
                    audit = client.get('/v1/audit', headers=reviewer).json()
                    verification = client.get('/v1/audit/verify', headers=reviewer).json()
                    assert verification['valid']
                    save(args.output / 'audit.json', audit)
                    save(args.output / 'summary.json', {'status': 'PASS', 'mode': 'real_github_operator_relay',
                         'tested_commit_sha': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                         'scope': 'one user-authorized real issue, ephemeral separately credentialed scripted review',
                         'human_reviewers': 0, 'model_approvals': 0, 'direct_runtime_github_token': False,
                         'business_side_effects': 1, 'issue_url': observed.url, 'action_id': approved['id'],
                         'request_hash': claim['request_hash'], 'receipt': response.json(), 'audit_verification': verification,
                         'checks': ['agent_approval_denied', 'pending_not_claimable', 'rejected_not_claimable',
                                    'approved_queued_unknown', 'claim_once', 'exact_readback', 'reconcile_executed',
                                    'same_key_no_duplicate', 'audit_chain_valid'],
                         'observed_sha256': hashlib.sha256(observed_file.read_bytes()).hexdigest()})
                    print(json.dumps({'status': 'PASS', 'issue_url': observed.url, 'receipt_verification': 'operator_attested'}), flush=True)
        finally:
            stop_process_tree(process)


if __name__ == '__main__':
    main()
