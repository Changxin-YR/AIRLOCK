"""Read-only checks for the engineering checkpoint and original execution receipts."""
from pathlib import Path
import hashlib
import io
import json
import re
import subprocess
import zipfile

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
record = json.loads((BASE / 'ARCHIVE.json').read_text(encoding='utf-8'))
bundle = ROOT / record['bundle']['path']
raw = bundle.read_bytes()
assert len(raw) == record['bundle']['bytes']
assert hashlib.sha256(raw).hexdigest() == record['bundle']['sha256']
with zipfile.ZipFile(io.BytesIO(raw)) as archive:
    assert len(archive.namelist()) == len(set(archive.namelist()))
    contents = json.loads(archive.read('CONTENTS.json'))
    assert contents == {key: value for key, value in record.items() if key != 'bundle'}
    assert set(archive.namelist()) == set(record['files']) | {'CONTENTS.json'}
    for name, expected in record['files'].items():
        data = archive.read(name)
        assert len(data) == expected['bytes'], name
        assert hashlib.sha256(data).hexdigest() == expected['sha256'], name
        if name.startswith('snapshot/'):
            actual = subprocess.check_output(['git', 'show', record['baseline_commit'] + ':' + name[9:]], cwd=ROOT)
            assert actual == data, name
    with zipfile.ZipFile(io.BytesIO(archive.read('source-699adbd.zip'))) as source:
        assert source.comment.decode() == record['baseline_commit']
        assert all(not name.startswith(('var/', '.git/', 'evidence/')) for name in source.namelist())
    with zipfile.ZipFile(io.BytesIO(archive.read('acceptance-533726a.zip'))) as ci:
        manifest = json.loads(ci.read('manifest.json'))
        assert manifest['commit'] == record['tested_source_commit']
        for name, expected in manifest['files'].items():
            data = ci.read(name)
            assert len(data) == expected['bytes'], name
            assert hashlib.sha256(data).hexdigest() == expected['sha256'], name

demo = json.loads((BASE / 'comparison.json').read_text())
assert demo['without_gate'] == {'before': 1206, 'after': 0}
assert demo['with_gate']['pending_rows'] == demo['with_gate']['rejected_rows'] == 1206
assert demo['with_gate']['safe_alternative']['result']['rows'] == [{'remaining': 1206}]
assert demo['with_gate']['approved_rows'] == 0
assert demo['audit']['valid'] is True
for name, code in [('comparison.log.status.json', 1), ('comparison-rerun.log.status.json', 0)]:
    receipt = json.loads((BASE / name).read_text())
    assert receipt['exit_code'] == code
    assert receipt['tested_commit_sha'] == record['baseline_commit']
    assert receipt['tracked_source_dirty'] is False

provenance = json.loads((BASE / 'PROVENANCE.json').read_text())
previous = json.loads((BASE / 'PREVIOUS_MANIFEST.json').read_text())
historical = {provenance['evidence_root'] + '/' + name: value for name, value in previous['files'].items()}
historical.update(previous['documents'])
for name, expected in historical.items():
    data = subprocess.check_output(['git', 'show', provenance['commit'] + ':' + name], cwd=ROOT)
    assert len(data) == expected['bytes'], name
    assert hashlib.sha256(data).hexdigest() == expected['sha256'], name
for path in BASE.glob('comparison*'):
    assert path.read_bytes() == subprocess.check_output(
        ['git', 'show', provenance['commit'] + ':' + provenance['evidence_root'] + '/' + path.name], cwd=ROOT)

links_checked = 0
for path in [ROOT / 'docs/PLAN.md', BASE / 'README.md', ROOT / 'README.md']:
    for target in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
        if target.startswith(('http:', 'https:', '#')):
            continue
        file = target.split('#', 1)[0]
        assert (path.parent / file).is_file(), (path, target)
        links_checked += 1

print(json.dumps({'status': 'PASS', 'baseline_commit': record['baseline_commit'],
                  'bundle_payloads_verified': len(record['files']), 'ci_payloads_verified': len(manifest['files']),
                  'local_links_checked': links_checked, 'historical_git_objects_verified': len(historical),
                  'demo': 'disposable synthetic fixture; actual effect/state/audit checked',
                  'historical_full_ci_is_not_a_new_full_test_run': True}, ensure_ascii=False))
