import json
import subprocess
import sys
import xml.etree.ElementTree as ET
import pytest
from scripts.verify_evidence import REQUIRED_TESTS,verify_junit,verify_benchmark


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
