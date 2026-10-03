"""Verify delivered Git objects and document bindings from the AIRLOCK checkout cwd."""
import hashlib,json,subprocess
from pathlib import Path
BASE='evidence/closure2-20261003'
head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
def blob(name):return subprocess.check_output(['git','show',f'{head}:{name}'])
m=json.loads(blob(BASE+'/ARCHIVE_MANIFEST.json'));d=json.loads(blob(BASE+'/DOCUMENT_BINDINGS.json'))
items={BASE+'/'+p:v for p,v in m['files'].items()};items.update(d['documents'])
for name,entry in items.items():
    raw=blob(name)
    assert len(raw)==entry['bytes'] and hashlib.sha256(raw).hexdigest()==entry['sha256'],name
scope=['airlock','frontend','configs','policies','benchmark','scripts','tests','tests-js','requirements.txt','requirements-dev.txt','requirements-archive.txt','pyproject.toml','package.json','package-lock.json','Dockerfile','compose.yaml','.github','docs/acceptance/build_matrix.py','docs/acceptance/validate_matrix.py']
changed=subprocess.check_output(['git','diff','533726aa72eeeb71d5c28d81ac84ad7b1a23dd3c',head,'--name-only','--']+scope,text=True).splitlines()
assert changed==[],changed
print(json.dumps({'delivered_commit':head,'source_commit':m['tested_commit_sha'],'git_payloads_verified':len(m['files']),'document_bindings_verified':len(d['documents']),'application_diff':changed,'status':'PASS'}))
