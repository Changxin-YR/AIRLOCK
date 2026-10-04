from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import pytest
from airlock.policy import Policy,PolicyManager
from airlock.service import Gate
from conftest import call,decision,count


def document(expression,decision='block'):
    import json
    return 'version: test\nrules:\n - id: one\n   expression: '+json.dumps(expression)+'\n   decision: '+decision+'\n'


@pytest.mark.parametrize('expression',['unknown == 1','tool == 1','changed_rows','1 + 2 > 0','tool.matches(".*")','[1,2].exists(x,x>0)','changed_rows / 0 > 1'])
def test_policy_rejects_unsupported_or_ill_typed_cel(expression):
    with pytest.raises(Exception): Policy.parse(document(expression))


@pytest.mark.parametrize('text',['version: a\nversion: b\nrules: []','version: a\nrules: &a [*a]','!!python/object/apply:os.system [echo bad]',document('true')+'x: 1'])
def test_policy_rejects_unsafe_yaml(text):
    with pytest.raises(Exception): Policy.parse(text)


def test_policy_cannot_override_write_approval(settings,tmp_path):
    path=tmp_path/'policy.yaml'; path.write_text(document('true','pass'))
    gate=Gate(replace(settings,policy_file=path))
    action=gate.submit(call())
    assert action['state']=='pending' and count(gate)==1206


def test_policy_reload_is_atomic_and_invalidates_pending(settings,tmp_path):
    path=tmp_path/'policy.yaml'; path.write_text(document('false'))
    gate=Gate(replace(settings,policy_file=path)); action=gate.submit(call())
    old=gate.policy.active.version
    path.write_text(document('tool == 1'))
    with pytest.raises(ValueError): gate.policy.reload()
    assert gate.policy.active.version==old
    path.write_text(document('changed_rows > 0'))
    gate.policy.reload()
    assert gate.decide(action['id'],decision(action))['state']=='stale'
    assert gate.submit(call(key='blocked-policy'))['state']=='blocked'
    assert count(gate)==1206 and gate.store.verify_audit()['valid']


def test_rule_conflict_and_context_unknown_fail_closed():
    policy=Policy.parse(document('true','pass')+' - id: stop\n   expression: true == true\n   decision: block\n')
    context={'tool':'sql','resource':'customers','principal':'agent:demo','operation':'read','changed_rows':0,'matched_rows':0}
    assert policy.evaluate(context,False)[0]=='block'
    assert policy.evaluate(context|{'changed_rows':None},False)[0]=='block'


def test_cel_limits():
    with pytest.raises(Exception): Policy.parse(document('true && '*100+'true'))
    with pytest.raises(Exception): Policy.parse(document('('*100+'true'+')'*100))
