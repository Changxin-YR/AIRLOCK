"""Counterexamples use the preserved real ledger, never replace its evidence."""
import xml.etree.ElementTree as ET

import pytest

from docs.acceptance.validate_matrix import ROOT, read_json, validate


@pytest.fixture
def ledger():
    return (read_json(ROOT / 'docs/acceptance/COMPLETION_MATRIX.json'),
            read_json(ROOT / 'docs/acceptance/AIRLOCK-acceptance-targets.json'))


def test_acceptance_ledger_positive_control_keeps_external_blockers(ledger):
    result = validate(*ledger)
    assert result['target_records'] == 126
    assert result['original_goals_all_satisfied'] is False
    assert result['counts']['verification']['BLOCKED_EXTERNAL'] > 0


@pytest.mark.parametrize('mutation,expected', [
    ('count', 'summary counts'), ('all_goals', 'all-goals'), ('row_sha', 'row SHA'),
    ('unrecorded', 'missing process receipt'), ('ci_only', 'no successful frozen receipt'),
    ('parent_commands', 'parent command'), ('parent_exits', 'parent exit'),
    ('parent_flag', 'parent aggregation'), ('criterion', 'criterion changed'),
    ('absolute_path', 'inside repository'), ('traversal', 'inside repository'),
    ('manual_function', 'invalid manual evidence'),
])
def test_acceptance_rejects_false_closure_mutations(ledger, mutation, expected):
    report, index = ledger
    row = report['targets'][0]
    parent = next(item for item in report['targets'] if item['id'] == 'C1')
    if mutation == 'count': report['counts']['verification']['PASS'] = 126
    elif mutation == 'all_goals': report['original_goals_all_satisfied'] = True
    elif mutation == 'row_sha': row['tested_commit_sha'] = '0' * 40
    elif mutation == 'unrecorded': row['commands'] = [{'command': ['never', 'executed']}]
    elif mutation == 'ci_only':
        row['commands'] = [{'command': 'CI green', 'tested_commit_sha': report['tested_commit_sha'],
                            'run_url': 'https://github.com/Changxin-YR/AIRLOCK/actions/runs/123'}]
    elif mutation == 'parent_commands': parent['commands'] = [{'child_id': 'C1.1', 'commands': []}]
    elif mutation == 'parent_exits': parent['exit_codes'] = []
    elif mutation == 'parent_flag': parent['derived_parent'] = False
    elif mutation == 'criterion': row['criterion'] = 'Only require the tool to exit zero.'
    elif mutation == 'absolute_path': row['evidence'] = [(ROOT / 'README.md').as_posix()]
    elif mutation == 'traversal': row['evidence'] = ['../airlock/README.md']
    elif mutation == 'manual_function':
        row['commands'] = [{'command': 'manual says safe', 'process_exit_code_applicable': False,
                            'receipt': row['evidence'][0]}]
    with pytest.raises(ValueError, match=expected):
        validate(report, index)


@pytest.mark.parametrize('tag', ['failure', 'error', 'skipped'])
def test_acceptance_rejects_junit_failure_even_when_test_names_match(ledger, monkeypatch, tag):
    original = ET.parse
    def altered(path):
        tree = original(path)
        ET.SubElement(next(tree.iter('testcase')), tag)
        return tree
    monkeypatch.setattr(ET, 'parse', altered)
    with pytest.raises(ValueError, match='JUnit failed'):
        validate(*ledger)


def test_acceptance_rejects_duplicate_json_keys(tmp_path):
    path = tmp_path / 'report.json'
    path.write_text('{"original_goals_all_satisfied":false,"original_goals_all_satisfied":true}')
    with pytest.raises(ValueError, match='duplicate JSON key'):
        read_json(path)


def test_acceptance_rejects_changed_archived_log(ledger, monkeypatch):
    from pathlib import Path
    original = Path.read_bytes
    def altered(path):
        data = original(path)
        return data + b' altered' if path.name == 'pytest.log' else data
    monkeypatch.setattr(Path, 'read_bytes', altered)
    with pytest.raises(ValueError, match='inventory hash mismatch'):
        validate(*ledger)
