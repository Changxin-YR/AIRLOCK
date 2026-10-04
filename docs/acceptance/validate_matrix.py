"""Validate both directions of acceptance evidence links, not scope judgments."""
from pathlib import Path, PurePosixPath
from collections import Counter
import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
MANUAL_TARGETS = {'G3', 'G4', 'E1', 'E2', 'E4', 'D4', 'W1'}
SHA = re.compile(r'[0-9a-f]{40}')
RUN = re.compile(r'https://github.com/Changxin-YR/AIRLOCK/actions/runs/[0-9]+')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs)


def validate(report, index, root=ROOT):
    root = root.resolve()

    def file(name, allow_directory=False):
        require(isinstance(name, str) and name and chr(92) not in name, 'invalid evidence path')
        relative = PurePosixPath(name)
        require(not relative.is_absolute() and '..' not in relative.parts and ':' not in name,
                'evidence path must stay inside repository')
        path = (root / name).resolve()
        require(path.is_relative_to(root) and (path.is_file() or (allow_directory and path.is_dir())),
                'missing or unsafe file: ' + name)
        return path

    targets = report['targets']
    originals = {row['id']: row for row in index['targets']}
    by_id = {row['id']: row for row in targets}
    require(len(targets) == len(by_id) == index['target_count'] == 126, 'missing or duplicate IDs')
    require(set(by_id) == set(originals), 'changed target set')
    require(report['target_count'] == len(targets), 'target count mismatch')
    require(SHA.fullmatch(report['tested_commit_sha']) is not None, 'invalid report SHA')
    counts = {'implementation': dict(Counter(row['implementation_status'] for row in targets)),
              'verification': dict(Counter(row['verification_status'] for row in targets))}
    require(report['counts'] == counts, 'summary counts disagree with target rows')
    require(type(report['original_goals_all_satisfied']) is bool, 'invalid completion flag')
    if report['original_goals_all_satisfied']:
        require(all(row['implementation_status'] == 'IMPLEMENTED' and
                    row['verification_status'] == 'PASS' and not row['uncovered_scope']
                    for row in targets), 'all-goals claim contradicts remaining gaps')

    junit_path = file(report['junit_evidence'])
    tree = ET.parse(junit_path)
    cases = list(tree.iter('testcase'))
    require(bool(cases), 'JUnit has no tests')
    junit = {case.get('classname', '') + '::' + case.get('name', '') for case in cases}
    require(len(junit) == len(cases), 'duplicate JUnit test ID')
    require(all(not any(case.find(tag) is not None for tag in ('failure', 'error', 'skipped'))
                for case in cases), 'JUnit failed/error/skipped')
    for suite in tree.iter('testsuite'):
        require(all(int(suite.get(key, '0')) == 0 for key in ('failures', 'errors', 'skipped')),
                'JUnit suite failed/error/skipped')
    junit_receipt = read_json(junit_path.parent / 'pytest.log.status.json')
    require(junit_receipt['tested_commit_sha'] == report['tested_commit_sha'] and
            junit_receipt['tracked_source_dirty'] is False and junit_receipt['exit_code'] == 0,
            'JUnit source receipt mismatch')
    require('-m' in junit_receipt['command'] and 'pytest' in junit_receipt['command'],
            'JUnit receipt is not pytest')

    manifest = read_json(junit_path.parent / 'manifest.json')
    require(manifest['commit'] == report['tested_commit_sha'], 'manifest source mismatch')

    def archived(path):
        if path.parent == junit_path.parent:
            entry = manifest['files'].get(path.name)
            require(entry is not None, 'file missing from CI inventory: ' + path.name)
            data = path.read_bytes()
            require(entry['bytes'] == len(data) and entry['sha256'] == hashlib.sha256(data).hexdigest(),
                    'CI inventory hash mismatch: ' + path.name)
            return True
        return False
    archived(junit_path)
    archived(junit_path.parent / 'pytest.log.status.json')
    checked_receipts = set()
    for row in targets:
        identifier = row['id']
        original = originals[identifier]
        require(set(index['required_result_fields']) <= row.keys(), identifier + ': missing fields')
        require(row['implementation_status'] in index['allowed_implementation_statuses'], identifier + ': implementation enum')
        require(row['verification_status'] in index['allowed_verification_statuses'], identifier + ': verification enum')
        require(row['parent_id'] == original['parent_id'], identifier + ': parent changed')
        require(row['criterion'] == original.get('criterion', original.get('title')), identifier + ': criterion changed')
        require(row['tested_commit_sha'] == report['tested_commit_sha'], identifier + ': row SHA mismatch')
        require(row['scope'] and row['commands'] and row['evidence'] and row['code_references'], identifier + ': missing scope or evidence')
        for name in row['code_references']:
            file(name, allow_directory=True)
        for name in row['evidence']:
            file(name)
        require(set(row['test_ids']) <= junit, identifier + ': unknown test ID')
        children = [child for child in targets if child['parent_id'] == identifier]
        require(bool(row.get('derived_parent')) == bool(children), identifier + ': parent aggregation missing')
        if children:
            require(row['commands'] == [{'child_id': child['id'], 'commands': child['commands']} for child in children],
                    identifier + ': parent command links differ from children')
            require(row['exit_codes'] == [{'child_id': child['id'], 'exit_codes': child['exit_codes']} for child in children],
                    identifier + ': parent exit links differ from children')
            for key in ('evidence', 'test_ids', 'code_references'):
                require(set(row[key]) == {item for child in children for item in child[key]},
                        identifier + ': parent ' + key + ' differs from children')
            if row['implementation_status'] == 'IMPLEMENTED':
                require(all(child['implementation_status'] == 'IMPLEMENTED' for child in children),
                        identifier + ': overstated parent implementation')
            if row['verification_status'] == 'PASS':
                require(all(child['implementation_status'] == 'IMPLEMENTED' and child['verification_status'] == 'PASS'
                            for child in children), identifier + ': overstated parent')
            continue
        if row['verification_status'].startswith('BLOCKED'):
            require(row['blocker'] and row['unblock_input'] and row['retest_command'], identifier + ': unexplained blocker')
        frozen = False
        manual = False
        for command in row['commands']:
            receipt_name = command.get('receipt')
            if command.get('process_exit_code_applicable') is False:
                require(identifier in MANUAL_TARGETS and isinstance(command.get('command'), str)
                        and receipt_name in row['evidence'], identifier + ': invalid manual evidence')
                file(receipt_name)
                manual = True
                continue
            if receipt_name is None:
                # A CI link supplements actual receipts, never establishes PASS.
                require(RUN.fullmatch(command.get('run_url', '')) is not None and
                        SHA.fullmatch(command.get('tested_commit_sha', '')) is not None,
                        identifier + ': missing process receipt')
                continue
            require(isinstance(command['command'], list) and bool(command['command']), identifier + ': executable command required')
            path = file(receipt_name)
            status = read_json(path)
            require(status['command'] == command['command'], identifier + ': command mismatch')
            require(status['tested_commit_sha'] == command['tested_commit_sha'], identifier + ': receipt SHA mismatch')
            require(type(status['exit_code']) is int and type(status['tracked_source_dirty']) is bool,
                    identifier + ': invalid receipt types')
            require(command.get('tracked_source_dirty') is status['tracked_source_dirty'], identifier + ': concealed source status')
            require(any(type(item.get('exit_code')) is int and item['exit_code'] == status['exit_code']
                        for item in row['exit_codes']), identifier + ': discarded failure')
            require(receipt_name.endswith('.log.status.json'), identifier + ': process log binding missing')
            raw_name = receipt_name[:-len('.status.json')]
            require(raw_name in row['evidence'], identifier + ': raw log absent from evidence')
            raw_log = file(raw_name)
            require(raw_log.stat().st_size > 0, identifier + ': empty raw log')
            receipt_archived = archived(path)
            log_archived = archived(raw_log)
            if status['tracked_source_dirty']:
                require(command.get('evidence_role') == 'supporting_precommit_experiment', identifier + ': dirty experiment mislabeled')
            elif (status['tested_commit_sha'] == report['tested_commit_sha'] and status['exit_code'] == 0
                  and receipt_archived and log_archived):
                frozen = True
            checked_receipts.add(receipt_name)
        require(frozen or manual, identifier + ': no successful frozen receipt or applicable source review')
    corpus = file('evidence/full-audit-20261002/final/synthetic-cases.jsonl')
    require(hashlib.sha256(corpus.read_bytes()).hexdigest() == '243854b51e7039324de4c31fa7a67af1a98ddc48b9c9edfbbac581a2c2f73af7',
            'corpus changed')
    return {'target_records': len(targets), 'unique_receipts_checked': len(checked_receipts),
            'counts': counts, 'original_goals_all_satisfied': report['original_goals_all_satisfied'],
            'meaning': 'bidirectional structure and provenance only; not functional or human acceptance'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--matrix', type=Path, default=ROOT / 'docs/acceptance/COMPLETION_MATRIX.json')
    args = parser.parse_args()
    print(json.dumps(validate(read_json(args.matrix), read_json(ROOT / 'docs/acceptance/AIRLOCK-acceptance-targets.json')),
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
