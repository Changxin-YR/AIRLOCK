"""Read delivery evidence from committed Git objects in the AIRLOCK checkout."""
import hashlib
import json
import subprocess

BASE = 'evidence/project-maintenance-20261004'
CHECKPOINT = 'evidence/project-checkpoint-20261004'
SOURCE = '7073fb76a2e46365fabe6f51a3765de267863890'
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()


def blob(name):
    return subprocess.check_output(['git', 'show', f'{head}:{name}'])


def verify(items):
    for name, entry in items.items():
        raw = blob(name)
        assert len(raw) == entry['bytes'], name
        assert hashlib.sha256(raw).hexdigest() == entry['sha256'], name


manifest = json.loads(blob(BASE + '/ARCHIVE_MANIFEST.json'))
documents = json.loads(blob(BASE + '/DOCUMENT_BINDINGS.json'))
checkpoint = json.loads(blob(CHECKPOINT + '/PUBLIC_MANIFEST.json'))
assert manifest['tested_commit_sha'] == documents['tested_commit_sha'] == SOURCE
verify({BASE + '/' + name: value for name, value in manifest['files'].items()})
verify(documents['documents'])
verify({CHECKPOINT + '/' + name: value for name, value in checkpoint['files'].items()})
scope = [
    'airlock', 'frontend', 'configs', 'policies', 'benchmark', 'scripts', 'tests',
    'tests-js', 'requirements.txt', 'requirements-dev.txt', 'requirements-archive.txt',
    'pyproject.toml', 'package.json', 'package-lock.json', 'Dockerfile', 'compose.yaml',
    '.github', 'docs/acceptance/build_matrix.py', 'docs/acceptance/validate_matrix.py',
]
changed = subprocess.check_output(
    ['git', 'diff', SOURCE, head, '--name-only', '--'] + scope, text=True
).splitlines()
assert changed == [], changed
print(json.dumps({
    'delivered_commit': head, 'source_commit': SOURCE,
    'git_payloads_verified': len(manifest['files']),
    'document_bindings_verified': len(documents['documents']),
    'checkpoint_git_payloads_verified': len(checkpoint['files']),
    'application_diff': changed, 'status': 'PASS',
}))
