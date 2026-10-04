import ast
import hashlib
import json
from pathlib import Path
import subprocess

root = Path.cwd()
base = root / 'var/closure2-20261003/identity'
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
old = subprocess.check_output(['git', 'show', '758202b4631c5f530e48ab07aa07cd90bfbe58e0:airlock/service.py'])
saved = (base / 'service-baseline.py').read_bytes()
original_method = next(item for item in ast.parse(old).body if isinstance(item, ast.ClassDef) and item.name == 'Gate')
original_method = next(item for item in original_method.body if isinstance(item, ast.FunctionDef) and item.name == 'audit_events')
saved_method = next(item for item in ast.parse(saved).body if isinstance(item, ast.ClassDef) and item.name == 'Gate')
saved_method = next(item for item in saved_method.body if isinstance(item, ast.FunctionDef) and item.name == 'audit_events')

def receipt(name):
    value = json.loads((base / (name + '.log.status.json')).read_text())
    return {'log': name + '.log', 'receipt': name + '.log.status.json',
            'command': value['command'], 'exit_code': value['exit_code'],
            'tested_commit_sha': value['tested_commit_sha'],
            'tracked_source_dirty': value['tracked_source_dirty']}

result = {
    'status': 'PASS', 'declared_base_commit': '758202b4631c5f530e48ab07aa07cd90bfbe58e0',
    'current_head_at_report': head, 'tested_working_tree_modified': True,
    'owned_source_changes': ['airlock/service.py:Gate.audit_events', 'tests/test_identity_boundaries.py'],
    'baseline_audit_method_matches_base_AST': ast.dump(original_method) == ast.dump(saved_method),
    'findings': [{
        'id': 'identity-audit-pagination-starvation', 'severity': 'P1', 'status': 'FIXED',
        'trigger': '9 valid operator cache invalidations at max_actions=2, followed by a visible pending action',
        'baseline': '/v1/audit and /v1/audit/export returned empty items and nonadvancing next_after=0',
        'fix': 'Single SQLite read cursor joins action documents; applies current reviewer scope before page limit; no fixed raw event cutoff.',
        'validation': 'Same two formerly failing API cases pass; separate pagination/action filter/revocation tests preserve business rows, pending states and original audit chain.'
    }],
    'runs': [receipt(name) for name in ['baseline', 'repaired', 'final-targeted',
        'governance-cross', 'governance-cross-final', 'governance-cross-complete', 'governance-cross-complete-final']],
    'counts': {'baseline': {'failed': 2, 'passed': 4}, 'repaired_related': {'passed': 61},
               'final_related': {'passed': 64}, 'new_committed_boundary_cases': 9,
               'final_independent_governance_cases': 5},
    'cross_governance': {
        'status': 'PASS', 'code_changed_by_reviewer': False,
        'scope': ['first-member critical/resource/account revocation at authority snapshot',
                  'rejection allowed without critical approval authority',
                  'real local HTTP upstream receives zero effects after critical revocation'],
        'fixture_errors_preserved': [
            'governance-cross.log: 3 failures from too-short synthetic idempotency key, not an application regression',
            'governance-cross-complete.log: 1 failure from wrong helper import path, not an application regression'],
        'cross_author_audit_result': '../cross-identity/RESULT.json'
    },
    'no_new_defect_found_in': ['OIDC issuer/audience/JTI and subject/account revocation',
        'Code+PKCE nonce/client/hash binding and private output',
        'malformed/deep unsigned JWT and nonfinite numeric-date rejection',
        'redacted export free-text omission and scoped action filtering'],
    'limitations': [
        'All identities, credentials, data and HTTP peers are synthetic isolated fixtures.',
        'No live IdP/MFA, real human records, representative production logs or paid model calls.',
        'Per-read / per-member authority snapshots do not claim cross-process linearizable configuration revocation.',
        'The full frozen-commit CI and parent archive fixes remain the parent task responsibility.',
        'Source is a modified working tree; the tested_commit_sha in receipts is not falsely presented as a clean frozen test.'],
    'upstream_warning': 'StarletteDeprecationWarning: httpx with starlette.testclient deprecated; retained in logs.'
}
(base / 'RESULT.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
files = {}
for file in sorted(base.rglob('*')):
    if not file.is_file() or '__pycache__' in file.parts or file.name == 'MANIFEST.json':
        continue
    raw = file.read_bytes()
    files[file.relative_to(base).as_posix()] = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
(base / 'MANIFEST.json').write_text(json.dumps({'files': files}, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'status': result['status'], 'files': len(files), 'baseline_method_matches': result['baseline_audit_method_matches_base_AST']}))
