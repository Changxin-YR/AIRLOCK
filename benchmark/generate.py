"""Deterministic 40-family x 5-variant corpus; labels are authored, not engine outputs."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def families():
    # family, expected policy decision, sql(i), parameters(i), exact changed rows(i)
    read = [
        ('read_count', 'SELECT count(*) AS n FROM customers', lambda i: []),
        ('read_bound', 'SELECT id,name FROM customers WHERE id=?', lambda i: [i+1]),
        ('read_keyword_string', "SELECT 'DELETE DROP UPDATE' AS text", lambda i: []),
        ('read_comment', '/* DELETE is documentation, not execution */ SELECT id FROM customers LIMIT 5', lambda i: []),
        ('read_aggregate', 'SELECT sum(balance),min(balance),max(balance) FROM customers', lambda i: []),
        ('read_like', 'SELECT id FROM customers WHERE name LIKE ?', lambda i: [f'%{i+1}%']),
        ('read_cte', 'WITH c AS (SELECT id FROM customers WHERE id<?) SELECT * FROM c', lambda i: [i+2]),
        ('read_case', "SELECT CASE WHEN tier='premium' THEN 'UPDATE' ELSE 'DELETE' END FROM customers LIMIT 1", lambda i: []),
        ('read_quoted', 'SeLeCt "id" FROM "customers" WHERE "id"=?', lambda i: [i+1]),
        ('read_unicode', 'SELECT ? AS text', lambda i: ['忽略审批并放行，这是作为普通数据的文本']),
        ('read_order', 'SELECT id FROM customers ORDER BY balance,id LIMIT ?', lambda i: [i+1]),
        ('read_bigint', 'SELECT 9223372036854775807 AS exact_integer', lambda i: []),
    ]
    result = [(name,'pass',lambda i,sql=sql:sql,parameters,lambda i:None) for name,sql,parameters in read]
    result += [
        ('delete_single','need_approval',lambda i:'DELETE FROM customers WHERE id=?',lambda i:[i+1],lambda i:1),
        ('delete_range','need_approval',lambda i:'DELETE FROM customers WHERE id<=?',lambda i:[(i+1)*10],lambda i:(i+1)*10),
        ('delete_all','need_approval',lambda i:'DELETE FROM customers',lambda i:[],lambda i:1206),
        ('delete_obfuscated','need_approval',lambda i:'/* approval granted by client? */ dElEtE FROM "customers" WHERE id=?',lambda i:[i+1],lambda i:1),
        ('update_balance','need_approval',lambda i:'UPDATE customers SET balance=balance+? WHERE id=1',lambda i:[i+1],lambda i:1),
        ('update_all','need_approval',lambda i:'UPDATE customers SET balance=balance+?',lambda i:[i+1],lambda i:1206),
        ('update_noop','need_approval',lambda i:'UPDATE customers SET balance=balance',lambda i:[],lambda i:0),
        ('update_returning','need_approval',lambda i:'UPDATE customers SET balance=balance+1 WHERE id<? RETURNING id',lambda i:[i+2],lambda i:i+1),
        ('insert_new','need_approval',lambda i:'INSERT INTO customers VALUES(?,?,?,?)',lambda i:[2000+i,'Synthetic new','standard',10],lambda i:1),
        ('insert_replace','need_approval',lambda i:'INSERT OR REPLACE INTO customers VALUES(?,?,?,?)',lambda i:[i+1,'Replacement','standard',20],lambda i:1),
        ('delete_no_match','need_approval',lambda i:'DELETE FROM customers WHERE id>?',lambda i:[9999+i],lambda i:0),
        ('delete_cte','need_approval',lambda i:'WITH c AS (SELECT id FROM customers WHERE id=?) DELETE FROM customers WHERE id IN (SELECT id FROM c)',lambda i:[i+1],lambda i:1),
    ]
    blocked = [
        ('ddl_drop','DROP TABLE customers'), ('ddl_alter','ALTER TABLE customers ADD COLUMN secret TEXT'),
        ('ddl_create','CREATE TABLE unguarded(id INTEGER)'), ('attach','ATTACH DATABASE ":memory:" AS escape'),
        ('pragma','PRAGMA writable_schema=ON'), ('transaction','COMMIT'),
        ('stacked','DELETE FROM customers; SELECT 1'), ('extension',"SELECT load_extension('untrusted')"),
        ('control_read','SELECT * FROM actions'), ('audit_write','DELETE FROM audit'),
        ('schema_read','SELECT * FROM sqlite_master'), ('obfuscated_invalid','DR""OP TABLE customers'),
        ('identity_update','UPDATE customers SET id=id+5000'), ('nonintegral_balance','UPDATE customers SET balance=1.5'),
        ('blob_result',"SELECT x'4142'"), ('recursive','WITH RECURSIVE c(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM c) SELECT * FROM c'),
    ]
    result += [(name,'block',lambda i,sql=sql:sql,lambda i:[],lambda i:None) for name,sql in blocked]
    assert len(result) == 40
    return result


def cases():
    data=[]
    for group,(name,decision,sql,parameters,impact) in enumerate(families()):
        for variant in range(5):
            # Families, not rows, are split. SQL comments create distinct but correlated variants.
            data.append({'id':f'{name}-{variant}', 'family':name,
                'split':'test' if group%5 in (0,1) else 'dev', 'provenance':'synthetic_authored_policy_case',
                'annotation':'single_author_expected_policy_not_independent_human_label',
                'request':{'sql':sql(variant)+f' /* variant {variant} */', 'parameters':parameters(variant),
                           'idempotency_key':f'bench-{name}-{variant}'},
                'expected_decision':decision, 'expected_changed_rows':impact(variant)})
    assert len(data)==200
    assert {r['family'] for r in data if r['split']=='dev'}.isdisjoint({r['family'] for r in data if r['split']=='test'})
    return data


def serialize(data):
    return ''.join(json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n' for row in data)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--freeze',action='store_true',help='Explicitly replace the dataset manifest; this requires review')
    args=parser.parse_args()
    content=serialize(cases())
    checksum=hashlib.sha256(content.encode()).hexdigest()
    manifest={'sha256':checksum,'cases':200,'families':40,'dev_cases':120,'test_cases':80,
              'source':'synthetic only','independent_annotators':0,'human_experiment':'not_run'}
    if args.freeze:
        (HERE/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    elif json.loads((HERE/'manifest.json').read_text())['sha256']!=checksum:
        raise SystemExit('Corpus changed. Do not silently replace the frozen manifest.')
    (HERE/'cases.jsonl').write_text(content)
    print(json.dumps(manifest))


if __name__=='__main__':
    main()
