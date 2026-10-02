"""Require successful command receipts AND the actual expected result artifacts."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
DIR=ROOT/'evidence'
REQUIRED_LOGS=['pytest.log','frontend-check.log','frontend-tests.log','benchmark-dev.log',
               'benchmark-test.log','browser-native.log','docker-smoke.log']
for name in REQUIRED_LOGS:
    status=json.loads((DIR/(name+'.status.json')).read_text())
    assert status['exit_code']==0,f'{name}: failed command'
    assert (DIR/name).is_file(),f'{name}: missing raw log'
cases={case.attrib['name']:case for case in ET.parse(DIR/'pytest.xml').iter('testcase')}
required={'test_official_mcp_sdk_pending_approval_and_result',
          'test_process_death_inside_gate_decision_is_atomic','test_concurrent_approvals_execute_once',
          'test_real_sse_reconnect_cursor_only_delivers_newer_events','test_http_complete_flow'}
for name in required:
    assert name in cases,f'missing required test: {name}'
    assert not any(cases[name].find(tag) is not None for tag in ('failure','error','skipped')),name
browser=json.loads((DIR/'browser-report.json').read_text())
assert browser['mode']=='native_browser_e2e' and not browser['errors'] and not browser['not_proven']
assert len(set(browser['passed']))>=9
container=json.loads((DIR/'docker-report.json').read_text())
assert container['mode']=='real_docker_compose'
assert container['rows_before_independent_approval']==1206 and container['rows_after_approval_and_restart']==0
assert container['probe']['uid']!=0 and container['probe']['effective_capabilities']==0
report=json.loads((DIR/'benchmark-test.json').read_text())
assert report['cases']==80 and report['families']==16 and len(report['rows'])==80
assert report['corpus_sha256']==json.loads((ROOT/'benchmark/manifest.json').read_text())['sha256']
assert report['human_ab']=='not_run' and report['cohens_kappa'] is None
print('Required exit codes, tests, native browser, Docker and benchmark artifacts verified.')
