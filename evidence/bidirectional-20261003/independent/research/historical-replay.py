import hashlib,json
from pathlib import Path
from benchmark.research import study_report,read_json,read_jsonl,Case
from benchmark.closure import evaluate,Prediction
root=Path('var/bidirectional-20261003/research');base=Path('evidence/single-person-20261003/ci/verified')
session=base/'study-automation.json';original=read_json(base/'study-analysis.json')
replayed=study_report([read_json(session)])
extra=replayed.pop('comprehension_verification')
assert original==replayed
pipeline=base/'research-pipeline';cases=read_jsonl(pipeline/'cases.jsonl',Case);predictions=read_jsonl(pipeline/'predictions.jsonl',Prediction)
old_eval=read_json(pipeline/'evaluation.json');new_eval=evaluate(cases,predictions)
assert old_eval==new_eval
result={'status':'PASS','checks':['archived_automation_study_metrics_identical_excluding_new_provenance_field','archived_frozen_corpus_predictions_evaluation_identical'],'study_provenance_added':extra,'human_participants':new_eval['annotations']['paired_cases'],'formal_acceptance_metrics':new_eval['acceptance_metrics'],'source_files':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [session,base/'study-analysis.json',pipeline/'cases.jsonl',pipeline/'predictions.jsonl',pipeline/'evaluation.json']},'history_rewritten':False}
(root/'historical-replay.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
