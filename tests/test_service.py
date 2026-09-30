from concurrent.futures import ThreadPoolExecutor
import json
import uuid
import pytest
from sqlalchemy import select, update
from airlock.auth import add_principal
from airlock.common import AirlockError
from airlock.contracts import ApprovalDecision, ToolRequest
from airlock.policy import Policy
from airlock.runner import LocalRunner
from airlock.service import Service
from airlock.storage import approvals, audit_events, jobs, operations, principals


def req(tool='db.update_rows', **fields):
    data = {'tool':tool, 'filters':[{'field':'id','op':'in','value':[1,2,3]}]}
    if tool == 'db.update_rows': data['values'] = {'status':'archived'}
    return ToolRequest(**(data | fields))

def submit(s, request=None, key=None):
    result = s.service.submit(s.agent, request or req(), key or str(uuid.uuid4()))
    s.service.drain()
    return s.service.get(result['id'], s.agent)

def decision(s, ident, action='approve', **fields):
    current = s.service.get(ident, s.human, provide_view=True)
    plan = current['plan']
    return ApprovalDecision(**({'decision':action,'plan_digest':plan['plan_digest'],
        'view_digest':plan['view_digest'],'expected_version':current['version'],
        'decision_key':str(uuid.uuid4()),'reason':'已确认范围' if action=='approve' else '范围不符合任务'} | fields))

def statuses(s):
    with s.target.connect(readonly=True) as conn:
        return [r[0] for r in conn.execute('SELECT status FROM customers WHERE id IN (1,2,3) ORDER BY id')]

def test_read_uses_real_scoped_data(system):
    s=system
    op=submit(s,req('db.query_rows',filters=[],limit=5))
    assert op['state']=='SUCCEEDED' and op['decision']=='pass'
    assert [x['id'] for x in op['result']['query_result']['rows']]==[1,2,3,4,5]
    assert op['result']['query_result']['truncated'] is True

def test_pending_only_executes_after_independent_human_decision(system):
    s=system; op=submit(s)
    assert op['state']=='PENDING_APPROVAL' and statuses(s)==['active']*3
    d=decision(s,op['id'])
    approved=s.service.decide(op['id'],s.human,d)
    assert approved['state']=='READY' and statuses(s)==['active']*3
    s.service.drain()
    assert s.service.get(op['id'],s.agent)['state']=='SUCCEEDED'
    assert statuses(s)==['archived']*3
    assert s.service.decide(op['id'],s.human,d)['state']=='SUCCEEDED'

def test_rejection_is_terminal_and_audit_retains_provided_view(system):
    s=system; op=submit(s)
    s.service.decide(op['id'],s.human,decision(s,op['id'],'reject'))
    s.service.drain()
    assert s.service.get(op['id'],s.agent)['state']=='REJECTED'
    assert statuses(s)==['active']*3
    audit=s.service.audit(op['id'],s.human)
    assert audit['chain_valid'] is True
    assert audit['provided_approval_view']['facts']['total_changed']==3

def test_large_deletion_is_blocked_and_cannot_be_human_overridden(system):
    s=system; op=submit(s,req('db.delete_rows',filters=[{'field':'id','op':'gte','value':1}]))
    assert op['state']=='BLOCKED' and op['summary']['direct_changed']==1206
    with pytest.raises(AirlockError) as e: s.service.decide(op['id'],s.human,decision(s,op['id']))
    assert e.value.code=='VERSION_CONFLICT' and statuses(s)==['active']*3

def test_agent_cannot_approve_itself(system):
    s=system; op=submit(s)
    with pytest.raises(AirlockError) as e: s.service.decide(op['id'],s.agent,decision(s,op['id']))
    assert e.value.code=='LOGIN_REQUIRED'

def test_human_must_have_received_the_view_in_this_session(system):
    s=system; op=submit(s)
    current=s.service.get(op['id'],s.human)
    plan=current['plan']
    d=ApprovalDecision(decision='approve',plan_digest=plan['plan_digest'],view_digest=plan['view_digest'],
        expected_version=current['version'],decision_key=str(uuid.uuid4()))
    with pytest.raises(AirlockError) as e: s.service.decide(op['id'],s.human,d)
    assert e.value.code=='VIEW_REQUIRED'

@pytest.mark.parametrize('fields,code', [({'plan_digest':'f'*64},'PLAN_MISMATCH'),
    ({'view_digest':'0'*64},'PLAN_MISMATCH'),({'expected_version':999},'VERSION_CONFLICT')])
def test_approval_binding_rejects_tampering(system,fields,code):
    s=system; op=submit(s)
    with pytest.raises(AirlockError) as e: s.service.decide(op['id'],s.human,decision(s,op['id'],**fields))
    assert e.value.code==code and statuses(s)==['active']*3

def test_request_idempotency_and_conflict(system):
    s=system; key=str(uuid.uuid4())
    one=s.service.submit(s.agent,req(),key)
    two=s.service.submit(s.agent,req(),key)
    assert one['id']==two['id']
    with pytest.raises(AirlockError) as e: s.service.submit(s.agent,req(values={'tag':'different'}),key)
    assert e.value.code=='IDEMPOTENCY_CONFLICT'

def test_concurrent_submit_has_one_operation(system):
    s=system; key=str(uuid.uuid4())
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(lambda _:s.service.submit(s.agent,req(),key),range(12)))
    assert len({r['id'] for r in results})==1

def test_concurrent_human_decisions_commit_only_one(system):
    s=system; op=submit(s)
    a=decision(s,op['id']); b=decision(s,op['id'],'reject')
    def act(d):
        try: return s.service.decide(op['id'],s.human,d)['state']
        except AirlockError as e: return e.code
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(act,[a,b]))
    assert results.count('ALREADY_DECIDED')==1
    with s.store.engine.connect() as c: assert len(c.execute(select(approvals)).all())==1

def test_pending_survives_restart_but_not_expiry(system):
    s=system; op=submit(s)
    s.service=Service(s.store,LocalRunner(s.target),s.settings,policy=s.service.policy())
    s.service.drain()
    assert s.service.get(op['id'],s.agent)['state']=='PENDING_APPROVAL'
    s.clock.advance(31); s.service.drain()
    assert s.service.get(op['id'],s.agent)['state']=='EXPIRED' and statuses(s)==['active']*3

def test_data_drift_detected_at_execution(system):
    s=system; op=submit(s)
    with s.target.connect() as c: c.execute("UPDATE customers SET tag='concurrent' WHERE id=10")
    s.service.decide(op['id'],s.human,decision(s,op['id'])); s.service.drain()
    assert s.service.get(op['id'],s.agent)['state']=='STALE' and statuses(s)==['active']*3

@pytest.mark.parametrize('when', ['before_decision','before_claim'])
def test_policy_change_invalidates_old_plan(system,when):
    s=system; op=submit(s); d=decision(s,op['id'])
    if when=='before_claim': s.service.decide(op['id'],s.human,d)
    s.service.override_policy=Policy(name='changed')
    if when=='before_decision': s.service.decide(op['id'],s.human,d)
    s.service.drain()
    assert s.service.get(op['id'],s.agent)['state']=='STALE' and statuses(s)==['active']*3

@pytest.mark.parametrize('who',['agent','reviewer'])
def test_authorization_revoked_before_execution(system,who):
    s=system; op=submit(s); s.service.decide(op['id'],s.human,decision(s,op['id']))
    with s.store.transaction() as c: c.execute(update(principals).where(principals.c.id==who).values(active=False,version=2))
    s.service.drain()
    # Inspect directly because the revoked identity no longer has an API session.
    with s.store.engine.connect() as c: state=c.execute(select(operations.c.state).where(operations.c.id==op['id'])).scalar_one()
    assert state=='BLOCKED' and statuses(s)==['active']*3

def test_per_principal_tool_allowlist(system):
    s=system
    add_principal(s.store,'read-agent','agent','demo',token='read-token',tools=['db.query_rows'])
    reader=s.auth.agent('Bearer read-token')
    with pytest.raises(AirlockError) as e: s.service.submit(reader,req(),str(uuid.uuid4()))
    assert e.value.code=='AUTH_REVOKED'

def test_cancellation_before_claim_has_no_business_effect(system):
    s=system; op=submit(s); s.service.decide(op['id'],s.human,decision(s,op['id']))
    assert s.service.cancel(op['id'],s.human)['state']=='CANCELLED'
    s.service.drain(); assert statuses(s)==['active']*3

def test_cancellation_after_claim_is_not_promised(system):
    s=system; op=submit(s); s.service.decide(op['id'],s.human,decision(s,op['id']))
    job,current=s.service._claim()
    with pytest.raises(AirlockError) as e: s.service.cancel(op['id'],s.human)
    assert e.value.code=='NOT_CANCELLABLE'
    s.service._finish_execute(job,current)
    assert statuses(s)==['archived']*3

def test_response_loss_recovers_receipt_without_repeating_write(system):
    s=system
    class LoseResponse(LocalRunner):
        def execute_once(self,envelope):
            self.target.execute_once(envelope)
            raise TimeoutError('simulated transport loss AFTER commit')
    s.service.runner=LoseResponse(s.target)
    op=submit(s); s.service.decide(op['id'],s.human,decision(s,op['id'])); s.service.step()
    assert s.service.get(op['id'],s.agent)['state']=='UNKNOWN' and statuses(s)==['archived']*3
    s.clock.advance(3); s.service.runner=LocalRunner(s.target); s.service.drain()
    assert s.service.get(op['id'],s.agent)['state']=='SUCCEEDED'
    with s.target.connect(readonly=True) as c: assert c.execute('SELECT version FROM customers WHERE id=1').fetchone()[0]==1
    assert any(e['type']=='RECEIPT_RECOVERED' for e in s.service.audit(op['id'],s.human)['items'])

def test_metadata_audit_failure_after_target_commit_is_recoverable(system):
    s=system; op=submit(s); s.service.decide(op['id'],s.human,decision(s,op['id']))
    original=s.store.audit
    def fail(conn, op, kind, data=None):
        if kind=='EXECUTION_RECEIPT': raise OSError('metadata disk failure')
        return original(conn,op,kind,data)
    s.store.audit=fail
    with pytest.raises(OSError): s.service.step()
    assert statuses(s)==['archived']*3
    assert s.service.get(op['id'],s.agent)['state']=='EXECUTING'
    s.store.audit=original; s.clock.advance(3)
    s.service=Service(s.store,LocalRunner(s.target),s.settings,policy=s.service.policy()); s.service.drain()
    assert s.service.get(op['id'],s.agent)['state']=='SUCCEEDED'

def test_audit_failure_before_authorization_prevents_execution(system):
    s=system; op=submit(s); s.service.decide(op['id'],s.human,decision(s,op['id']))
    original=s.store.audit
    def fail(conn, op, kind, data=None):
        if kind=='EXECUTION_AUTHORIZED': raise OSError('audit not durable')
        return original(conn,op,kind,data)
    s.store.audit=fail
    with pytest.raises(OSError): s.service.step()
    s.store.audit=original
    assert statuses(s)==['active']*3 and s.service.get(op['id'],s.agent)['state']=='READY'

def test_preview_failure_is_closed_not_model_fallback(system):
    s=system
    s.service.runner.preview=lambda *_: (_ for _ in ()).throw(RuntimeError('broken backup'))
    op=submit(s)
    assert op['state']=='BLOCKED' and op['error']['code']=='PREVIEW_UNAVAILABLE'
    assert statuses(s)==['active']*3

def test_resource_scope_and_agent_ownership_on_reads_and_lists(system):
    s=system; op=submit(s)
    other=s.auth.agent('Bearer '+'test-other-token-'+'b'*40)
    with pytest.raises(AirlockError) as e: s.service.get(op['id'],other)
    assert e.value.status==404
    assert s.service.list(other)['items']==[] and s.service.events(other)==[]
    add_principal(s.store,'same-scope-agent','agent','demo',token='same-scope-token')
    same=s.auth.agent('Bearer same-scope-token')
    with pytest.raises(AirlockError): s.service.get(op['id'],same)
    assert s.service.list(same)['items']==[]

def test_audit_chain_detects_local_modification_without_claiming_admin_proof(system):
    s=system; op=submit(s)
    assert s.service.audit(op['id'],s.human)['chain_valid']
    with s.store.transaction() as c:
        c.execute(update(audit_events).where(audit_events.c.operation_id==op['id'],audit_events.c.ordinal==1).values(data_json='{}'))
    assert not s.service.audit(op['id'],s.human)['chain_valid']

def test_single_tag_explicit_rule_passes_and_receipt_is_real(system):
    s=system; op=submit(s,req(values={'tag':'reviewed'},filters=[{'field':'id','op':'eq','value':1}]))
    assert op['state']=='SUCCEEDED' and op['reason_code']=='EXPLICIT_SMALL_TAG_RULE'
    with s.target.connect(readonly=True) as c: assert c.execute('SELECT tag FROM customers WHERE id=1').fetchone()[0]=='reviewed'
