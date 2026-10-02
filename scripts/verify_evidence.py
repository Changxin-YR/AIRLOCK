"""Validate raw evidence independently of exit receipts; safe under python -O."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_LOGS = ['pytest.log','frontend-check.log','frontend-tests.log','benchmark-dev.log',
                 'benchmark-test.log','browser-native.log','docker-smoke.log']
REQUIRED_TESTS = {'test_official_mcp_sdk_pending_approval_and_result',
    'test_process_death_inside_gate_decision_is_atomic','test_concurrent_approvals_execute_once',
    'test_real_sse_reconnect_cursor_only_delivers_newer_events','test_http_complete_flow',
    'test_server_filtered_pending_queue_survives_long_read_history','test_state_filter_is_validated_and_applied'}
REQUIRED_BROWSER = {'agent_credential_rejected_by_reviewer_console','approval_disabled_without_informed_confirmation',
    'browser_rejection_preserves_all_1206_rows','browser_approval_executes_real_update_once',
    'critical_action_requires_exact_1206_scope_phrase','390px_mobile_has_no_horizontal_overflow',
    'audit_replay_and_hmac_verification_render','logout_removes_authenticated_console',
    'no_browser_javascript_errors','pending_queue_survives_more_than_100_newer_reads'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(directory, name):
    return json.loads((directory / name).read_text(encoding='utf-8'))


def verify_junit(path):
    tree = ET.parse(path)
    cases = list(tree.iter('testcase'))
    require(bool(cases), 'JUnit has no tests')
    for case in cases:
        require(not any(case.find(tag) is not None for tag in ('failure','error','skipped')),
                'JUnit failed/error/skipped: ' + case.get('name','unnamed'))
    for suite in tree.iter('testsuite'):
        require(all(int(suite.get(key,'0')) == 0 for key in ('failures','errors','skipped')),
                'JUnit suite reports failures/errors/skips')
    require(REQUIRED_TESTS <= {c.get('name') for c in cases}, 'JUnit missing mandatory tests')
    return len(cases)


def verify_benchmark(report, expected_cases, expected_families, corpus_sha):
    rows = report['rows']
    require(report['cases']==len(rows)==expected_cases, 'benchmark case count')
    require(report['families']==len({r['family'] for r in rows})==expected_families, 'benchmark families')
    require(len({r['id'] for r in rows}) == len(rows), 'duplicate benchmark case')
    require(report['corpus_sha256']==corpus_sha, 'benchmark hash')
    require(report['human_ab']=='not_run' and report['cohens_kappa'] is None, 'synthetic provenance')
    allowed = {'pass','block','need_approval'}
    require(all(r['airlock'] in allowed and r['expected'] in allowed for r in rows), 'invalid prediction')
    accuracy = sum(r['airlock']==r['expected'] for r in rows)/len(rows)
    reads = [r for r in rows if r['expected']=='pass']
    require(bool(reads),'benchmark lacks pass denominator')
    fpr = sum(r['airlock']!='pass' for r in reads)/len(reads)
    impacts = [r for r in rows if r['expected_changed_rows'] is not None]
    matches = sum(r['expected_changed_rows']==r['actual_changed_rows'] for r in impacts)
    require(accuracy >= .9 and fpr <= .1 and matches==len(impacts), 'benchmark regression threshold')
    require(report['airlock']['exact_accuracy']==accuracy and report['airlock']['supported_read_fpr']==fpr,
            'benchmark summary disagrees with raw rows')
    require(report['impact_denominator']==len(impacts) and report['impact_exact_match_count']==matches,
            'impact summary disagrees with raw rows')


def verify(directory):
    for name in REQUIRED_LOGS:
        status = load(directory, name+'.status.json')
        require(status['exit_code']==0, name+': failed command')
        require(bool(status.get('command')), name+': missing command')
        require((directory/name).stat().st_size > 0, name+': empty raw log')
    tests = verify_junit(directory/'pytest.xml')
    browser = load(directory,'browser-report.json')
    require(browser['mode']=='native_browser_e2e' and not browser['errors'] and not browser['not_proven'],
            'native browser failed or weakened')
    require(REQUIRED_BROWSER <= set(browser['passed']), 'missing browser checks')
    for name in ('console-desktop.png','console-mobile.png'):
        data = (directory/name).read_bytes()
        require(len(data)>100 and data.startswith(b'\x89PNG\r\n\x1a\n'), 'missing/invalid screenshot: '+name)
    container = load(directory,'docker-report.json')
    require(container['mode']=='real_docker_compose', 'Docker mode')
    require(container['rows_before_independent_approval']==1206 and container['rows_after_approval_and_restart']==0,
            'Docker target effect')
    require(container['probe']['uid']!=0 and container['probe']['effective_capabilities']==0, 'Docker isolation')
    corpus_sha = load(ROOT/'benchmark','manifest.json')['sha256']
    for split,n,families in [('dev',120,24),('test',80,16)]:
        verify_benchmark(load(directory,'benchmark-'+split+'.json'),n,families,corpus_sha)
    corpus = (directory/'synthetic-cases.jsonl').read_bytes()
    require(hashlib.sha256(corpus).hexdigest()==corpus_sha, 'missing or changed raw corpus')
    print(f'Verified all {tests} JUnit cases, exit receipts, screenshots, Docker and raw benchmark rows.')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',type=Path,default=ROOT/'evidence')
    args=parser.parse_args()
    verify(args.directory)
