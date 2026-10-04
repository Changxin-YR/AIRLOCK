"""Two real processes must observe the same committed authorization policy."""
from dataclasses import replace
import multiprocessing
from airlock.service import Gate
from conftest import call,decision,count


def worker(settings, action, ready, proceed, output):
    gate=Gate(settings)
    ready.set()
    if not proceed.wait(15):raise RuntimeError('test coordination timeout')
    output.put({'decision':gate.decide(action['id'],decision(action))['state'],
                'submission':gate.submit(call('SELECT 1',key='other-process-read'))['state'],
                'rows':count(gate)})


def test_policy_reload_is_seen_by_existing_other_process(settings,tmp_path):
    path=tmp_path/'policy.yaml';path.write_text('version: original\nrules: []\n')
    settings=replace(settings,policy_file=path)
    gate=Gate(settings);action=gate.submit(call())
    ctx=multiprocessing.get_context('spawn')
    ready,proceed,output=ctx.Event(),ctx.Event(),ctx.Queue()
    process=ctx.Process(target=worker,args=(settings,action,ready,proceed,output))
    process.start()
    try:
        assert ready.wait(15)
        path.write_text('version: deny-all\nrules:\n - id: stop\n   expression: true == true\n   decision: block\n')
        gate.reload_policy();proceed.set()
        assert output.get(timeout=15)=={'decision':'stale','submission':'blocked','rows':1206}
        process.join(15);assert process.exitcode==0
        assert gate.store.verify_audit()['valid']
    finally:
        if process.is_alive():process.terminate();process.join(5)
        output.close()


def test_restart_uses_activated_policy_not_unactivated_file(settings,tmp_path):
    path=tmp_path/'policy.yaml';path.write_text('version: original\nrules: []\n')
    settings=replace(settings,policy_file=path)
    first=Gate(settings)
    path.write_text('this file is not a valid policy')
    restarted=Gate(settings)
    assert first.policy_version==restarted.policy_version
    assert restarted.submit(call())['state']=='pending'
