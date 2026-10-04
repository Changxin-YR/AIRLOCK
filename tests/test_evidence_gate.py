import json
import subprocess
import sys
import xml.etree.ElementTree as ET
import pytest
from scripts.verify_evidence import REQUIRED_TESTS,verify_junit,verify_benchmark,verify_latency


@pytest.mark.parametrize('tag',['failure','error','skipped'])
def test_evidence_rejects_any_failed_or_skipped_case(tmp_path,tag):
    suite=ET.Element('testsuite')
    for name in REQUIRED_TESTS: ET.SubElement(suite,'testcase',name=name)
    ET.SubElement(ET.SubElement(suite,'testcase',name='new_security_case'),tag)
    path=tmp_path/'test.xml'; ET.ElementTree(suite).write(path)
    with pytest.raises(ValueError,match='JUnit failed'):
        verify_junit(path)


def test_evidence_checks_survive_python_optimization(tmp_path):
    path=tmp_path/'empty.xml'; path.write_text('<testsuite/>')
    result=subprocess.run([sys.executable,'-O','-c',
        'from pathlib import Path; from scripts.verify_evidence import verify_junit; import sys; verify_junit(Path(sys.argv[1]))',str(path)],capture_output=True)
    assert result.returncode!=0 and b'JUnit has no tests' in result.stderr


def test_evidence_recomputes_prediction_metrics():
    report={'cases':2,'families':2,'corpus_sha256':'hash','human_ab':'not_run','cohens_kappa':None,
      'rows':[{'id':'a','family':'a','expected':'pass','airlock':'block','expected_changed_rows':None},
              {'id':'b','family':'b','expected':'need_approval','airlock':'pass','expected_changed_rows':1,'actual_changed_rows':1}],
      'airlock':{'exact_accuracy':1,'supported_read_fpr':0},'impact_denominator':1,'impact_exact_match_count':1}
    with pytest.raises(ValueError,match='regression threshold'):
        verify_benchmark(report,2,2,'hash')


@pytest.fixture
def latency_report():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    return json.loads((root/'evidence/single-person-20261003/ci/verified/latency.json').read_text())


def test_latency_gate_recomputes_preserved_real_samples(latency_report):
    verify_latency(latency_report)


@pytest.mark.parametrize('mutation', ['raw_slow','false_summary','missing_pair','duplicate_pair',
    'duplicate_action','broken_pair','nan','negative_duration','false_count','missing_write','bool_value'])
def test_latency_gate_rejects_false_pass(latency_report,mutation):
    report=latency_report
    if mutation=='raw_slow':
        for row in report['raw_read_pairs']: row['proxy_ms']+=300;row['added_ms']+=300
        for row in report['raw_writes']: row['static_ms']=1000
    elif mutation=='false_summary': report['read']['added_ms']['p95']=0
    elif mutation=='missing_pair': report['raw_read_pairs'].pop()
    elif mutation=='duplicate_pair': report['raw_read_pairs'][1]['pair']=0
    elif mutation=='duplicate_action': report['raw_read_pairs'][1]['action_id']=report['raw_read_pairs'][0]['action_id']
    elif mutation=='broken_pair': report['raw_read_pairs'][0]['added_ms']=0
    elif mutation=='nan': report['raw_writes'][0]['static_ms']=float('nan')
    elif mutation=='negative_duration': report['raw_writes'][0]['static_ms']=-1
    elif mutation=='false_count': report['write']['preview_ms']['n']=1
    elif mutation=='missing_write': report['raw_writes'].pop()
    elif mutation=='bool_value': report['raw_writes'][0]['static_ms']=True
    with pytest.raises(ValueError,match='latency'):
        verify_latency(report)


def test_latency_gate_keeps_negative_paired_differences():
    # Hand-computed independent example: every proxy is 1ms faster than direct.
    reads=[{'pair':i,'action_id':str(i),'order':['direct','proxy'],
            'direct_ms':2,'proxy_ms':1,'added_ms':-1} for i in range(10)]
    fields=('submit_receipt_ms','approval_request_to_effect_ms','static_ms','preview_ms','evaluation_ms')
    writes=[{'sample':i,**{field:1 for field in fields}} for i in range(10)]
    report={'samples':10,'raw_read_pairs':reads,'raw_writes':writes,
        'read':{field:{'n':10,'mean':value,'p50':value,'p95':value,'p99':value}
                for field,value in [('direct_ms',2),('proxy_ms',1),('added_ms',-1)]},
        'write':{field:{'n':10,'p50':1,'p95':1,'p99':1} for field in fields}}
    verify_latency(report,expected_samples=10)
