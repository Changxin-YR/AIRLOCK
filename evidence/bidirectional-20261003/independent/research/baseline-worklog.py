"""Read local authorized GitHub evidence into an unlabelled private worklog.

No GitHub calls, mutations, labels or approval decisions are performed here.
Connector histories are source claims, not cryptographically attested traces.
Current issue snapshots describe observations, never newly executed operations.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat

from airlock.private_files import reserve_private_output


REPOSITORY = 'Changxin-YR/AIRLOCK'
ISSUE_PREFIX = f'https://github.com/{REPOSITORY}/issues/'
API_PREFIX = f'https://api.github.com/repos/{REPOSITORY}'
MAX_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 1000
FAMILY = 'airlock-github-issue-maintenance'
CSV_FIELDS = ('case_id', 'annotator_id', 'source', 'human', 'independent',
              'dangerous', 'decision', 'risk_level', 'reversibility',
              'impact_units_observed', 'rationale', 'uncertainty')
SECRET_KEYS = {'access_token', 'refresh_token', 'id_token', 'client_secret',
               'claim_token', 'api_key', 'password', 'authorization_header',
               'headers', 'cookie', 'cookies', 'private_key'}
SECRET_PATTERN = re.compile(r'(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}'
                            r'|Bearer\s+[A-Za-z0-9_.~-]{24,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)')
ISSUE_FIELDS = {
    'url', 'repository_url', 'labels_url', 'comments_url', 'events_url', 'html_url',
    'id', 'node_id', 'number', 'issue_number', 'title', 'user', 'labels', 'state',
    'locked', 'assignees', 'milestone', 'comments', 'created_at', 'updated_at',
    'closed_at', 'assignee', 'author_association', 'active_lock_reason',
    'sub_issues_summary', 'issue_dependencies_summary', 'body', 'closed_by',
    'reactions', 'timeline_url', 'performed_via_github_app', 'state_reason',
    'pinned_comment', 'display_url', 'display_title', 'body_html', 'body_text',
    'type', 'issue_field_values', 'parent_issue_url', 'draft',
}
RECORD_FIELDS = {
    'schema_version', 'case_id', 'repository', 'family_id', 'split', 'correlation_key',
    'source_type', 'source_kind', 'source_artifact_sha256', 'source_record_sha256',
    'source_reference', 'authorization_reference', 'authorization_basis', 'imported_at',
    'runtime_attestation', 'human_approval', 'human_gold', 'model_prediction',
    'benchmark_accepted', 'source_task_id', 'source_authorization_reference',
    'authorization_context', 'code_baseline', 'task_family', 'business_intent', 'tool',
    'arguments', 'execution_path', 'airlock_protected', 'independent_review_observed',
    'operation_started_at', 'operation_finished_at', 'observed_at',
    'source_object_created_at', 'source_object_updated_at', 'outcome', 'result',
    'operation_recorded', 'limitations',
}


def _json(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False)


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        raise ValueError('unsupported or missing source fields')


def _text(value, maximum=1000, *, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError('invalid source text')
    if any(ord(c) < 32 and c not in '\n\r\t' for c in value):
        raise ValueError('control character in source text')
    return value


def _timestamp(value):
    value = _text(value, 80)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('invalid source timestamp') from None
    if parsed.tzinfo is None:
        raise ValueError('source timestamps require an explicit timezone')
    return parsed.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _safe_tree(value, depth=0):
    if depth > 20:
        raise ValueError('source nesting exceeds limit')
    if isinstance(value, dict):
        for key, item in value.items():
            if key.casefold() in SECRET_KEYS:
                raise ValueError('credential or raw transport field is not permitted')
            _safe_tree(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_RECORDS:
            raise ValueError('source list exceeds limit')
        for item in value:
            _safe_tree(item, depth + 1)
    elif isinstance(value, str):
        _text(value, 100_000, empty=True)
        if SECRET_PATTERN.search(value):
            raise ValueError('possible credential content is not permitted')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def _load(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('source must be a regular local file')
    with path.open('rb') as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError('source must be a regular local file')
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('source file exceeds limit')
    value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON value')))
    _safe_tree(value)
    return value, _hash(raw)


def _issue(value, *, readback=False):
    extra = {'observed_at', 'source_tool'} if readback else set()
    _keys(value, {'title', 'body', 'state', 'created_at', 'updated_at'}, ISSUE_FIELDS | extra)
    number = value.get('number', value.get('issue_number'))
    if type(number) is not int or not 1 <= number <= 2**53 - 1:
        raise ValueError('invalid issue number')
    if 'number' in value and 'issue_number' in value and value['number'] != value['issue_number']:
        raise ValueError('inconsistent issue numbers')
    expected = ISSUE_PREFIX + str(number)
    url = value.get('html_url', value.get('url'))
    if url != expected:
        raise ValueError('issue URL must bind the fixed repository and number')
    if 'url' in value and value['url'] not in {expected, API_PREFIX + '/issues/' + str(number)}:
        raise ValueError('issue API URL does not match repository')
    if 'repository_url' in value and value['repository_url'] != API_PREFIX:
        raise ValueError('issue belongs to another repository')
    if value.get('display_url', expected) != expected or value['state'] not in ('open', 'closed'):
        raise ValueError('invalid issue state or display URL')
    created = _timestamp(value['created_at'])
    updated = _timestamp(value['updated_at'])
    if datetime.fromisoformat(updated) < datetime.fromisoformat(created):
        raise ValueError('issue update precedes creation')
    return {'number': number, 'url': expected, 'title': _text(value['title'], 256),
            'body': _text('' if value['body'] is None else value['body'], 65_536, empty=True),
            'state': value['state'], 'created_at': created, 'updated_at': updated}


def _base(source_hash, authorization, imported_at, source_kind, correlation, identity, source_record):
    return {
        'schema_version': 1, 'case_id': 'worklog-' + _hash(_json(identity).encode())[:24],
        'repository': REPOSITORY, 'family_id': FAMILY, 'split': 'unassigned',
        'correlation_key': correlation, 'source_type': 'authorized_log' if source_kind == 'connector_trace' else 'public_snapshot',
        'source_kind': source_kind, 'source_artifact_sha256': source_hash,
        'source_record_sha256': _hash(_json(source_record).encode()),
        'source_reference': 'local-artifact:sha256:' + source_hash,
        'authorization_reference': authorization,
        'authorization_basis': 'operator_supplied_reference; not independently authenticated by importer',
        'imported_at': imported_at, 'runtime_attestation': 'unverified_local_source',
        'human_approval': 'unknown', 'human_gold': None, 'model_prediction': None,
        'benchmark_accepted': False,
    }


def _connector(data, source_hash, authorization, imported_at):
    _keys(data, {'schema_version', 'kind', 'user_date', 'repository', 'authorization',
                 'code_baseline', 'before', 'events', 'after', 'limitations'})
    if type(data['schema_version']) is not int or data['schema_version'] != 1 or data['kind'] != 'authorized_real_project_maintenance_trace' or data['repository'] != REPOSITORY:
        raise ValueError('unsupported connector trace version or repository')
    _keys(data['authorization'], {'source', 'statement', 'used_scope'})
    for value in data['authorization'].values():
        _text(value, 4000)
    if not re.fullmatch('[0-9a-f]{40}', data['code_baseline']):
        raise ValueError('invalid code baseline')
    if not isinstance(data['events'], list) or not 1 <= len(data['events']) <= MAX_RECORDS:
        raise ValueError('nonempty bounded connector events required')
    records = []
    seen = set()
    for event in data['events']:
        _keys(event, {'task_id', 'business_intent', 'authorization_reference', 'execution_path',
                      'tool', 'arguments', 'started_at', 'finished_at', 'response',
                      'independent_review_observed', 'airlock_protected',
                      'model_semantic_prediction', 'human_gold'}, {'readback'})
        task_id = _text(event['task_id'], 100)
        if task_id in seen:
            raise ValueError('duplicate connector task ID')
        seen.add(task_id)
        if event['tool'] != 'mcp__codex_apps__github_create_issue' or event['execution_path'] != 'Codex GitHub connector; not AIRLOCK gate':
            raise ValueError('unsupported connector execution path')
        if event['airlock_protected'] is not False or event['independent_review_observed'] is not False:
            raise ValueError('this trace format cannot establish AIRLOCK or independent human approval')
        if event['model_semantic_prediction'] is not None or event['human_gold'] is not None:
            raise ValueError('worklog import requires an unlabelled source')
        args = event['arguments']
        _keys(args, {'repository_full_name', 'title', 'body'})
        if args['repository_full_name'] != REPOSITORY:
            raise ValueError('connector arguments target another repository')
        _text(args['title'], 256)
        _text(args['body'], 65_536, empty=True)
        start, finish = _timestamp(event['started_at']), _timestamp(event['finished_at'])
        if datetime.fromisoformat(finish) < datetime.fromisoformat(start):
            raise ValueError('connector completion precedes start')
        readback = event.get('readback')
        observed = _issue(readback, readback=True) if readback is not None else None
        observed_at = _timestamp(readback['observed_at']) if readback is not None else None
        if readback is not None:
            if readback.get('source_tool') != 'mcp__codex_apps__github_fetch' or datetime.fromisoformat(observed_at) < datetime.fromisoformat(finish):
                raise ValueError('invalid connector readback time or tool')
        response_issue = None
        response = event['response']
        if response is not None:
            _keys(response, {'content', 'isError'}, {'structuredContent', '_meta'})
            if type(response['isError']) is not bool:
                raise ValueError('invalid connector error flag')
            if not isinstance(response['content'], list):
                raise ValueError('invalid normalized connector content')
            for content in response['content']:
                _keys(content, {'type', 'text'}, {'annotations', '_meta'})
                if content['type'] != 'text':
                    raise ValueError('only normalized text connector content is supported')
                _text(content['text'], 100_000, empty=True)
            structured = response.get('structuredContent')
            if structured is not None:
                _keys(structured, {'issue'}, {'url', 'title', 'display_url', 'display_title'})
                response_issue = _issue(structured['issue'])
                for field in ('url', 'display_url'):
                    if structured.get(field, response_issue['url']) != response_issue['url']:
                        raise ValueError('inconsistent connector response URL')
        bound = (response is not None and not response['isError'] and response_issue is not None
                 and observed is not None and response_issue['number'] == observed['number']
                 and all(observed[k] == response_issue[k] == args[k] for k in ('title', 'body')))
        number = observed['number'] if observed else response_issue['number'] if response_issue else None
        correlation = f'github-issue:{REPOSITORY}:{number}' if number else 'connector-task:' + task_id
        record = _base(source_hash, authorization, imported_at, 'connector_trace', correlation,
                       {'task_id': task_id, 'started_at': start, 'arguments': args}, event)
        record.update({
            'source_task_id': task_id, 'source_authorization_reference': _text(event['authorization_reference'], 4000),
            'authorization_context': data['authorization'], 'code_baseline': data['code_baseline'],
            'task_family': 'github.issue.create', 'business_intent': _text(event['business_intent'], 4000),
            'tool': event['tool'], 'arguments': args, 'execution_path': event['execution_path'],
            'airlock_protected': False, 'independent_review_observed': False,
            'human_approval': 'not_observed', 'operation_started_at': start,
            'operation_finished_at': finish, 'observed_at': observed_at,
            'source_object_created_at': observed['created_at'] if observed else None,
            'source_object_updated_at': observed['updated_at'] if observed else None,
            'outcome': 'created_issue_observed' if bound else 'unknown', 'result': observed,
            'operation_recorded': True, 'limitations': [
                'Normalized local connector trace, not raw wire capture or independent attestation.',
                'No AIRLOCK protection or independent human approval is established.',
                'A connector error or missing/mismatched readback leaves the write outcome unknown.',
            ],
        })
        records.append(record)
    return records


def import_source(source, source_format, authorization_reference, *, observed_at=None):
    """Validate one local source. Never infer authorization from a GitHub URL."""
    authorization = _text(authorization_reference, 4000)
    data, source_hash = _load(source)
    imported = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    if source_format == 'connector-trace':
        if observed_at is not None:
            raise ValueError('connector observation times must come from recorded readbacks')
        return _connector(data, source_hash, authorization, imported)
    if source_format != 'github-issues':
        raise ValueError('unsupported source format')
    observation = _timestamp(observed_at)
    issues = data if isinstance(data, list) else [data]
    if not 1 <= len(issues) <= MAX_RECORDS:
        raise ValueError('nonempty bounded snapshot list required')
    result = []
    for raw_issue in issues:
        issue = _issue(raw_issue)
        if datetime.fromisoformat(observation) < datetime.fromisoformat(issue['updated_at']):
            raise ValueError('snapshot observation precedes its last update')
        record = _base(source_hash, authorization, imported, 'current_issue_snapshot',
                       f"github-issue:{REPOSITORY}:{issue['number']}",
                       {'issue': issue, 'observed_at': observation}, raw_issue)
        record.update({
            'source_task_id': None, 'source_authorization_reference': None,
            'authorization_context': {'source': 'operator import', 'statement': authorization,
                                      'used_scope': 'read-only private research import'},
            'code_baseline': None, 'task_family': 'github.issue.observe',
            'business_intent': f"Observe existing issue #{issue['number']}: {issue['title']}",
            'tool': 'github.issue.snapshot', 'arguments': {'repository_full_name': REPOSITORY,
                                                          'number': issue['number']},
            'execution_path': 'current issue snapshot; original operation path unknown',
            'airlock_protected': None, 'independent_review_observed': None,
            'operation_started_at': None, 'operation_finished_at': None,
            'observed_at': observation, 'source_object_created_at': issue['created_at'],
            'source_object_updated_at': issue['updated_at'], 'operation_recorded': False,
            'outcome': 'current_state_observed', 'result': issue,
            'limitations': ['Snapshot is not a runtime trace; created_at is object metadata, not a captured invocation.',
                            'Original task intent, execution outcome, AIRLOCK and human approval are unknown.'],
        })
        result.append(record)
    if len({r['correlation_key'] for r in result}) != len(result):
        raise ValueError('duplicate issue snapshots in one source')
    return result


def write_pack(records, requested_path):
    """Reserve a private directory exclusively; write completion manifest last."""
    for record in records:
        _keys(record, RECORD_FIELDS)
        _safe_tree(record)
        if (record['repository'] != REPOSITORY or record['family_id'] != FAMILY
                or record['split'] != 'unassigned' or record['schema_version'] != 1
                or not re.fullmatch(r'worklog-[0-9a-f]{24}', record['case_id'])
                or record['human_gold'] is not None or record['model_prediction'] is not None
                or record['benchmark_accepted'] is not False):
            raise ValueError('invalid or labelled worklog record')
        for field in ('source_artifact_sha256', 'source_record_sha256'):
            if not re.fullmatch('[0-9a-f]{64}', record[field]):
                raise ValueError('invalid worklog provenance hash')
        if record['source_kind'] == 'connector_trace':
            if (record['operation_recorded'] is not True or record['airlock_protected'] is not False
                    or record['independent_review_observed'] is not False
                    or record['human_approval'] != 'not_observed'
                    or record['outcome'] not in ('created_issue_observed', 'unknown')):
                raise ValueError('invalid connector worklog claims')
        elif record['source_kind'] == 'current_issue_snapshot':
            if (record['operation_recorded'] is not False or record['airlock_protected'] is not None
                    or record['independent_review_observed'] is not None
                    or record['human_approval'] != 'unknown'
                    or record['outcome'] != 'current_state_observed'
                    or record['operation_started_at'] is not None or record['operation_finished_at'] is not None):
                raise ValueError('snapshots cannot establish runtime operation or approval')
        else:
            raise ValueError('unknown worklog source category')
    if not records or len({r['case_id'] for r in records}) != len(records):
        raise ValueError('nonempty unique worklog records required')
    contexts = [dict(r, label_question='Assess the stated task and available evidence. Leave uncertainty explicit; no gold label is supplied.') for r in records]
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, CSV_FIELDS, lineterminator='\n')
    writer.writeheader()
    writer.writerows({'case_id': r['case_id']} for r in records)
    payloads = {
        'worklog.jsonl': ''.join(_json(r) + '\n' for r in records),
        'case-contexts.json': json.dumps(contexts, ensure_ascii=False, indent=2) + '\n',
        'single-annotator.csv': stream.getvalue(),
        'README.txt': ('Private unlabelled AIRLOCK GitHub worklog. Keep this directory out of Git.\n'
                       'The importer reads local files only and does not call GitHub or execute requests.\n'
                       'Connector events and issue snapshots have different source_kind values. Snapshots add zero operation records.\n'
                       'All examples share one project-maintenance family; correlation_key groups the same issue across observations.\n'
                       'operation_records counts source invocation entries; observed_created_issues counts distinct matched issue objects.\n'
                       'Only an actual consenting participant may fill the single-annotator CSV. Do not prefill human/independent/source.\n'
                       'A single person is pilot feedback, not independent double annotation, Cohen kappa, gold or causal A/B proof.\n'
                       'Model responses belong in separately marked model-only outputs. Missing approval remains unknown/not_observed.\n'
                       'Labels and runtime outcomes are not interchangeable. This pack grants no execution authority.\n'),
    }
    with reserve_private_output(requested_path) as (actual, destination):
        if actual.name in payloads:
            raise ValueError('manifest filename conflicts with pack content')
        for name, content in payloads.items():
            with open(actual.parent / name, 'x', encoding='utf-8', newline='',
                      opener=lambda filename, flags: os.open(filename, flags, 0o600)) as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
        manifest = {
            'schema_version': 1, 'kind': 'private_unlabelled_worklog_pack', 'repository': REPOSITORY,
            'case_ids': [r['case_id'] for r in records], 'cases': len(records),
            'source_artifact_sha256': sorted({r['source_artifact_sha256'] for r in records}),
            'operation_records': sum(r['operation_recorded'] for r in records),
            'snapshot_observations': sum(r['source_kind'] == 'current_issue_snapshot' for r in records),
            'creation_claim_records': sum(r['outcome'] == 'created_issue_observed' for r in records),
            'observed_created_issues': len({r['correlation_key'] for r in records if r['outcome'] == 'created_issue_observed'}),
            'unknown_operation_outcomes': sum(r['operation_recorded'] and r['outcome'] == 'unknown' for r in records),
            'family_count': len({r['family_id'] for r in records}),
            'correlated_object_count': len({r['correlation_key'] for r in records}),
            'human_gold_records': 0, 'human_participants': 0, 'benchmark_accepted': False,
            'human_cohen_kappa': None, 'acceptance_metrics': None,
            'files': {name: _hash(content.encode('utf-8')) for name, content in payloads.items()},
        }
        destination.write(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--format', choices=['connector-trace', 'github-issues'], required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--authorization-reference', required=True)
    parser.add_argument('--observed-at', help='Actual capture time for an issue snapshot, with timezone')
    parser.add_argument('--out', type=Path, required=True, help='Private manifest reservation path; use ignored var/')
    args = parser.parse_args()
    try:
        records = import_source(args.source, args.format, args.authorization_reference, observed_at=args.observed_at)
        actual = write_pack(records, args.out)
    except (ValueError, OSError, TypeError, KeyError, RecursionError) as error:
        # Source content and validation inputs may contain private text: never echo them.
        parser.exit(2, f'worklog import rejected ({type(error).__name__}); check source schema and private output reservation\n')
    print(json.dumps({'manifest': str(actual), 'cases': len(records),
                      'operation_records': sum(r['operation_recorded'] for r in records),
                      'snapshot_observations': sum(not r['operation_recorded'] for r in records)}))


if __name__ == '__main__':
    main()
