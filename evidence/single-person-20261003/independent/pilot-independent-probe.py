"""Synthetic self-declarations for parser boundary tests only; no real human labels."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmark.pilot import PilotInputError, import_annotations, prepare, summarize
from benchmark.research import Annotation

checks = []
def rejected(name, thunk):
    try:
        thunk()
    except (PilotInputError, ValueError):
        checks.append(name)
    else:
        raise AssertionError(name)

row = {'case_id': 'probe:1', 'annotator_id': 'synthetic-declaration', 'source': 'human', 'human': True,
       'independent': False, 'dangerous': None, 'decision': 'block', 'risk_level': 'unknown',
       'reversibility': 'unknown', 'rationale': 'Synthetic parser probe, not an actual human record.'}
for claim in ({'source': 'model'}, {'human': False}, {'human': 1}, {'source': 'automation'}):
    rejected('source_override_' + str(claim), lambda claim=claim: summarize(['probe:1'], [(1, row | claim)], explicit_source='human'))
rejected('unknown_id', lambda: summarize(['probe:2'], [(1, row)]))
rejected('duplicate_annotation', lambda: summarize(['probe:1'], [(1, row), (2, row)]))
rejected('unknown_field', lambda: summarize(['probe:1'], [(1, row | {'gold': True})]))
report, normalized = summarize(['probe:1'], [(1, row)])
assert report['acceptance_metrics'] is None and report['kappa'] is None and report['independent_human_gold_records'] == 0
assert report['formal_evaluation_status'] == 'BLOCKED_EXTERNAL' and report['coverage']['complete_annotations'] == 0
rejected('formal_schema_refuses_pilot', lambda: Annotation.model_validate(normalized[0]))
checks.append('single_person_never_formal_metrics')
with tempfile.TemporaryDirectory(prefix='airlock-pilot-independent-') as directory:
    root = Path(directory)
    cases = root / 'cases.json'
    cases.write_text(json.dumps([{'id': 'probe:1'}]), encoding='utf-8')
    output = root / 'private-template'
    prepare(cases, output)
    raw = (output / 'single-person.template.csv').read_bytes()
    assert all(item.get('human') is None and item.get('source') is None for item in map(json.loads, (output / 'single-person.template.jsonl').read_text().splitlines()))
    try:
        prepare(cases, output)
    except FileExistsError:
        pass
    else:
        raise AssertionError('overwrite')
    assert (output / 'single-person.template.csv').read_bytes() == raw
    checks.append('exclusive_private_template_no_claims')
    for index, identifier in enumerate(['\r=NOW()', '\ufeff=NOW()', ' =NOW()', '\u2028=NOW()', '@SUM(1)', '-0']):
        cases.write_text(json.dumps([{'id': identifier}]), encoding='utf-8')
        rejected('formula_id_' + str(index), lambda index=index: prepare(cases, root / ('unsafe-' + str(index))))
        assert not (root / ('unsafe-' + str(index))).exists()
    cases.write_text(json.dumps([{'id': 'probe:1'}]), encoding='utf-8')
    annotations = root / 'annotations.jsonl'
    original = (json.dumps(row) + '\n').encode()
    annotations.write_bytes(original)
    report = import_annotations(cases, annotations, root / 'import', source_reference='Independent synthetic parser probe only')
    assert (root / 'import' / 'annotations.original.jsonl').read_bytes() == original
    assert report['provenance']['annotation_input']['sha256'] == hashlib.sha256(original).hexdigest()
    assert report['acceptance_metrics'] is None and report['formal_evaluation_status'] == 'BLOCKED_EXTERNAL'
    checks.append('original_input_hash_preserved')
print(json.dumps({'status': 'PASS', 'mode': 'synthetic_independent_boundary_probe', 'real_humans': 0, 'checks': checks}, indent=2))
