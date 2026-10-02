"""Report conditional synthetic-regression metrics, never fabricated model/human data."""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from airlock.models import Invocation, Settings
from airlock.service import Gate
from .generate import HERE, cases, serialize


def load(split: str, tuning: bool=False):
    if tuning and split!='dev':
        raise ValueError('Tuning mode cannot read the test split')
    if split not in {'dev','test'}:
        raise ValueError('Use an explicit dev or test split')
    all_cases=cases()
    checksum=hashlib.sha256(serialize(all_cases).encode()).hexdigest()
    manifest=json.loads((HERE/'manifest.json').read_text())
    if manifest['sha256']!=checksum:
        raise ValueError('Frozen corpus checksum mismatch')
    return [row for row in all_cases if row['split']==split],checksum


def keyword_baseline(sql: str) -> str:
    # Independent naive filter, not Airlock with features disabled; not a real competing product.
    if re.search(r'\b(DROP|ALTER|CREATE|ATTACH|PRAGMA|VACUUM)\b',sql,re.I):
        return 'block'
    if re.search(r'\b(DELETE|UPDATE|INSERT|REPLACE)\b',sql,re.I):
        return 'need_approval'
    return 'pass'


def metrics(rows, key):
    positive=[r for r in rows if r['expected']!='pass']
    negative=[r for r in rows if r['expected']=='pass']
    writes=[r for r in rows if r['expected']=='need_approval']
    return {'exact_accuracy':sum(r[key]==r['expected'] for r in rows)/len(rows),
        'policy_gating_recall':sum(r[key]!='pass' for r in positive)/len(positive),
        'supported_read_fpr':sum(r[key]!='pass' for r in negative)/len(negative),
        'supported_write_interception':sum(r[key]!='pass' for r in writes)/len(writes),
        'denominators':{'all':len(rows),'requires_gate':len(positive),'supported_reads':len(negative),'supported_writes':len(writes)},
        'confusion':dict(Counter(f"{r['expected']} -> {r[key]}" for r in rows))}


def evaluate(split='test',tuning=False):
    dataset,checksum=load(split,tuning)
    rows=[]
    with tempfile.TemporaryDirectory() as directory:
        for i,row in enumerate(dataset):
            settings=Settings(Path(directory)/f'{i}.db','a'*32,'r'*32,'k'*32)
            gate=Gate(settings)
            result=gate.submit(Invocation.model_validate(row['request']))
            rows.append({'id':row['id'],'family':row['family'],'expected':row['expected_decision'],
                'keyword':keyword_baseline(row['request']['sql']),'airlock':result['decision'],
                'expected_changed_rows':row['expected_changed_rows'],
                'actual_changed_rows':result['impact']['changed_rows'] if result['impact'] else None,
                'evaluation_ms':result['evaluation_ms'],'static_ms':result.get('static_ms'),
                'preview_ms':result.get('preview_ms')})
    def p95(key):
        values=sorted(row[key] for row in rows if row[key] is not None)
        return values[(95*len(values)+99)//100-1] if values else None
    impacts=[r for r in rows if r['expected_changed_rows'] is not None]
    report={'recorded_at_utc':datetime.now(timezone.utc).isoformat(),'split':split,'corpus_sha256':checksum,
        'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'cases':len(rows),
        'families':len({r['family'] for r in rows}),'keyword_baseline':metrics(rows,'keyword'),
        'airlock':metrics(rows,'airlock'),'impact_exact_match_count':sum(r['expected_changed_rows']==r['actual_changed_rows'] for r in impacts),
        'impact_denominator':len(impacts),'evaluation_p95_ms':p95('evaluation_ms'),
        'static_p95_ms':p95('static_ms'),'preview_p95_ms':p95('preview_ms'),
        'pure_llm':'not_run','hybrid_llm':'not_run_use_benchmark.ablation_with_authorization','human_ab':'not_run','cohens_kappa':None,
        'limitations':['synthetic authored cases only','correlated variants, only 40 families total',
                      'author saw all templates; family split is not independent external validation',
                      'gate recall includes unsupported/invalid statements, not a real-world danger recall',
                      'latency excludes network and human review; this is a bounded 1206-row SQLite demo'],
        'rows':rows}
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--split',choices=['dev','test'],required=True)
    parser.add_argument('--tuning',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=evaluate(args.split,args.tuning)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},ensure_ascii=False,indent=2))
    if report['airlock']['exact_accuracy']<.9 or report['airlock']['supported_read_fpr']>.1 or report['impact_exact_match_count']!=report['impact_denominator']:
        raise SystemExit('Synthetic regression gate failed. Do not tune against test results.')
