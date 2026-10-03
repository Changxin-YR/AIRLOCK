"""Independent synthetic follow-up to baseline_probe.py; never real participants."""
import hashlib,json,subprocess,sys,types
from pathlib import Path
from benchmark.research import Annotation,study_report,read_jsonl
from benchmark.closure import governance_report
root=Path('var/bidirectional-20261003/research')
old=types.ModuleType('benchmark.research_saved_baseline');sys.modules[old.__name__]=old
exec(compile((root/'baseline-research.py').read_text(encoding='utf-8'),'baseline-research.py','exec'),old.__dict__)
record=dict(case_id='fixture-a',annotator_id='fixture-person',human=True,independent=True,dangerous=False,decision='pass',rationale='Synthetic test only')
checks=[]
def rejects(label,fn):
    try:fn()
    except (ValueError,TypeError):checks.append(dict(check=label,status='PASS'));return
    raise AssertionError(label)
for field in ('human','independent'):
    assert getattr(old.Annotation.model_validate(record|{field:1}),field) is True
    rejects(field+'_numeric_true',lambda field=field:Annotation.model_validate(record|{field:1}))
assert old.Annotation.model_validate(record|{'rationale':'   '}).rationale=='   '
rejects('blank_formal_rationale',lambda:Annotation.model_validate(record|{'rationale':'   '}))
assert old.read_jsonl(root/'duplicate-declaration.jsonl',old.Annotation)[0].human is True
rejects('duplicate_false_to_true_json',lambda:read_jsonl(root/'duplicate-declaration.jsonl',Annotation))
gold={'a':{'gold':'approve'},'b':{'gold':'reject','check':{'answer':'many'}}}
session=dict(kind='airlock-study-v1',participant_id='fixture-person',source='human',consent=True,responses=[dict(case_id='a',arm='A',choice='approve',correct=False,visible_ms=1500,comprehension_correct=True),dict(case_id='b',arm='B',choice='reject',correct=False,visible_ms=2200,comprehension_correct=True)])
assert old.study_report([session],gold)['comprehension_correct']['denominator']==2
new=study_report([session],gold)
assert new['correct_decisions']['value']==1 and new['comprehension_correct']=={'numerator':0,'denominator':1,'value':0}
assert new['acceptance_metrics'] is None and new['paired_time_delta']['ci95'] is None
checks.append(dict(check='only_actual_comprehension_gold_in_denominator',status='PASS'))
for source in ('model','automation'):
    assert study_report([session|{'source':source}],gold)['human_participants']==0
checks.append(dict(check='model_automation_excluded',status='PASS'))
base=dict(id='a',source='authorized_log',authorized=True,authorization_reference='synthetic-counterexample',participant_id='fixture-user',date='2026-99-99',task_id='one',baseline_approvals=0,actual_approvals=0,eligible_requests=0,displayed_groups=0,readonly_pass=5,duplicates_suppressed=0,batch_reviewed=0,incorrect_decisions=0,same_task_quality=True)
rejects('impossible_active_day',lambda:governance_report([base]))
normal=governance_report([base|{'date':'2026-10-03'}])
assert normal['active_user_days']==1 and normal['quality_matched_approval_reduction']['value'] is None
checks.append(dict(check='valid_day_and_zero_baseline',status='PASS'))
files=['benchmark/research.py','benchmark/closure.py','benchmark/pilot.py','benchmark/worklog.py','tests/test_research_integrity.py']
report={'status':'PASS','checks':checks,'baseline_commit':'4e512df4c65e9b94b7f210ed5483e612efb5eec1','tested_commit_sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'dirty':subprocess.check_output(['git','status','--porcelain'],text=True),'source_hashes':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in files},'synthetic_only':True,'real_participants_observed':0,'paid_model_calls':0,'formal_human_validation':'ENVIRONMENT BLOCKED','scope':'offline research import and analysis integrity; declarations do not authenticate humans'}
(root/'countercheck.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,indent=2))
