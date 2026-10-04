import copy,contextlib,hashlib,io,json,subprocess,types
from pathlib import Path
root=Path.cwd()
sha='4e512df4c65e9b94b7f210ed5483e612efb5eec1'
p='docs/acceptance/validate_matrix.py'
raw=subprocess.check_output(['git','show',sha+':'+p])
m=types.ModuleType('baseline_matrix');m.__file__=str(root/p)
exec(compile(raw,str(root/p),'exec'),m.__dict__)
def check(name,change):
 original=m.REPORT;m.REPORT=copy.deepcopy(original);change(m.REPORT)
 try:
  with contextlib.redirect_stdout(io.StringIO()):m.main()
  result={'probe':name,'accepted':True}
 except Exception as e:result={'probe':name,'accepted':False,'error':str(e)}
 finally:m.REPORT=original
 return result
results=[check('unchanged_positive_control',lambda r:None),check('inflated_PASS_total',lambda r:r['counts']['verification'].update(PASS=126)),check('all_goals_claim_without_closure',lambda r:r.update(original_goals_all_satisfied=True)),check('row_SHA_replaced',lambda r:r['targets'][0].update(tested_commit_sha='0'*40)),check('PASS_without_process_receipt',lambda r:r['targets'][0].update(commands=[{'command':['unexecuted','self-asserted-success']}],exit_codes=[{'exit_code':0}],test_ids=[])),check('parent_children_evidence_removed',lambda r:next(x for x in r['targets'] if x['id']=='C1').update(commands=[{'child_id':'C1.1','commands':[]}]))]
print(json.dumps({'baseline_commit':sha,'validator_sha256':hashlib.sha256(raw).hexdigest(),'probes':results,'meaning':'accepted invalid variants expose ledger validation gaps; not application side effects'},ensure_ascii=False,indent=2))
