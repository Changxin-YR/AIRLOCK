"""Incident-inspired synthetic comparison, with no production connection."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from airlock.models import Settings,Invocation,Decision
from airlock.service import Gate,agent_view


def run():
    with closing(sqlite3.connect(':memory:')) as direct:
        direct.execute('CREATE TABLE synthetic_ids(id INTEGER PRIMARY KEY)')
        direct.executemany('INSERT INTO synthetic_ids VALUES(?)',[(i,) for i in range(1206)])
        before=direct.execute('SELECT count(*) FROM synthetic_ids').fetchone()[0]
        direct.execute('DELETE FROM synthetic_ids');after=direct.execute('SELECT count(*) FROM synthetic_ids').fetchone()[0]
    with tempfile.TemporaryDirectory() as directory:
        gate=Gate(Settings(Path(directory)/'demo.sqlite','a'*32,'r'*32,'k'*32))
        def count():
            with gate.store.connection() as conn:return conn.execute('SELECT count(*) FROM customers').fetchone()[0]
        action=gate.submit(Invocation(sql='DELETE FROM customers',idempotency_key='demo-reject-all'))
        pending_count=count()
        rejected=gate.decide(action['id'],Decision(decision='reject',reason='Synthetic independent reviewer denies scope',review_digest=action['review_digest'],expected_version=1))
        rejected_count=count()
        fallback=gate.submit(Invocation(sql='SELECT count(*) AS remaining FROM customers',idempotency_key='demo-safe-alternative'))
        second=gate.submit(Invocation(sql='DELETE FROM customers',idempotency_key='demo-approve-all'))
        executed=gate.decide(second['id'],Decision(decision='approve',reason='Explicit synthetic fixture authorization',
            review_digest=second['review_digest'],expected_version=1,confirmation=second['confirmation_required']))
        result={'scope':'disposable synthetic data; automated independent reviewer fixture; no live model/human',
            'without_gate':{'before':before,'after':after},'with_gate':{'pending_rows':pending_count,'rejected_rows':rejected_count,
            'denial':agent_view(rejected),'safe_alternative':agent_view(fallback),'approved_rows':count(),'approved_receipt':agent_view(executed)},'audit':gate.store.verify_audit()}
        assert before==1206 and after==0 and pending_count==rejected_count==1206 and count()==0 and result['audit']['valid']
        return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    result=run();args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
