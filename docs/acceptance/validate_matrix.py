"""Check ledger structure and receipt provenance; not a functional oracle."""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]
INDEX=json.loads((ROOT/'docs/acceptance/AIRLOCK-acceptance-targets.json').read_text(encoding='utf-8'))
REPORT=json.loads((ROOT/'docs/acceptance/COMPLETION_MATRIX.json').read_text(encoding='utf-8'))
def require(condition,message):
    if not condition:raise ValueError(message)

def main():
    targets=REPORT['targets'];by_id={r['id']:r for r in targets}
    require(len(targets)==len(by_id)==126,'missing or duplicate IDs')
    require(set(by_id)=={r['id'] for r in INDEX['targets']},'changed target set')
    junit={c.get('classname','')+'::'+c.get('name','') for c in ET.parse(ROOT/REPORT.get('junit_evidence','evidence/full-audit-20261002/final/pytest.xml')).iter('testcase')}
    checked_receipts=set()
    for r in targets:
        id=r['id']
        require(set(INDEX['required_result_fields'])<=r.keys(),id+': missing fields')
        require(r['implementation_status'] in INDEX['allowed_implementation_statuses'],id+': implementation enum')
        require(r['verification_status'] in INDEX['allowed_verification_statuses'],id+': verification enum')
        require(len(r['tested_commit_sha'])==40,id+': source SHA')
        require(r['scope'] and r['commands'] and r['evidence'],id+': missing scope or evidence')
        for path in r['code_references']+r['evidence']:
            require((ROOT/path).exists(),id+': missing '+path)
        require(set(r['test_ids'])<=junit,id+': unknown test ID')
        if r.get('derived_parent'):
            children=[c for c in targets if c['id'].startswith(id+'.')]
            require(bool(children),id+': missing children')
            if r['verification_status']=='PASS':
                require(all(c['implementation_status']=='IMPLEMENTED' and c['verification_status']=='PASS' for c in children),id+': overstated parent')
            continue
        for c in r['commands']:
            if isinstance(c.get('command'),str):continue
            if 'receipt' not in c:continue  # CI control has its own raw job record.
            path=ROOT/c['receipt'];status=json.loads(path.read_text(encoding='utf-8'))
            require(status['command']==c['command'],id+': command mismatch')
            require(status['tested_commit_sha']==c['tested_commit_sha'],id+': SHA mismatch')
            require(status['tracked_source_dirty'] is False,id+': dirty executable source')
            require(any(x['exit_code']==status['exit_code'] for x in r['exit_codes']),id+': discarded failure')
            checked_receipts.add(c['receipt'])
    corpus=ROOT/'evidence/full-audit-20261002/final/synthetic-cases.jsonl'
    require(hashlib.sha256(corpus.read_bytes()).hexdigest()=='243854b51e7039324de4c31fa7a67af1a98ddc48b9c9edfbbac581a2c2f73af7','corpus changed')
    print(json.dumps({'target_records':126,'unique_receipts_checked':len(checked_receipts),'counts':REPORT['counts'],'original_goals_all_satisfied':False,'meaning':'structure and provenance only; not functional acceptance'},ensure_ascii=False))

if __name__=='__main__':main()
