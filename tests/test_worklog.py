"""Synthetic evidence only; no personal GitHub logs or online mutations."""
import copy
import csv
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from airlock import private_files
from benchmark import worklog


def issue(number=10, *, api=False):
    value = {
        'number': number, 'url': worklog.ISSUE_PREFIX + str(number),
        'title': 'Synthetic maintenance task', 'body': 'Synthetic fixture, not a real task.',
        'state': 'open', 'created_at': '2026-01-01T10:00:00Z',
        'updated_at': '2026-01-01T10:00:01Z',
    }
    if api:
        value.update({'html_url': value['url'],
                      'url': worklog.API_PREFIX + '/issues/' + str(number),
                      'repository_url': worklog.API_PREFIX,
                      'user': {'login': 'synthetic-person', 'email': 'synthetic@example.invalid'},
                      'node_id': 'I_synthetic', 'assignees': [], 'labels': []})
    return value


def trace():
    result = issue()
    readback = dict(result, observed_at='2026-01-01T10:00:04Z',
                    source_tool='mcp__codex_apps__github_fetch')
    return {
        'schema_version': 1, 'kind': 'authorized_real_project_maintenance_trace',
        'repository': worklog.REPOSITORY, 'user_date': '2026-01-01',
        'authorization': {'source': 'synthetic test authorization', 'statement': 'Test only',
                          'used_scope': 'Synthetic AIRLOCK issue maintenance'},
        'code_baseline': 'a' * 40, 'before': {'issues': []}, 'after': {'issues': [result]},
        'limitations': ['Synthetic test, not an actual operation.'],
        'events': [{
            'task_id': 'synthetic-create', 'business_intent': 'Track synthetic maintenance',
            'authorization_reference': 'synthetic task authorization',
            'execution_path': 'Codex GitHub connector; not AIRLOCK gate',
            'tool': 'mcp__codex_apps__github_create_issue',
            'arguments': {'repository_full_name': worklog.REPOSITORY,
                          'title': result['title'], 'body': result['body']},
            'started_at': '2026-01-01T10:00:00Z', 'finished_at': '2026-01-01T10:00:02Z',
            'response': {'content': [{'type': 'text', 'text': 'Action completed.'}],
                         'isError': False, 'structuredContent': {'issue': result}},
            'readback': readback, 'airlock_protected': False,
            'independent_review_observed': False, 'model_semantic_prediction': None,
            'human_gold': None,
        }],
    }


def source_file(tmp_path, value, name='input.json'):
    path = tmp_path / name
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return path


def load_trace(tmp_path, value=None):
    return worklog.import_source(source_file(tmp_path, value if value is not None else trace()),
                                 'connector-trace', 'synthetic operator authorization')


def load_snapshot(tmp_path, value=None, observed='2026-01-02T10:00:00Z'):
    return worklog.import_source(source_file(tmp_path, value if value is not None else issue(api=True)),
                                 'github-issues', 'synthetic operator authorization', observed_at=observed)


def test_connector_keeps_provenance_timing_and_no_gold(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('no network allowed'))
    data = trace()
    path = source_file(tmp_path, data)
    before = path.read_bytes()
    records = worklog.import_source(path, 'connector-trace', 'synthetic operator authorization')
    assert path.read_bytes() == before
    record = records[0]
    assert record['source_kind'] == 'connector_trace'
    assert record['source_artifact_sha256'] == hashlib.sha256(before).hexdigest()
    assert record['source_record_sha256'] == hashlib.sha256(worklog._json(data['events'][0]).encode()).hexdigest()
    assert record['operation_started_at'] == '2026-01-01T10:00:00Z'
    assert record['operation_finished_at'] == '2026-01-01T10:00:02Z'
    assert record['observed_at'] == '2026-01-01T10:00:04Z'
    assert record['imported_at'] not in {record['observed_at'], record['operation_started_at']}
    assert record['outcome'] == 'created_issue_observed'
    assert record['operation_recorded'] is True and record['airlock_protected'] is False
    assert record['human_approval'] == 'not_observed'
    assert record['human_gold'] is None and record['benchmark_accepted'] is False


def test_snapshot_is_observation_not_execution_or_approval(tmp_path):
    record = load_snapshot(tmp_path)[0]
    assert record['source_kind'] == 'current_issue_snapshot'
    assert record['source_type'] == 'public_snapshot'
    assert record['operation_recorded'] is False
    assert record['operation_started_at'] is record['operation_finished_at'] is None
    assert record['observed_at'] == '2026-01-02T10:00:00Z'
    assert record['source_object_created_at'] == '2026-01-01T10:00:00Z'
    assert record['airlock_protected'] is record['independent_review_observed'] is None
    assert record['human_approval'] == 'unknown' and record['outcome'] == 'current_state_observed'
    assert 'synthetic@example.invalid' not in json.dumps(record)
    assert 'synthetic-person' not in json.dumps(record)
    assert record['correlation_key'] == load_trace(tmp_path)[0]['correlation_key']


@pytest.mark.parametrize('change', ['missing-response', 'error', 'missing-readback', 'changed-body', 'other-number'])
def test_unconfirmed_write_outcomes_remain_unknown(tmp_path, change):
    data = trace()
    event = data['events'][0]
    if change == 'missing-response':
        event['response'] = None
    elif change == 'error':
        event['response']['isError'] = True
    elif change == 'missing-readback':
        del event['readback']
    elif change == 'changed-body':
        event['readback']['body'] = 'Synthetic edit after operation'
    elif change == 'other-number':
        event['readback']['number'] = 11
        event['readback']['url'] = worklog.ISSUE_PREFIX + '11'
    records = load_trace(tmp_path, data)
    assert records[0]['outcome'] == 'unknown'
    manifest = json.loads(worklog.write_pack(records, tmp_path / 'pack.json').read_text())
    assert manifest['unknown_operation_outcomes'] == 1
    assert manifest['observed_created_issues'] == 0


@pytest.mark.parametrize('change', [
    'foreign-repo', 'foreign-args', 'unknown-event', 'unknown-argument', 'noncreate-tool',
    'airlock-claim', 'human-claim', 'human-gold', 'model-label', 'duplicate-task',
    'backwards-time', 'readback-before-operation', 'untrusted-readback-tool', 'string-bool',
])
def test_connector_refuses_unsupported_or_inflated_claims(tmp_path, change):
    data = trace()
    event = data['events'][0]
    if change == 'foreign-repo': data['repository'] = 'someone/else'
    elif change == 'foreign-args': event['arguments']['repository_full_name'] = 'someone/else'
    elif change == 'unknown-event': event['run_shell'] = 'dangerous'
    elif change == 'unknown-argument': event['arguments']['assignees'] = ['someone']
    elif change == 'noncreate-tool': event['tool'] = 'github.update_issue'
    elif change == 'airlock-claim': event['airlock_protected'] = True
    elif change == 'human-claim': event['independent_review_observed'] = True
    elif change == 'human-gold': event['human_gold'] = {'dangerous': False}
    elif change == 'model-label': event['model_semantic_prediction'] = {'dangerous': False}
    elif change == 'duplicate-task': data['events'].append(copy.deepcopy(event))
    elif change == 'backwards-time': event['finished_at'] = '2025-12-01T00:00:00Z'
    elif change == 'readback-before-operation': event['readback']['observed_at'] = event['started_at']
    elif change == 'untrusted-readback-tool': event['readback']['source_tool'] = 'agent assertion'
    elif change == 'string-bool': event['response']['isError'] = 'false'
    with pytest.raises(ValueError):
        load_trace(tmp_path, data)


@pytest.mark.parametrize('change', ['url-userinfo', 'other-repo', 'other-number', 'query', 'http',
                                   'unknown-field', 'pull-request', 'boolean-number', 'bad-state',
                                   'timezone-missing', 'bad-created', 'duplicate-issue'])
def test_snapshot_refuses_foreign_ambiguous_or_nonissue_inputs(tmp_path, change):
    data = issue(api=True)
    if change == 'url-userinfo': data['html_url'] = 'https://github.com@evil.invalid/Changxin-YR/AIRLOCK/issues/10'
    elif change == 'other-repo': data['repository_url'] = 'https://api.github.com/repos/other/project'
    elif change == 'other-number': data['number'] = 11
    elif change == 'query': data['html_url'] += '?token=private'
    elif change == 'http': data['html_url'] = data['html_url'].replace('https:', 'http:')
    elif change == 'unknown-field': data['execute'] = 'shell'
    elif change == 'pull-request': data['pull_request'] = {'url': 'https://example.invalid'}
    elif change == 'boolean-number': data['number'] = True
    elif change == 'bad-state': data['state'] = 'executed'
    elif change == 'timezone-missing': data['created_at'] = '2026-01-01T00:00:00'
    elif change == 'bad-created': data['created_at'] = '2027-01-01T00:00:00Z'
    elif change == 'duplicate-issue': data = [data, copy.deepcopy(data)]
    with pytest.raises(ValueError):
        load_snapshot(tmp_path, data)


def test_snapshot_requires_real_capture_time_and_authorization(tmp_path):
    for observed in (None, '2026-01-01T00:00:00', '2020-01-01T00:00:00Z'):
        with pytest.raises(ValueError):
            load_snapshot(tmp_path, observed=observed)
    with pytest.raises(ValueError):
        worklog.import_source(source_file(tmp_path, issue()), 'github-issues', '', observed_at='2026-01-02T00:00:00Z')
    with pytest.raises(ValueError):
        worklog.import_source(source_file(tmp_path, trace()), 'connector-trace', 'synthetic authorization',
                              observed_at='2026-01-02T00:00:00Z')


@pytest.mark.parametrize('field', ['access_token', 'claim_token', 'headers', 'password', 'client_secret'])
def test_credentials_anywhere_in_source_are_rejected(tmp_path, field):
    data = issue(api=True)
    data['user'][field] = 'synthetic confidential value'
    with pytest.raises(ValueError):
        load_snapshot(tmp_path, data)


def test_duplicate_json_oversized_inputs_and_credential_text_rejected(tmp_path, monkeypatch):
    path = tmp_path / 'invalid.json'
    for text in ('{"number":1,"number":2}', '{"number":NaN}'):
        path.write_text(text)
        with pytest.raises(ValueError):
            worklog.import_source(path, 'github-issues', 'synthetic authorization', observed_at='2026-01-02T00:00:00Z')
    data = issue()
    data['body'] = 'Synthetic exposed key ghp_' + 'x' * 40
    with pytest.raises(ValueError):
        load_snapshot(tmp_path, data)
    monkeypatch.setattr(worklog, 'MAX_BYTES', 10)
    with pytest.raises(ValueError):
        load_snapshot(tmp_path)


def test_private_pack_hashes_empty_labels_and_correlated_counts(tmp_path):
    records = load_trace(tmp_path) + load_snapshot(tmp_path)
    actual = worklog.write_pack(records, tmp_path / 'manifest.json')
    assert actual == tmp_path / 'manifest.json.private' / 'manifest.json'
    manifest = json.loads(actual.read_text(encoding='utf-8'))
    assert manifest['operation_records'] == 1 and manifest['snapshot_observations'] == 1
    assert manifest['cases'] == 2 and manifest['observed_created_issues'] == 1
    assert manifest['family_count'] == manifest['correlated_object_count'] == 1
    assert manifest['human_participants'] == manifest['human_gold_records'] == 0
    assert manifest['human_cohen_kappa'] is manifest['acceptance_metrics'] is None
    for name, expected in manifest['files'].items():
        assert hashlib.sha256((actual.parent / name).read_bytes()).hexdigest() == expected
    with (actual.parent / 'single-annotator.csv').open(encoding='utf-8', newline='') as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 2
    assert all(value == '' for row in rows for key, value in row.items() if key != 'case_id')
    contexts = json.loads((actual.parent / 'case-contexts.json').read_text(encoding='utf-8'))
    assert [r['case_id'] for r in contexts] == manifest['case_ids']
    with pytest.raises(FileExistsError):
        worklog.write_pack(records, tmp_path / 'manifest.json')
    assert json.loads(actual.read_text()) == manifest


def test_duplicate_records_and_failed_private_permissions_write_nothing(tmp_path, monkeypatch):
    records = load_trace(tmp_path)
    with pytest.raises(ValueError):
        worklog.write_pack(records * 2, tmp_path / 'manifest.json')
    def denied(_):
        raise PermissionError('Synthetic ACL failure')
    monkeypatch.setattr(private_files, 'restrict_directory', denied)
    with pytest.raises(PermissionError):
        worklog.write_pack(records, tmp_path / 'denied.json')
    assert list((tmp_path / 'denied.json.private').iterdir()) == []


def test_repeated_create_claims_do_not_multiply_observed_issue_effects(tmp_path):
    data = trace()
    repeated = copy.deepcopy(data['events'][0])
    repeated['task_id'] = 'another-source-claim-for-the-same-issue'
    data['events'].append(repeated)
    records = load_trace(tmp_path, data)
    manifest = json.loads(worklog.write_pack(records, tmp_path / 'manifest.json').read_text())
    assert manifest['cases'] == manifest['operation_records'] == manifest['creation_claim_records'] == 2
    assert manifest['observed_created_issues'] == manifest['correlated_object_count'] == 1


@pytest.mark.parametrize('field,value', [('case_id', '=HYPERLINK("https://example.invalid")'),
                                       ('human_gold', {'dangerous': False}),
                                       ('expected_decision', 'pass'),
                                       ('operation_recorded', True),
                                       ('airlock_protected', True)])
def test_pack_api_refuses_injected_fields_labels_csv_formulas_and_snapshot_claims(tmp_path, field, value):
    records = load_snapshot(tmp_path)
    records[0][field] = value
    with pytest.raises(ValueError):
        worklog.write_pack(records, tmp_path / 'manifest.json')
    assert not (tmp_path / 'manifest.json.private').exists()


def test_cli_emits_only_manifest_path_counts_and_sanitized_error(tmp_path):
    path = source_file(tmp_path, issue(api=True))
    command = [sys.executable, '-m', 'benchmark.worklog', '--format', 'github-issues',
               '--source', str(path), '--authorization-reference', 'synthetic operator authorization',
               '--observed-at', '2026-01-02T00:00:00Z', '--out', str(tmp_path / 'pack.json')]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    emitted = json.loads(result.stdout)
    assert Path(emitted['manifest']).is_file() and emitted['operation_records'] == 0
    assert 'synthetic@example.invalid' not in result.stdout + result.stderr
    again = subprocess.run(command, capture_output=True, text=True, check=False)
    assert again.returncode == 2 and not again.stdout
    path.write_text('{"private text hidden":', encoding='utf-8')
    rejected = subprocess.run(command, capture_output=True, text=True, check=False)
    assert rejected.returncode == 2 and 'private text hidden' not in rejected.stderr
