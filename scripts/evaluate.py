"""Frozen synthetic contract evaluation, with an independent Python diff oracle.

No security-generalization or human-decision claims can be made from this set.
Classification-only baselines never disable the actual execution safety layer.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import statistics
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from pydantic import ValidationError
from airlock.common import AirlockError,canonical
from airlock.contracts import ToolRequest
from airlock.policy import Policy
from airlock.target import TargetStore,initialize_target

CLASSES=['pass','need_approval','block']


def oracle(path:Path,request:ToolRequest) -> list[dict]:
    """Independent dictionary transformation, not production SQL/compiler/diff."""
    with sqlite3.connect(path) as conn:
        conn.row_factory=sqlite3.Row
        customers=[dict(row) for row in conn.execute('SELECT * FROM customers ORDER BY id')]
        notes=[dict(row) for row in conn.execute('SELECT * FROM customer_notes ORDER BY id')]
    def matches(row):
        if row['project']!='demo':return False
        for condition in request.filters:
            a,b=row[condition.field],condition.value
            valid={'eq':lambda:a==b,'in':lambda:a in b,'lt':lambda:a<b,'lte':lambda:a<=b,'gt':lambda:a>b,'gte':lambda:a>=b}[condition.op]()
            if not valid:return False
        return True
    selected=[row for row in customers if matches(row)]
    changes=[]
    if request.tool=='db.update_rows':
        for row in selected:
            after=copy.deepcopy(row);after.update(request.values);after['version']+=1
            changes.append({'table':'customers','id':row['id'],'before':row,'after':after,'kind':'update','origin':'direct'})
    elif request.tool=='db.delete_rows':
        selected_ids={row['id'] for row in selected}
        for table,rows,origin in [('customers',selected,'direct'),('customer_notes',[row for row in notes if row['customer_id'] in selected_ids],'cascade')]:
            changes.extend({'table':table,'id':row['id'],'before':row,'after':None,'kind':'delete','origin':origin} for row in rows)
    return sorted(changes,key=lambda item:(item['table'],item['id']))


def summarize(rows,key):
    matrix={truth:{guess:0 for guess in CLASSES} for truth in CLASSES}
    for row in rows:matrix[row['expected']][row[key]]+=1
    positives=sum(row['expected']!='pass' for row in rows);negatives=len(rows)-positives
    blocks=sum(row['expected']=='block' for row in rows)
    unsafe=sum(row['expected']!='pass' and row[key]=='pass' for row in rows)
    false_alarm=sum(row['expected']=='pass' and row[key]!='pass' for row in rows)
    prohibited_to_ask=sum(row['expected']=='block' and row[key]=='need_approval' for row in rows)
    return {'confusion_matrix':matrix,'correct':sum(row['expected']==row[key] for row in rows),'total':len(rows),
        'dangerous_direct_pass':{'numerator':unsafe,'denominator':positives,'rate':unsafe/positives if positives else None},
        'false_positive':{'numerator':false_alarm,'denominator':negatives,'rate':false_alarm/negatives if negatives else None},
        'prohibited_misrouted_to_approval':{'numerator':prohibited_to_ask,'denominator':blocks,'rate':prohibited_to_ask/blocks if blocks else None}}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=ROOT/'Evidence/evaluation.json')
    args=parser.parse_args()
    data=(ROOT/'benchmark/cases.jsonl').read_bytes();manifest=json.loads((ROOT/'benchmark/manifest.json').read_text())
    assert hashlib.sha256(data).hexdigest()==manifest['sha256'],'Frozen dataset changed: review and version manifest explicitly'
    cases=[json.loads(line) for line in data.splitlines()];assert len(cases)==manifest['cases']
    families={}
    for case in cases:
        if case['family'] in families:assert families[case['family']]==case['split'],'Family leakage'
        families[case['family']]=case['split']
    rows=[];policy=Policy();latencies=[]
    with tempfile.TemporaryDirectory(prefix='airlock-eval-') as tmp:
        for case in cases:
            path=Path(tmp)/(case['id']+'.db');initialize_target(path)
            if case.get('setup'):
                sql={'trigger':'CREATE TRIGGER unexpected AFTER UPDATE ON customers BEGIN SELECT 1; END',
                     'view':'CREATE VIEW unexpected AS SELECT id FROM customers'}[case['setup']]
                with sqlite3.connect(path) as conn:conn.execute(sql)
            before=hashlib.sha256(path.read_bytes()).hexdigest()
            result={'id':case['id'],'family':case['family'],'split':case['split'],'expected':case['expected'],
                    'preview_complete':False,'oracle_matches':None}
            start=time.perf_counter()
            try:
                request=ToolRequest.model_validate(case['request'])
                # Independent conservative metadata-only baseline: never used to execute.
                baseline='pass' if request.tool=='db.query_rows' else 'block' if request.tool=='db.delete_rows' and not request.filters else 'need_approval'
                facts=TargetStore(path,'evaluation-only-'+'s'*40).preview(request.model_dump(mode='json'),'demo')
                guess,reason=policy.decide(request,facts)
                expected_diff=oracle(path,request)
                actual=sorted(facts['changes'],key=lambda item:(item['table'],item['id']))
                result.update(preview_complete=True,oracle_matches=actual==expected_diff,affected_records=facts['total_changed'])
                assert result['oracle_matches'],case['id']+' independent oracle mismatch'
            except ValidationError:guess,reason,baseline='block','UNSUPPORTED_CONTRACT','block'
            except AirlockError as exc:guess,reason='block',exc.code
            duration=(time.perf_counter()-start)*1000
            assert hashlib.sha256(path.read_bytes()).hexdigest()==before,'Preview touched original target: '+case['id']
            result.update(predicted=guess,baseline=baseline,reason=reason,elapsed_ms=round(duration,3),target_unchanged=True)
            rows.append(result)
            if result['preview_complete']:latencies.append(duration)
    supported=[row for row in rows if row['preview_complete']]
    sorted_ms=sorted(latencies)
    report={'status':'PASS' if all(row['expected']==row['predicted'] for row in rows) else 'FAIL',
        'scope':'synthetic fixed-policy contract regression; no independent security or human-study generalization',
        'source_manifest_sha256':manifest['sha256'],'environment':{'python':platform.python_version(),
            'sqlite':sqlite3.sqlite_version,'platform':platform.platform(),'cpu_count':os.cpu_count(),
            'business_fixture':'1206 demo customers, 3 other-scope customers, 12 notes','concurrency':1,
            'timing':'one independent target per case; process warm, snapshot/oracle plus policy wall time; not gateway p95'},
        'combined':summarize(rows,'predicted'),'static_baseline':summarize(rows,'baseline'),
        'splits':{split:summarize([r for r in rows if r['split']==split],'predicted') for split in ['dev','test']},
        'preview_coverage':{'complete':len(supported),'all_submissions':len(rows),
            'rate':len(supported)/len(rows),'unsupported_remain_in_denominator':True},
        'independent_oracle':{'matches':sum(r['oracle_matches'] is True for r in rows),'complete_previews':len(supported)},
        'supported_case_ms':{'n':len(latencies),'median':round(statistics.median(latencies),3),
            'p95_nearest_rank':round(sorted_ms[max(0,__import__('math').ceil(.95*len(sorted_ms))-1)],3)},
        'real_model_ablation':'NOT_TESTABLE: no API key supplied',
        'human_ab_experiment':'NOT_TESTABLE: no participants or observations',
        'rows':rows}
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ('status','combined','static_baseline','preview_coverage','independent_oracle','supported_case_ms')},ensure_ascii=False,indent=2))
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
