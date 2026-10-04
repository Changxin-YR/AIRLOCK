"""Replay the frozen startup baseline using only disposable synthetic inputs."""
from pathlib import Path
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile

BASELINE = 'f27b447e268209a8b8f480111e55a3f6bb1bedce'
ROOT = Path.cwd()
OUTPUT = ROOT / 'var/startup-preflight-20261004/independent'
OUTPUT.mkdir(parents=True, exist_ok=True)
python = str(Path(sys.executable).resolve())
source = subprocess.check_output(['git', 'archive', '--format=tar', BASELINE, '--', 'airlock', 'configs', 'policies'], cwd=ROOT)
(OUTPUT / 'baseline-source.tar').write_bytes(source)
observations = []

with tempfile.TemporaryDirectory(prefix='airlock-startup-countercheck-') as temporary:
    isolated = Path(temporary)
    checkout = isolated / 'baseline'
    checkout.mkdir()
    with tarfile.open(fileobj=io.BytesIO(source)) as archive:
        for member in archive.getmembers():
            destination = (checkout / member.name).resolve()
            assert destination.is_relative_to(checkout.resolve()) and not member.issym() and not member.islnk()
        archive.extractall(checkout, filter='data')
    environment = {
        'SystemRoot': r'C:\Windows', 'TEMP': str(isolated), 'TMP': str(isolated),
        'PYTHONUTF8': '1', 'PYTHONPATH': str(checkout),
        'AIRLOCK_AGENT_TOKEN': 'fixture-agent-' + 'a' * 32,
        'AIRLOCK_REVIEWER_TOKEN': 'fixture-reviewer-' + 'r' * 32,
        'AIRLOCK_AUDIT_KEY': 'fixture-audit-' + 'k' * 32,
        'AIRLOCK_DB': str(isolated / 'must-not-open.sqlite'),
    }
    for name, change in [('numeric_environment', {'AIRLOCK_TTL': 'synthetic-private-TTL-marker'}),
                         ('origin_port_environment', {'AIRLOCK_ORIGIN': 'http://127.0.0.1:synthetic-private-port-marker'})]:
        done = subprocess.run([python, '-m', 'airlock', 'serve'], cwd=isolated,
            env=environment | change, capture_output=True, timeout=12)
        (OUTPUT / (name + '.stdout.log')).write_bytes(done.stdout)
        (OUTPUT / (name + '.stderr.log')).write_bytes(done.stderr)
        marker = next(iter(change.values())).split(':')[-1].encode()
        result = {'case': name, 'child_exit_code': done.returncode,
                  'input_marker_in_stderr': marker in done.stderr,
                  'traceback_in_stderr': b'Traceback' in done.stderr,
                  'database_created': Path(environment['AIRLOCK_DB']).exists()}
        assert done.returncode != 0 and result['input_marker_in_stderr'] and result['traceback_in_stderr']
        assert not result['database_created']
        observations.append(result)

    child = r'''
from pathlib import Path
import json,sqlite3,sys
from fastapi.testclient import TestClient
from airlock import api
from airlock.models import Settings
root=Path(sys.argv[1]);mode=sys.argv[2];root.mkdir()
database=root/'fresh-synthetic.sqlite'
settings=Settings(database,'fixture-agent-'+'a'*32,'fixture-reviewer-'+'r'*32,'fixture-audit-'+'k'*32)
api.CONSOLE=root/'console'
if mode=='missing_console':
 app=api.create_app(settings)
 with TestClient(app,base_url=settings.origin) as client:
  health=client.get('/healthz');home=client.get('/')
 result={'case':mode,'health_status':health.status_code,'health_body':health.json(),'homepage_status':home.status_code,'homepage_body':home.json(),'database_created':database.exists()}
 assert health.status_code==200 and home.status_code==503
else:
 api.CONSOLE.mkdir();(api.CONSOLE/'csp.json').write_text('{"script_hashes":"invalid-build-shape"}')
 try:api.create_app(settings)
 except ValueError as error:reason=str(error)
 else:raise AssertionError('bad CSP unexpectedly accepted')
 result={'case':mode,'startup_failure':reason,'database_created':database.exists()}
 assert reason=='invalid console script hashes' and database.exists()
with sqlite3.connect(database) as conn:
 result['seeded_customer_rows']=conn.execute('SELECT count(*) FROM customers').fetchone()[0]
 result['seed_marker']=conn.execute("SELECT value FROM meta WHERE key='seeded'").fetchone()[0]
assert result['seeded_customer_rows']==1206
print(json.dumps(result))
'''
    (OUTPUT / 'console_countercheck_child.py').write_text(child, encoding='utf-8')
    for mode in ('missing_console', 'invalid_csp'):
        done = subprocess.run([python, '-c', child, str(isolated / mode), mode], cwd=isolated,
            env=environment, capture_output=True, timeout=12)
        (OUTPUT / (mode + '.stdout.log')).write_bytes(done.stdout)
        (OUTPUT / (mode + '.stderr.log')).write_bytes(done.stderr)
        assert done.returncode == 0, (mode, done.stderr.decode('utf-8', 'replace'))
        result = json.loads(done.stdout)
        result['child_exit_code'] = done.returncode
        observations.append(result)

report = {'status': 'REPRODUCED', 'source_commit': BASELINE,
    'source_tar_sha256': hashlib.sha256(source).hexdigest(),
    'cases': observations,
    'scope': 'Frozen Git source copied to disposable directory; only synthetic environment mappings, fresh test databases and local TestClient. No existing config, database or host credential read. No network connections or model calls.',
    'exit_meaning': 'The outer exit0 means all expected baseline defects were observed. Console child exit0 means the defect assertion script completed, not a healthy application.',
    'findings': [
        {'id': 'START-ENV-LEAK', 'severity': 'P2', 'code': 'airlock/models.py:Settings.from_env and airlock/__main__.py:main',
         'summary': 'Malformed numeric/port environment values escape as Uvicorn startup tracebacks containing the original value.'},
        {'id': 'START-CONSOLE-READINESS', 'severity': 'P2', 'code': 'airlock/api.py:create_app, health, index',
         'summary': 'Missing console index yields HTTP503 while /healthz returns 200 status ok. This is a console-readiness limitation, not an authorization bypass.'},
        {'id': 'START-SIDE-EFFECT', 'severity': 'P2', 'code': 'airlock/api.py:create_app before console validation; airlock/service.py:Gate.__init__',
         'summary': 'Invalid CSP prevents startup only after the fresh SQLite database has been created, schema installed and 1206 rows seeded.'}],
    'doctor_counterexample_requirements': [
        'Invalid environment/config values produce stable field/error codes with no traceback, raw input value, token or path details.',
        'Detect missing index.html, invalid/missing CSP and missing referenced JS/CSS before declaring console ready; keep liveness separate from readiness.',
        'Never instantiate Gate, Store or SemanticAdvisor or open any persistent SQLite path; allow only explicit in-memory runtime check.',
        'Do not create the DB parent, config directory, semantic ledger, WAL, SHM or lock files, including on failed validation.',
        'No DNS, socket, browser, subprocess server or model call; unavailable external authentication/archive/notifications must remain unverified.',
        'Use only explicitly selected synthetic config in tests; preserve omitted-config environment compatibility and existing environment precedence.',
        'A successful preflight is configuration/build readiness, not proof of production permissions, live IdP or successful business execution.']}
(OUTPUT / 'RESULT.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report, indent=2))
