from pathlib import Path
import sqlite3
import time
import pytest
from airlock.common import AirlockError, digest, sign
from airlock.contracts import ToolRequest, normalize
from airlock.plans import make_plan
from airlock.target import TargetStore, initialize_target

SECRET = 's' * 48

@pytest.fixture
def target(tmp_path):
    path = tmp_path / 'target.db'
    initialize_target(path)
    return TargetStore(path, SECRET)

def request(tool='db.update_rows', **kw):
    data = {'tool': tool, 'filters': [{'field':'id','op':'in','value':[1,2,3]}]}
    if tool == 'db.update_rows': data['values'] = {'status':'archived'}
    return normalize(ToolRequest(**(data | kw)))

def envelope(target, req):
    facts = target.preview(req, 'demo')
    plan = make_plan('op-test', {'id':'agent','scope':'demo','version':1}, req, facts, 'policy', time.time()+60)
    permit = {'operation_id':'op-test','plan_digest':plan['plan_digest'],'not_after':plan['expires_at']}
    return {'plan':plan,'permit':permit,'signature':sign(permit,SECRET)}

def count(target):
    with target.connect(readonly=True) as conn:
        return conn.execute('SELECT count(*) FROM customers').fetchone()[0]

def test_preview_never_mutates_target_and_counts_cascade(target):
    before = target.path.read_bytes()
    facts = target.preview(request('db.delete_rows'), 'demo')
    assert facts['direct_changed'] == 3
    assert facts['cascade_changed'] == 6
    assert facts['total_changed'] == 9
    assert target.path.read_bytes() == before
    assert count(target) == 1209

def test_execute_with_receipt_is_idempotent(target):
    env = envelope(target, request())
    first = target.execute_once(env)
    second = target.execute_once(env)
    assert first == second and first['total_changed'] == 3
    with target.connect(readonly=True) as conn:
        assert conn.execute('SELECT version FROM customers WHERE id=1').fetchone()[0] == 1
        assert conn.execute('SELECT count(*) FROM execution_receipts').fetchone()[0] == 1

def test_drift_blocks_old_plan(target):
    env = envelope(target, request())
    with target.connect() as conn:
        conn.execute("UPDATE customers SET tag='outside change' WHERE id=100")
    with pytest.raises(AirlockError, match='目标数据已变化') as error:
        target.execute_once(env)
    assert error.value.code == 'STALE'
    with target.connect(readonly=True) as conn:
        assert conn.execute('SELECT status FROM customers WHERE id=1').fetchone()[0] == 'active'

@pytest.mark.parametrize('sql', [
    'CREATE TRIGGER bad AFTER DELETE ON customers BEGIN DELETE FROM customer_notes; END',
    'CREATE VIEW secrets AS SELECT * FROM customers',
    'CREATE TABLE extra(x TEXT)',
    'ALTER TABLE customers ADD COLUMN extra TEXT',
])
def test_unknown_schema_is_not_a_sandbox(target, sql):
    with target.connect() as conn: conn.execute(sql)
    with pytest.raises(AirlockError) as error: target.preview(request(), 'demo')
    assert error.value.code == 'UNSUPPORTED_SCHEMA'

def test_bound_values_not_sql_and_scope_cannot_be_bypassed(target):
    req = request('db.query_rows', filters=[{'field':'name','op':'eq','value':"' OR 1=1 --"}])
    assert target.preview(req, 'demo')['query_result']['rows'] == []
    req = request('db.query_rows', filters=[{'field':'project','op':'eq','value':'other'}])
    assert target.preview(req, 'demo')['query_result']['rows'] == []

def test_row_limit_is_failure_not_partial_success(target):
    target.max_rows = 3
    with pytest.raises(AirlockError) as error: target.preview(request(), 'demo')
    assert error.value.code == 'PREVIEW_LIMIT'

def test_forged_permit_is_rejected(target):
    env = envelope(target, request())
    env['signature'] = 'f'*64
    with pytest.raises(AirlockError) as error: target.execute_once(env)
    assert error.value.code == 'INVALID_PERMIT'

def test_changed_request_cannot_use_old_approval(target):
    env = envelope(target, request())
    env['plan']['request']['filters'] = []
    with pytest.raises(AirlockError) as error: target.execute_once(env)
    assert error.value.code == 'PLAN_MISMATCH'

def test_expired_permit_never_writes_but_committed_retry_returns_receipt(target):
    env = envelope(target, request())
    saved = target.execute_once(env)
    target.clock = lambda: env['plan']['expires_at'] + 1
    assert target.execute_once(env) == saved
    env = envelope(target, request(values={'tag':'a'}))
    target.clock = lambda: env['plan']['expires_at'] + 2
    with pytest.raises(AirlockError) as error: target.execute_once(env)
    # This new plan deliberately has the same operation id but different content.
    assert error.value.code == 'RECEIPT_CONFLICT'

def test_independent_oracle_matches_every_changed_row(target):
    req = request('db.delete_rows')
    facts = target.preview(req, 'demo')
    # Oracle identifies fixture rows independently; it does not call changes().
    expected = {('customers', i) for i in (1,2,3)} | {('customer_notes', i*2+j) for i in (1,2,3) for j in (0,1)}
    assert {(c['table'],c['id']) for c in facts['changes']} == expected
    assert all(c['after'] is None and c['before'] for c in facts['changes'])
