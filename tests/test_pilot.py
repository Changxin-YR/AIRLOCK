import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from benchmark.pilot import (
    FIELDS, PilotInputError, import_annotations, load_annotations, load_cases,
    prepare, summarize,
)
from benchmark.research import Annotation, annotations_report, bootstrap_mean, study_report


def label(case_id='case-1', **overrides):
    return {'case_id': case_id, 'annotator_id': 'fixture-person', 'source': 'human', 'human': True,
            'independent': False, 'dangerous': False, 'decision': 'need_approval',
            'risk_level': 'low', 'reversibility': 'compensatable', 'impact_units_observed': 1,
            'rationale': 'Synthetic test fixture, not a real human record.', 'uncertainty': ''} | overrides


@pytest.fixture
def cases(tmp_path):
    path = tmp_path / 'case-contexts.json'
    path.write_text(json.dumps([{'case_id': 'case-1', 'business_intent': 'Synthetic test context'},
                               {'case_id': 'case-2', 'business_intent': 'Synthetic test context'}]))
    return path


def write_jsonl(path, rows):
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    return path


def test_private_templates_never_create_human_declarations_or_labels(cases, tmp_path):
    out = tmp_path / 'single-person-pack'
    result = prepare(cases, out)
    assert result['human_records_created'] == 0 and result['acceptance_metrics'] is None
    assert result['case_source']['sha256'] == hashlib.sha256(cases.read_bytes()).hexdigest()
    assert (out / 'case-source.original.json').read_bytes() == cases.read_bytes()
    rows = [json.loads(line) for line in (out / 'single-person.template.jsonl').read_text().splitlines()]
    assert [row['case_id'] for row in rows] == ['case-1', 'case-2']
    assert all(all(value is None for key, value in row.items() if key != 'case_id') for row in rows)
    with (out / 'single-person.template.csv').open(encoding='utf-8-sig', newline='') as source:
        csv_rows = list(csv.DictReader(source))
    assert all(row['human'] == row['source'] == row['annotator_id'] == '' for row in csv_rows)
    original = (out / 'manifest.json').read_bytes()
    with pytest.raises(FileExistsError):
        prepare(cases, out)
    assert (out / 'manifest.json').read_bytes() == original


def test_import_one_person_retains_raw_inputs_provenance_unknowns_and_null_acceptance(cases, tmp_path):
    rows = [label(), label('case-2', risk_level='unknown', reversibility='unknown', impact_units_observed=None)]
    annotations = write_jsonl(tmp_path / 'annotations.jsonl', rows)
    output = tmp_path / 'result'
    report = import_annotations(cases, annotations, output, source_reference='Synthetic unit-test provenance only')
    assert report['status'] == 'SINGLE_HUMAN_PILOT_COMPLETE'
    assert report['declared_human_annotators'] == 1
    assert report['coverage']['complete_annotations'] == 2
    assert report['independent_human_gold_records'] == 0
    assert report['kappa'] is report['human_cohen_kappa'] is report['acceptance_metrics'] is None
    assert report['formal_evaluation_status'] == 'BLOCKED_EXTERNAL'
    assert report['unknown_counts']['reversibility'] == 1 and report['unknown_counts']['impact_units_observed'] == 1
    assert report['provenance']['annotation_input']['sha256'] == hashlib.sha256(annotations.read_bytes()).hexdigest()
    assert report['provenance']['source_reference'] == 'Synthetic unit-test provenance only'
    assert (output / 'annotations.original.jsonl').read_bytes() == annotations.read_bytes()
    normalized = [json.loads(line) for line in (output / 'pilot-annotations.jsonl').read_text().splitlines()]
    assert [row['input_line'] for row in normalized] == [1, 2]
    assert all(row['independent'] is False and len(row['parsed_input_row_sha256']) == 64 for row in normalized)
    with pytest.raises(ValueError):
        Annotation.model_validate(normalized[0])
    before = (output / 'pilot-report.json').read_bytes()
    with pytest.raises(FileExistsError):
        import_annotations(cases, annotations, output, source_reference='A rerun must not overwrite')
    assert (output / 'pilot-report.json').read_bytes() == before


def test_blank_and_empty_annotations_report_missing_input_without_fabricating_humans():
    blank = dict.fromkeys(FIELDS) | {'case_id': 'case-1'}
    report, rows = summarize(['case-1', 'case-2'], [(2, blank)])
    assert report['status'] == 'AWAITING_EXPLICIT_HUMAN_INPUT'
    assert report['declared_human_annotators'] == 0 and report['coverage']['complete_annotations'] == 0
    assert report['coverage']['missing_case_ids'] == ['case-2']
    assert 'human' in report['issues'][0]['missing_fields']
    assert rows[0]['human'] is None and rows[0]['source'] is None
    empty, _ = summarize(['case-1'], [])
    assert empty['coverage']['missing_case_ids'] == ['case-1'] and empty['declared_human_annotators'] == 0


def test_partial_labels_retain_single_declared_person_without_guessing_danger():
    report, rows = summarize(['case-1', 'case-2'], [(1, label(dangerous=None))])
    assert report['status'] == 'SINGLE_HUMAN_PILOT_PARTIAL'
    assert report['declared_human_annotators'] == 1
    assert rows[0]['dangerous'] is None and rows[0]['complete'] is False


def test_legacy_csv_requires_explicit_source_and_does_not_fill_human(tmp_path):
    path = tmp_path / 'legacy.csv'
    fields = [field for field in FIELDS if field != 'source']
    legacy = {key: value for key, value in label().items() if key != 'source'}
    with path.open('w', encoding='utf-8-sig', newline='') as out:
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        writer.writerow({key: str(value).lower() if type(value) is bool else value for key, value in legacy.items()})
    rows, _ = load_annotations(path)
    missing, _ = summarize(['case-1'], rows, csv_input=True)
    assert missing['declared_human_annotators'] == 0 and missing['coverage']['complete_annotations'] == 0
    complete, normalized = summarize(['case-1'], rows, csv_input=True, explicit_source='human')
    assert complete['declared_human_annotators'] == 1 and normalized[0]['human'] is True
    rows[0][1]['human'] = ''
    blank, normalized = summarize(['case-1'], rows, csv_input=True, explicit_source='human')
    assert blank['declared_human_annotators'] == 0 and normalized[0]['human'] is None


@pytest.mark.parametrize('overrides', [
    {'source': 'model', 'human': False}, {'source': 'automation'}, {'source': 'model', 'human': True},
    {'human': False}, {'human': 'true'}, {'human': 1}, {'source': ['human']},
    {'independent_human': False}, {'source': 'human', 'dangerous': 'false'},
])
def test_model_and_malformed_claims_cannot_be_promoted_by_explicit_source(overrides):
    with pytest.raises(PilotInputError):
        summarize(['case-1'], [(1, label(**overrides))], explicit_source='human')


@pytest.mark.parametrize('rows,error', [
    ([(1, label()), (2, label('case-2', annotator_id='fixture-person-two'))], 'single_annotator'),
    ([(1, label()), (2, label())], 'duplicate_annotation'),
    ([(1, label('unknown'))], 'unknown_case'),
])
def test_two_people_duplicate_rows_and_unknown_cases_are_rejected(rows, error):
    with pytest.raises(PilotInputError, match=error):
        summarize(['case-1', 'case-2'], rows)


def test_invalid_import_creates_no_output_or_partial_acceptance(cases, tmp_path):
    input_path = write_jsonl(tmp_path / 'model.jsonl', [label(source='model', human=False)])
    out = tmp_path / 'rejected-result'
    with pytest.raises(PilotInputError, match='nonhuman'):
        import_annotations(cases, input_path, out, source_reference='Unit-test model fixture', explicit_source='human')
    assert not out.exists()
    with pytest.raises(PilotInputError, match='source_reference'):
        import_annotations(cases, input_path, out, source_reference='')


@pytest.mark.parametrize('content,error', [
    ('case_id,case_id\ncase-1,case-1\n', 'header'),
    ('case_id,human\ncase-1,true,extra\n', 'row_width'),
    ('case_id,human\ncase-1\n', 'row_width'),
    ('\n', 'header'),
])
def test_malformed_csv_is_not_silently_repaired(tmp_path, content, error):
    path = tmp_path / 'bad.csv'
    path.write_text(content)
    with pytest.raises(PilotInputError, match=error):
        load_annotations(path)


def test_duplicate_json_fields_and_case_ids_rejected_and_case_jsonl_supported(tmp_path):
    duplicate = tmp_path / 'duplicate.jsonl'
    duplicate.write_text('{"case_id":"case-1","source":"model","source":"human"}\n')
    with pytest.raises(PilotInputError, match='duplicate_json_field'):
        load_annotations(duplicate)
    cases = write_jsonl(tmp_path / 'cases.jsonl', [{'id': 'case-1'}, {'id': 'case-2'}])
    assert load_cases(cases)[0] == ['case-1', 'case-2']
    write_jsonl(cases, [{'id': 'case-1'}, {'id': 'case-1'}])
    with pytest.raises(PilotInputError, match='duplicate_case_id'):
        load_cases(cases)


@pytest.mark.parametrize('identifier', ['=HYPERLINK("https://example.invalid")', '+SUM(1,1)', '-1+2',
                                      '@SUM(1)', '\t=1+1', 'case-1\n=1+1'])
def test_case_ids_cannot_inject_spreadsheet_formulas(tmp_path, identifier):
    path = tmp_path / 'cases.json'
    path.write_text(json.dumps([{'case_id': identifier}]))
    output = tmp_path / 'unsafe-template'
    with pytest.raises(PilotInputError, match='invalid_case_id'):
        prepare(path, output)
    assert not output.exists()


def test_private_directory_permissions_failure_writes_no_personal_rows(cases, tmp_path, monkeypatch):
    from benchmark import pilot
    def reject(_):
        raise PermissionError('fixture access control failure')
    monkeypatch.setattr(pilot, 'restrict_directory', reject)
    output = tmp_path / 'reserved'
    with pytest.raises(PermissionError):
        prepare(cases, output)
    assert output.exists() and list(output.iterdir()) == []


def test_bootstrap_single_person_has_no_population_interval_even_with_many_decisions():
    assert bootstrap_mean([])['ci95'] is None
    one = bootstrap_mean([1500])
    assert one['n'] == 1 and one['mean'] == 1500 and one['ci95'] is None
    assert bootstrap_mean([100, 300], repeats=100)['ci95'] is not None
    session = {'kind': 'airlock-study-v1', 'participant_id': 'synthetic-person', 'source': 'human', 'consent': True,
               'responses': [{'case_id': f'case-{i}', 'arm': 'B' if i % 2 else 'A', 'choice': 'approve',
                              'correct': True, 'visible_ms': 1000 + i} for i in range(20)]}
    result = study_report([session, session])
    assert result['human_participants'] == 1 and len(result['excluded']) == 1
    assert result['status'] == 'OBSERVED_SINGLE_HUMAN_PILOT'
    assert result['paired_time_delta']['ci95'] is None and result['paired_accuracy_delta']['ci95'] is None
    assert result['all_decisions_visible_ms']['n'] == 20 and result['acceptance_metrics'] is None


def test_original_annotations_report_still_requires_exactly_two_independent_people():
    from types import SimpleNamespace
    one = Annotation(case_id='case-1', annotator_id='synthetic-person', human=True, independent=True,
                     dangerous=False, decision='pass', rationale='Synthetic regression fixture only.')
    with pytest.raises(ValueError, match='exactly two'):
        annotations_report([SimpleNamespace(id='case-1')], [one])


def test_cli_prepare_and_import_leave_blank_template_unclaimed(cases, tmp_path):
    project = Path(__file__).resolve().parents[1]
    out = tmp_path / 'cli-template'
    prepare_run = subprocess.run([sys.executable, '-m', 'benchmark.pilot', 'prepare', '--cases', str(cases),
                                  '--output', str(out)], cwd=project, capture_output=True, text=True, timeout=30)
    assert prepare_run.returncode == 0, prepare_run.stderr
    result = tmp_path / 'cli-result'
    run = subprocess.run([sys.executable, '-m', 'benchmark.pilot', 'import', '--cases', str(cases),
                          '--annotations', str(out / 'single-person.template.csv'), '--source-reference', 'Unit-test fixture only',
                          '--output', str(result)], cwd=project, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)['status'] == 'AWAITING_EXPLICIT_HUMAN_INPUT'
    summary = json.loads((result / 'pilot-report.json').read_text())
    assert summary['declared_human_annotators'] == 0 and summary['acceptance_metrics'] is None
    duplicate = subprocess.run([sys.executable, '-m', 'benchmark.pilot', 'prepare', '--cases', str(cases),
                                '--output', str(out)], cwd=project, capture_output=True, text=True, timeout=30)
    assert duplicate.returncode == 2 and json.loads(duplicate.stdout)['status'] == 'REJECTED'
