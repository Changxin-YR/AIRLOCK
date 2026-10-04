"""Verify only a newly-created, uniquely named Compose test deployment.

No existing container/volume is reused or deleted. Credentials are generated in
an external temporary directory, never printed, and removed after the check.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
import errno,json,os,sqlite3
from pathlib import Path
import httpx
from airlock.sqlite_runtime import require_safe_sqlite, mapped_sqlite_libraries, verify_linked_build_report
with sqlite3.connect(':memory:') as connection:
    sqlite_runtime = require_safe_sqlite(connection)
sqlite_pin = json.loads(Path('/app/configs/sqlite-runtime.json').read_text())
assert all(sqlite_runtime[key] == sqlite_pin[key] for key in ('version', 'source_id'))
sqlite_runtime['loaded_shared_library_files'] = mapped_sqlite_libraries()
verify_linked_build_report(sqlite_runtime, sqlite_pin, Path('/opt/airlock-sqlite/build-report.json'))
assert os.getuid() != 0
assert not os.getenv('AIRLOCK_REVIEWER_TOKEN') and not os.getenv('AIRLOCK_AUDIT_KEY')
assert not Path('/data/airlock.db').exists()
assert not Path('/app/var/local.json').exists()
assert not Path('/var/run/docker.sock').exists()
assert os.statvfs('/app').f_flag & os.ST_RDONLY
caps = next(line.split(':')[1].strip() for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('CapEff:'))
assert int(caps,16) == 0
assert len([name for name in os.listdir('/sys/class/net') if name != 'lo']) == 1
with httpx.Client(base_url=os.environ['AIRLOCK_URL'],headers={'Authorization':'Bearer '+os.environ['AIRLOCK_AGENT_TOKEN']},trust_env=False,timeout=10) as c:
    response=c.post('/v1/actions',json={'sql':'DELETE FROM customers','idempotency_key':'docker-isolation-001'})
    assert response.status_code==202, response.text
    action=response.json()
    assert action['state']=='pending' and action['execution_occurred'] is False
    assert c.post('/v1/actions/'+action['id']+'/decision',json={'decision':'approve','review_digest':'0'*64,'expected_version':1,'reason':'forged agent approval'}).status_code==403
    assert c.get('/v1/audit').status_code==403
    denied=c.post('/v1/actions',json={'sql':'SELECT * FROM actions','idempotency_key':'docker-control-read'})
    assert denied.status_code==200 and denied.json()['state']=='blocked'
    print(json.dumps({'pending_id':action['id'],'uid':os.getuid(),'effective_capabilities':int(caps,16),'sqlite_runtime':sqlite_runtime,'checks':['agent_has_no_reviewer_or_audit_secret','target_database_not_mounted_in_agent','no_server_config_or_docker_socket','non_root_read_only_no_capabilities','agent_cannot_approve_or_read_audit','SQL_cannot_read_control_tables','write_waits_for_separate_reviewer','container_loads_pinned_sqlite_runtime']}))
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'evidence')
    args = parser.parse_args()
    if not shutil.which('docker'):
        raise SystemExit('ENVIRONMENT BLOCKED: Docker is required; this check was not run.')
    args.output.mkdir(parents=True, exist_ok=True)
    name = 'airlock-check-' + uuid.uuid4().hex[:12]
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    keys = {key: secrets.token_urlsafe(32) for key in
            ('AIRLOCK_AGENT_TOKEN', 'AIRLOCK_REVIEWER_TOKEN', 'AIRLOCK_AUDIT_KEY')}
    logs = []
    with tempfile.TemporaryDirectory(prefix='airlock-docker-') as temporary:
        env_file = Path(temporary) / 'compose.env'
        with open(env_file, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)) as handle:
            handle.write('\n'.join(f'{key}={value}' for key, value in keys.items()) + f'\nAIRLOCK_PORT={port}\n')
        # Explicit process environment wins over any unrelated operator variables.
        env = os.environ | keys | {'AIRLOCK_PORT': str(port)}
        base = ['docker', 'compose', '-p', name, '--env-file', str(env_file), '-f', str(ROOT / 'compose.yaml'), '--profile', 'demo']

        def run(arguments, timeout=240):
            result = subprocess.run(base + arguments, cwd=ROOT, env=env, text=True, capture_output=True, timeout=timeout)
            redacted = result.stdout + result.stderr
            for value in keys.values():
                redacted = redacted.replace(value, '[REDACTED]')
            logs.append(redacted)
            if result.returncode:
                raise RuntimeError(f'Compose command {arguments[0]} failed with exit code {result.returncode}; inspect docker-build.log')
            return result.stdout

        try:
            run(['version'], timeout=20)
            config = json.loads(run(['config', '--format', 'json'], timeout=20))
            assert set(config['services']['agent']['networks']) == {'protected'}
            assert set(config['services']['airlock']['networks']) == {'protected', 'ingress'}
            run(['build'], timeout=360)
            run(['up', '-d', 'airlock'], timeout=60)
            with httpx.Client(base_url=url, trust_env=False, timeout=5) as client:
                reviewer = {'Authorization': 'Bearer ' + keys['AIRLOCK_REVIEWER_TOKEN']}

                def ready():
                    for _ in range(80):
                        try:
                            if client.get('/healthz').status_code == 200:
                                return
                        except httpx.HTTPError:
                            pass
                        time.sleep(.25)
                    raise RuntimeError('Compose server did not become ready')

                ready()
                server_id = run(['ps', '-q', 'airlock'], timeout=20).strip()
                inspected = subprocess.run(['docker', 'inspect', '--format', '{{json .NetworkSettings}}', server_id],
                    text=True, capture_output=True, check=True, timeout=20)
                networking = json.loads(inspected.stdout)
                assert set(networking['Networks']) == {name + '_protected', name + '_ingress'}
                assert networking['Ports']['8000/tcp'] == [{'HostIp': '127.0.0.1', 'HostPort': str(port)}]
                output = run(['run', '--rm', '--no-deps', '-T', '--entrypoint', 'python', 'agent', '-c', PROBE], timeout=60)
                probe = json.loads(output.strip().splitlines()[-1])
                before = client.get('/v1/metrics', headers=reviewer).json()['customers']
                assert before == 1206
                run(['restart', 'airlock'], timeout=60)
                ready()
                detail = client.get('/v1/actions/' + probe['pending_id'], headers=reviewer).json()
                assert detail['state'] == 'pending'
                approved = client.post('/v1/actions/' + detail['id'] + '/decision', headers=reviewer, json={
                    'decision': 'approve', 'review_digest': detail['review_digest'], 'expected_version': detail['version'],
                    'reason': 'Automated isolation test reviewer verified the synthetic deletion',
                    'confirmation': detail['confirmation_required']})
                assert approved.status_code == 200 and approved.json()['state'] == 'executed'
                run(['restart', 'airlock'], timeout=60)
                ready()
                after = client.get('/v1/metrics', headers=reviewer).json()['customers']
                assert after == 0
                assert client.get('/v1/audit/verify', headers=reviewer).json()['valid']
                network = subprocess.run(['docker', 'network', 'inspect', name + '_protected'], text=True, capture_output=True, check=True, timeout=20)
                assert json.loads(network.stdout)[0]['Internal'] is True
                image_id=subprocess.run(['docker','inspect','--format','{{.Image}}',server_id],text=True,capture_output=True,check=True,timeout=20).stdout.strip()
                report = {'mode': 'real_docker_compose', 'project': name, 'probe': probe, 'runtime_image_id':image_id,
                    'rows_before_independent_approval': before, 'rows_after_approval_and_restart': after,
                    'additional_checks': ['pending_survives_server_restart_without_execution',
                        'approved_effect_and_audit_persist_without_reseeding', 'compose_network_is_internal',
                        'server_dual_network_agent_internal_only', 'published_port_is_loopback_only'],
                    'limitations': ['controlled synthetic deployment, not a general container escape audit',
                        'reviewer is automated test code, not a human A/B participant']}
                (args.output / 'docker-report.json').write_text(json.dumps(report, indent=2) + '\n')
                print(json.dumps(report, indent=2))
        except BaseException:
            for command in (['ps', '-a'], ['logs', '--no-color', '--tail', '120', 'airlock'], ['port', 'airlock', '8000']):
                try:
                    run(command, timeout=20)
                except Exception as diagnostic_error:
                    logs.append('Diagnostic unavailable: ' + str(diagnostic_error))
            raise
        finally:
            try:
                run(['down', '--volumes', '--remove-orphans'], timeout=60)
            finally:
                (args.output / 'docker-build.log').write_text('\n'.join(logs))


if __name__ == '__main__':
    main()
