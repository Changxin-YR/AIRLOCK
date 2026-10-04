"""Replay failed DEV provider contracts; retain the original experiment unchanged."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from airlock.semantic import SemanticAdvisor
from airlock.models import Settings,Invocation
from airlock.service import Gate
from benchmark.evaluate import load
from airlock.sql import classify
import sqlite3


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--provider-config',type=Path,required=True);p.add_argument('--ledger',type=Path,required=True)
    p.add_argument('--original-dev-report',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    prior=json.loads(a.original_dev_report.read_text(encoding='utf-8'))
    if prior['split']!='dev':raise ValueError('diagnostics never tune on test')
    cases,checksum=load('dev',True);by_id={c['id']:c for c in cases};advisor=SemanticAdvisor(a.provider_config,a.ledger);rows=[]
    with tempfile.TemporaryDirectory() as folder:
        for arm,report in prior['arms'].items():
            for row in report['rows']:
                if row.get('provider_status')!='error':continue
                call=Invocation.model_validate(by_id[row['id']]['request']);gate=Gate(Settings(Path(folder)/(str(len(rows))+'.db'),'a'*32,'r'*32,'k'*32))
                with gate.store.connection() as conn:
                    try:static='need_approval' if classify(conn,call) else 'pass'
                    except (ValueError,sqlite3.Error,OverflowError):static='block'
                preview=gate.submit(call)
                context={'principal':'experiment:offline','request':call.model_dump(exclude={'idempotency_key'}),'experiment_arm':arm,'corpus_sha256':checksum}
                if arm!='pure_llm':context['deterministic_decision']=static
                if arm=='hybrid_with_preview':context['preview']=preview['impact']
                result=advisor.assess(context);rows.append({'id':row['id'],'arm':arm,'original_error':row['semantic'],'diagnostic':result})
                a.output.write_text(json.dumps({'scope':'diagnostic replay of DEV failures, original predictions retained','rows':rows,'ledger':advisor.ledger_summary()},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'replayed':len(rows),'schema_errors':[r['diagnostic'].get('schema_errors') for r in rows],'ledger':advisor.ledger_summary()},indent=2))
