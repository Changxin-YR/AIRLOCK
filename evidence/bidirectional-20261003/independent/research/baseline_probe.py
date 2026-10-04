import hashlib,json,subprocess
from pathlib import Path
from benchmark.research import Annotation,study_report,read_jsonl
from benchmark.closure import governance_report
root=Path('var/bidirectional-20261003/research')
files=['benchmark/research.py','benchmark/closure.py','benchmark/pilot.py','benchmark/worklog.py']
meta={'tested_commit_sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'source_hashes':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in files},'dirty':subprocess.check_output(['git','status','--porcelain'],text=True),'synthetic_only':True}
for p in files:(root/('baseline-'+Path(p).name)).write_bytes(Path(p).read_bytes())
record=dict(case_id='case1',annotator_id='test-person',human=1,independent=1,dangerous=False,decision='pass',rationale='synthetic counterexample')
annotation=Annotation.model_validate(record)
gold={'one':{'gold':'approve'},'two':{'gold':'approve'}}
session=dict(kind='airlock-study-v1',participant_id='test-person',source='human',consent=True,responses=[dict(case_id=key,arm=arm,choice='approve',correct=True,visible_ms=2000,comprehension_correct=True) for key,arm in [('one','A'),('two','B')]])
study=study_report([session],gold)
base=dict(id='a',source='authorized_log',authorized=True,authorization_reference='synthetic-counterexample',participant_id='fixture-user',date='2026-99-99',task_id='one',baseline_approvals=0,actual_approvals=0,eligible_requests=0,displayed_groups=0,readonly_pass=5,duplicates_suppressed=0,batch_reviewed=0,incorrect_decisions=0,same_task_quality=True)
gov=governance_report([base])
line=json.dumps(record).replace('"human": 1','"human": false, "human": true').replace('"independent": 1','"independent": true')
(root/'duplicate-declaration.jsonl').write_text(line+'\n',encoding='utf-8')
duplicate=read_jsonl(root/'duplicate-declaration.jsonl',Annotation)
report=dict(meta,annotation_numeric_human_accepted=annotation.model_dump(),duplicate_json_human_last_wins=duplicate[0].human,unchecked_comprehension=study['comprehension_correct'],study_gold_verification=study['gold_verification'],invalid_day_active_user_days=gov['active_user_days'])
(root/'baseline.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,indent=2))
