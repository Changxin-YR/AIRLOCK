"""Paired same-target direct SQLite / native HTTP gate timing; synthetic only."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import platform
import random
import sqlite3
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.support import server
from airlock.observability import distribution


def measure(n):
    rows=[]; rng=random.Random(2073)
    with server({'AIRLOCK_CALLS_PER_MINUTE':'1000'}) as (url,keys,client):
        agent={'Authorization':'Bearer '+keys['AIRLOCK_AGENT_TOKEN']}; reviewer={'Authorization':'Bearer '+keys['AIRLOCK_REVIEWER_TOKEN']}
        def invoke(sql,key):
            start=time.perf_counter();response=client.post('/v1/actions',headers=agent,json={'sql':sql,'idempotency_key':key}); elapsed=(time.perf_counter()-start)*1000
            response.raise_for_status();return elapsed,response.json()
        query='SELECT count(*) AS n FROM customers'
        first_call_ms,_=invoke(query,'first-native-call')
        for i in range(10): invoke(query,f'warmup-{i:04d}')
        for i in range(n):
            order=['direct','proxy'];rng.shuffle(order); row={'pair':i,'order':order,'temperature':'warm'}
            for arm in order:
                if arm=='direct':
                    start=time.perf_counter()
                    with closing(sqlite3.connect(keys['AIRLOCK_DB'])) as conn: count=conn.execute(query).fetchone()[0]
                    row['direct_ms']=(time.perf_counter()-start)*1000;assert count==1206
                else:
                    row['proxy_ms'],action=invoke(query,f'latency-read-{i:04d}')
                    assert action['state']=='executed' and action['result']['rows']==[{'n':1206}]
            row['added_ms']=row['proxy_ms']-row['direct_ms'];rows.append(row)
        writes=[]
        for i in range(min(n,30)):
            elapsed,action=invoke('UPDATE customers SET balance=balance+1 WHERE id=1',f'latency-write-{i:04d}')
            assert action['state']=='pending'
            detail=client.get('/v1/actions/'+action['id'],headers=reviewer).json()
            start=time.perf_counter()
            response=client.post('/v1/actions/'+action['id']+'/decision',headers=reviewer,json={
                'decision':'approve','reason':'Synthetic measurement authorized for this isolated fixture',
                'review_digest':detail['review_digest'],'expected_version':detail['version'],'confirmation':detail['confirmation_required']})
            after=(time.perf_counter()-start)*1000;response.raise_for_status();assert response.json()['state']=='executed'
            writes.append({'sample':i,'submit_receipt_ms':elapsed,'approval_request_to_effect_ms':after,
                'static_ms':detail['static_ms'],'preview_ms':detail['preview_ms'],'evaluation_ms':detail['evaluation_ms'],
                'reviewer':'automated_fixture; no human waiting measured'})
    return {'scope':'1206-row synthetic SQLite; concurrency 1; warm HTTP client; same host and target',
        'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,'platform':platform.platform(),'processor':platform.processor(),
        'logical_cpus':os.cpu_count(),'samples':n,'seed':2073,'warmup_calls':10,'first_native_call_ms':first_call_ms,
        'read':{k:signed_distribution([r[k] for r in rows]) for k in ('direct_ms','proxy_ms','added_ms')},
        'write':{k:distribution([r[k] for r in writes]) for k in ('submit_receipt_ms','approval_request_to_effect_ms','static_ms','preview_ms','evaluation_ms')},
        'raw_read_pairs':rows,'raw_writes':writes,
        'not_measured':['live LLM latency','human review latency','distributed upstream overhead','cold OS filesystem cache','production concurrency'],
        'measurement_note':'direct includes SQLite connect/query; proxy includes HTTP, server admission, persistence and audit; negative deltas retained in raw rows'}


def signed_distribution(values):
    import math
    values=sorted(values)
    return {'n':len(values),'mean':sum(values)/len(values) if values else None,**{f'p{q}':values[math.ceil(len(values)*q/100)-1] if values else None for q in (50,95,99)}}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--samples',type=int,default=60);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if not 10<=args.samples<=200: parser.error('samples must be 10..200')
    result=measure(args.samples);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if not k.startswith('raw_')},indent=2))
