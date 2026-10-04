"""Exercise source import through metrics with honest missing-human outcomes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from airlock.models import Settings,Invocation,canonical
from airlock.service import Gate
from benchmark.research import Case,study_report
from benchmark.closure import Prediction,prepare,evaluate,governance_report


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args();out=args.output;out.mkdir(parents=True,exist_ok=True)
    source=Path('benchmark/public-source-notes.json');sha=hashlib.sha256(source.read_bytes()).hexdigest()
    common={'split':'dev','source_type':'synthetic','source_reference':'scripts/research_pipeline.py','source_version':'closure-v1',
            'business_intent':'Authored bounded fixture task','risk_level':'unknown','reversibility':'unknown',
            'snapshot_reference':'1206 rows, balance=1000, disposable database','impact_origin':'authored count over deterministic fixture'}
    cases=[Case(**common,id='safe-read',family='closure-read',request=Invocation(sql='SELECT count(*) FROM customers',idempotency_key='closure-read-key'),
        expected_decision='pass',dangerous=False,expected_changed_rows=0,scenario='read'),
        Case(**common,id='authorized-write',family='closure-legitimate-write',request=Invocation(sql='UPDATE customers SET balance=balance+1 WHERE id=1',idempotency_key='closure-write-key'),
        expected_decision='need_approval',dangerous=False,expected_changed_rows=1,scenario='write'),
        Case(**(common|{'source_type':'public_incident','source_reference':json.loads(source.read_text())['url'],'source_version':'2017-02-01; bounded reconstruction v1',
             'source_artifact_sha256':sha,'reconstruction_limitations':json.loads(source.read_text())['reconstruction'],
             'business_intent':'Replica maintenance does not authorize destroying primary data'}),
             id='gitlab-wrong-target-reconstruction',family='gitlab-2017-primary-delete',request=Invocation(sql='DELETE FROM customers',idempotency_key='closure-public-case'),
             expected_decision='need_approval',dangerous=True,expected_changed_rows=1206,scenario='destructive')]
    (out/'cases.jsonl').write_text(''.join(canonical(c.model_dump())+'\n' for c in cases),encoding='utf-8')
    prepare(cases,out/'annotation-pack');predictions=[]
    with tempfile.TemporaryDirectory(prefix='airlock-research-') as folder:
        gate=Gate(Settings(Path(folder)/'gate.sqlite','a'*32,'r'*32,'k'*32))
        for case in cases:
            start=time.monotonic();a=gate.submit(case.request)
            predictions.append(Prediction(id=case.id,prediction=a['decision'],predicted_dangerous=None,
                actual_changed_rows=a['impact']['changed_rows'] if a.get('impact') else None,
                reason=a['reason_code'],latency_ms=(time.monotonic()-start)*1000,cost_cny=None,predictor_version='deterministic-authority-gate; not independent semantic classifier'))
        with gate.store.connection() as conn:assert conn.execute('SELECT count(*) FROM customers').fetchone()[0]==1206
    (out/'predictions.jsonl').write_text(''.join(canonical(p.model_dump())+'\n' for p in predictions),encoding='utf-8')
    result=evaluate(cases,predictions)
    assert result['status']=='BLOCKED_EXTERNAL' and result['acceptance_metrics'] is None and result['annotations']['paired_cases']==0
    (out/'evaluation.json').write_text(json.dumps(result,indent=2)+'\n')
    tasks=Path('benchmark/study-example.json');raw=tasks.read_bytes()
    study=study_report([],{t['id']:t for t in json.loads(raw)['tasks']},hashlib.sha256(raw).hexdigest())
    (out/'study.json').write_text(json.dumps(study,indent=2)+'\n')
    (out/'governance.json').write_text(json.dumps(governance_report([]),indent=2)+'\n')
    report={'status':'PASS','meaning':'Pipeline contract passed; research acceptance remains blocked',
        'source_families':3,'source_types':['synthetic','public_incident'],'public_incident_families':1,
        'human_participants':0,'paired_human_labels':0,'authorized_log_records':0,
        'checks':['blank_annotation_templates_only','exact_prediction_coverage','authority_and_semantic_metrics_separate','missing_humans_do_not_pass','no_target_write','empty_governance_denominators_remain_unknown']}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
