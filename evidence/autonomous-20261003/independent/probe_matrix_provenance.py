"""Independent negative inputs for the documentation evidence binding gates."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import runpy
import subprocess
from unittest.mock import patch

root=Path.cwd()
docs=root/'docs/acceptance'
paths=[docs/name for name in ('COMPLETION_MATRIX.json','COMPLETION_MATRIX.md','FINAL_REPORT.md',
       'DELIVERY_STATE.json','EVIDENCE_RETENTION.md','FINDINGS_AND_FIXES.md')]
def hashes():return {str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
before=hashes()
spec=importlib.util.spec_from_file_location('matrix_probe',docs/'validate_matrix.py')
validator=importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)
validator.REPORT=copy.deepcopy(validator.REPORT)
current=validator.REPORT['tested_commit_sha']
row=next(row for row in validator.REPORT['targets'] if row['id']=='C11.2')
row['commands']=[command for command in row['commands'] if command.get('tested_commit_sha') != current]
assert any(command.get('tracked_source_dirty') is True for command in row['commands'])
assert any(command.get('tracked_source_dirty') is False for command in row['commands'])
try:
    validator.main()
except ValueError as error:
    assert str(error)=='C11.2: no frozen validation alongside experiment',str(error)
    stale_clean_rejected=True
else:
    raise AssertionError('Historical clean receipts incorrectly supported a current dirty experiment')

original_read=Path.read_text
def old_matrix(path,*args,**kwargs):
    text=original_read(path,*args,**kwargs)
    if path.resolve()==(docs/'COMPLETION_MATRIX.json').resolve():
        value=json.loads(text)
        value['tested_commit_sha']='a68b11b39c2c2ed41e18d9001b90b66dcb652ba4'
        return json.dumps(value)
    return text
try:
    with patch.object(Path,'read_text',old_matrix):
        runpy.run_path(str(root/'var/finalize_autonomous_docs.py'),run_name='__main__')
except AssertionError:
    stale_matrix_rejected=True
else:
    raise AssertionError('Old matrix accepted by current-CI final report generator')
assert before==hashes(),'Negative test modified delivered documents'
report={'tested_commit_sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'scope':'Documentation gate counterexamples only; no mutation of source evidence or claims about functional acceptance',
        'documentation_edits_uncommitted_at_test':True,
        'gate_file_hashes':{str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest()
             for path in (docs/'validate_matrix.py',root/'var/finalize_autonomous_docs.py')},
        'old_clean_receipt_only_rejected':stale_clean_rejected,'old_matrix_new_ci_rejected':stale_matrix_rejected,
        'reports_unmodified':True,'unchanged_report_hashes':before}
output=root/'evidence/autonomous-20261003/independent/methodology-provenance-counterexamples.json'
output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'old_clean_receipt_only_rejected':True,'old_matrix_new_ci_rejected':True,'reports_unmodified':True}))
