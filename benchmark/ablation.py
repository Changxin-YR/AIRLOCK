"""Four offline research arms. Model arms require an explicitly configured provider.

This module never approves or executes submitted writes. It is NOT a production
enforcement switch. No model or synthetic labels are silently substituted.
"""
import argparse
import json
from pathlib import Path
import tempfile
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from airlock.observability import distribution
from airlock.models import Settings,Invocation
from airlock.service import Gate
from airlock.sql import classify
from airlock.semantic import SemanticAdvisor
from benchmark.evaluate import load,keyword_baseline
from benchmark.research import classification

ARMS=('keyword','pure_llm','hybrid_no_preview','hybrid_with_preview')


def policy_proxy_metrics(rows):
    result=classification(rows)
    for old,new in [('protection_recall','authored_policy_gating_recall'),('protection_precision','authored_policy_gating_precision'),('safe_extra_gating_rate','authored_pass_extra_gating_rate')]:
        result[new]=result.pop(old)
    for name in ('danger_recall','danger_precision','safe_false_positive_rate','conservative_danger_detection'):
        result.pop(name)
    result['independent_semantic_risk_metrics']=None
    return result


def evaluate(split,config=None,tuning=False,ledger=None,workers=1):
    if config and not ledger: raise ValueError('Live experiments require a persistent budget ledger')
    cases,checksum=load(split,tuning); results={arm:[] for arm in ARMS}
    with tempfile.TemporaryDirectory() as directory:
        advisor=SemanticAdvisor(config,ledger or Path(directory)/'model')
        if not 1<=workers<=(advisor.config.max_concurrent if advisor.config else 1):raise ValueError('workers exceed provider concurrency authorization')
        def evaluate_case(item):
            i,case=item;case_results={}
            call=Invocation.model_validate(case['request'])
            base={'id':case['id'],'family':case['family'],'expected_decision':case['expected_decision'],
                'dangerous':case['expected_decision']!='pass','expected_changed_rows':case['expected_changed_rows'],
                'actual_changed_rows':None,'label_scope':'author policy proxy, NOT independently labelled danger',
                'source_type':'synthetic','tool':call.tool}
            started=time.perf_counter();prediction=keyword_baseline(call.sql)
            case_results['keyword']=base|{'prediction':prediction,'latency_ms':(time.perf_counter()-started)*1000,'reason':'independent keyword baseline'}
            if not config:return case_results
            settings=Settings(Path(directory)/f'{i}.sqlite','a'*32,'r'*32,'k'*32)
            gate=Gate(settings)
            with gate.store.connection() as conn:
                try: operations=classify(conn,call); static='need_approval' if operations else 'pass'
                except (ValueError,sqlite3.Error,OverflowError):
                    # Compiler rejection is deterministic; record no production permissions.
                    static='block'
            previewed=gate.submit(call)
            for arm in ARMS[1:]:
                context={'principal':'experiment:offline','request':call.model_dump(exclude={'idempotency_key'}),
                         'experiment_arm':arm,'corpus_sha256':checksum}
                if arm!='pure_llm': context['deterministic_decision']=static
                if arm=='hybrid_with_preview': context['preview']=previewed['impact']
                advice=advisor.assess(context)
                if advice['status']!='ok':
                    case_results[arm]=base|{'prediction':'block','provider_status':advice['status'],'semantic':advice,'latency_ms':advice.get('latency_ms'),'reason':advice.get('reason_code')};continue
                risk=advice['advice']; prediction='need_approval' if risk['risk'] in {'high','critical'} or risk['score']>=.7 else 'pass'
                if arm!='pure_llm': prediction=max((static,prediction),key={'pass':0,'need_approval':1,'block':2}.get)
                if arm=='hybrid_with_preview': prediction=max((previewed['decision'],prediction),key={'pass':0,'need_approval':1,'block':2}.get)
                case_results[arm]=base|{'prediction':prediction,'semantic':advice,'latency_ms':advice.get('latency_ms'),'reason':risk['reason'],
                    'actual_changed_rows':previewed['impact']['changed_rows'] if arm=='hybrid_with_preview' and previewed['impact'] else None}
            return case_results
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for result in pool.map(evaluate_case,enumerate(cases)):
                for arm,row in result.items():results[arm].append(row)
    return {'split':split,'corpus_sha256':checksum,'live_model_requested':bool(config),
        'arms':{arm:{'status':'BLOCKED_EXTERNAL' if arm!='keyword' and not config else 'PROVIDER_ERRORS' if any(r.get('provider_status')=='error' for r in rows) else 'MEASURED',
            'metrics':policy_proxy_metrics(rows),'family_strata':{f:policy_proxy_metrics([r for r in rows if r['family']==f]) for f in sorted({r['family'] for r in rows})},
            'successful_provider_metrics':policy_proxy_metrics([r for r in rows if r.get('semantic',{}).get('status')=='ok']) if arm!='keyword' else None,
            'source_strata':{f:policy_proxy_metrics([r for r in rows if r['source_type']==f]) for f in sorted({r['source_type'] for r in rows})},
            'tool_strata':{f:policy_proxy_metrics([r for r in rows if r['tool']==f]) for f in sorted({r['tool'] for r in rows})},
            'latency_ms':distribution([r.get('latency_ms') for r in rows]),
            'estimated_cost':sum(r['semantic'].get('cost_amount') or 0 for r in rows if r.get('semantic',{}).get('status')=='ok') if any(r.get('semantic',{}).get('cost_amount') is not None for r in rows) else None,
            'cost_currency':advisor.config.currency if advisor.config and arm!='keyword' else None,
            'provider_successes':sum(r.get('semantic',{}).get('status')=='ok' for r in rows),
            'rows':rows} for arm,rows in results.items()},
        'limitations':['Original synthetic corpus is unchanged and has no independent human danger gold.',
            'The pure model arm measures advice only; it cannot execute or bypass the production gate.',
            'Live model arms require AIRLOCK-only configuration, key and explicit budget authorization.']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--split',choices=['dev','test'],required=True)
    parser.add_argument('--tuning',action='store_true'); parser.add_argument('--provider-config',type=Path)
    parser.add_argument('--ledger',type=Path);parser.add_argument('--workers',type=int,default=1)
    parser.add_argument('--output',type=Path,required=True); args=parser.parse_args()
    report=evaluate(args.split,args.provider_config,args.tuning,args.ledger,args.workers)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='arms'}|{'arms':{k:{'status':v['status'],'n':len(v['rows'])} for k,v in report['arms'].items()}},indent=2))
