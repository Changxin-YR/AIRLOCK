import hashlib
import json
from pathlib import Path

base = Path('var/closure2-20261003/cross-archive')

def run(name, counts):
    status = json.loads((base / (name + '.log.status.json')).read_text())
    return {'log': name + '.log', 'junit': name + '.xml', 'receipt': name + '.log.status.json',
            'command': status['command'], 'exit_code': status['exit_code'],
            'tested_commit_sha': status['tested_commit_sha'],
            'tracked_source_dirty': status['tracked_source_dirty'], 'counts': counts}

report = {
    'status': 'PASS', 'reviewer_changed_application_code': False,
    'scope': 'Independent second-author archive receipt/body/version/retention and CLI output ordering probes',
    'runs': [run('initial', {'passed': 8, 'failed': 2}),
             run('repaired-original', {'passed': 10, 'failed': 0}),
             run('final', {'passed': 11, 'failed': 0})],
    'finding': {'severity': 'P2', 'status': 'FIXED_BY_PARENT',
        'code': 'scripts/archive_checkpoint_s3.py:main',
        'trigger': 'The configured receipt output already exists as a file or directory.',
        'before': 'A COMPLIANCE put occurred before output open raised OSError; the new version receipt was not saved.',
        'after': 'Output is exclusively reserved and fsynced before client creation/upload; existing paths cause zero remote writes.',
        'normal_flow': 'A complete valid receipt replaces the reservation with no residual marker; a second verification exports a complete verified result with no extra upload.'},
    'checks': ['Exact version requested for both retention and content',
        'COMPLIANCE extension accepted without receipt mutation', 'Storage version/body substitutions rejected',
        'Well-formed rekeyed receipt cannot relabel database_instance or seq in unchanged body',
        'GOVERNANCE and shortened retention rejected', 'Expired receipt rejected before storage reads',
        'Body streams close on success and failure', 'Existing output file/directory causes no upload',
        'Successful upload and subsequent read verification replace reservations with valid complete JSON'],
    'limitations': ['Synthetic S3-compatible method fixture; no new cloud resource or live credential used.',
        'These tests do not claim filesystem crash atomicity during the final receipt write.',
        'Actual S3 Object Lock and whole-project frozen CI validation remain the parent task responsibility.',
        'Receipt verification does not establish the HMAC chain without separately retained audit keys.']
}
(base / 'RESULT.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
files = {}
for item in sorted(base.rglob('*')):
    if not item.is_file() or '__pycache__' in item.parts or item.name == 'MANIFEST.json':
        continue
    raw = item.read_bytes()
    files[item.relative_to(base).as_posix()] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
(base / 'MANIFEST.json').write_text(json.dumps({'files': files}, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'status': 'PASS', 'payloads': len(files)}))
