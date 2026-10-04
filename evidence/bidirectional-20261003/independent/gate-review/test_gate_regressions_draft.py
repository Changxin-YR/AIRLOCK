"""Suggested cross-author regression cases; copy into the owning test modules."""
import json
import math
from pathlib import Path
import tempfile

import pytest

from docs.acceptance.validate_matrix import ROOT, read_json, validate
from scripts.verify_evidence import verify_latency


@pytest.mark.parametrize('field,limit', [('added_ms', 100.), ('static_ms', 300.), ('preview_ms', 5000.)])
def test_latency_threshold_uses_raw_p95_not_tolerated_summary(field, limit):
    # Every raw sample is exactly at the strict upper bound. One ULP below the
    # bound is an acceptable summary rounding error, never a passing raw value.
    added = limit if field == 'added_ms' else 1.
    reads = [{'pair': i, 'action_id': f'{i:032x}', 'order': ['direct', 'proxy'],
              'direct_ms': 1., 'proxy_ms': 1. + added, 'added_ms': added} for i in range(10)]
    names = ('submit_receipt_ms', 'approval_request_to_effect_ms', 'static_ms', 'preview_ms', 'evaluation_ms')
    writes = [{'sample': i, **{name: limit if field == name else 1. for name in names}} for i in range(10)]
    report = {'samples': 10, 'raw_read_pairs': reads, 'raw_writes': writes,
              'read': {name: {'n': 10, 'mean': value, 'p50': value, 'p95': value, 'p99': value}
                       for name, value in [('direct_ms', 1.), ('proxy_ms', 1. + added), ('added_ms', added)]},
              'write': {name: {'n': 10, 'p50': writes[0][name], 'p95': writes[0][name], 'p99': writes[0][name]}
                        for name in names}}
    report['read' if field == 'added_ms' else 'write'][field]['p95'] = math.nextafter(limit, 0.)
    with pytest.raises(ValueError, match='latency threshold'):
        verify_latency(report, expected_samples=10)


def test_acceptance_unarchived_receipt_cannot_establish_frozen_pass():
    report = read_json(ROOT / 'docs/acceptance/COMPLETION_MATRIX.json')
    index = read_json(ROOT / 'docs/acceptance/AIRLOCK-acceptance-targets.json')
    row = report['targets'][0]
    original_command = row['commands'][0]
    status = read_json(ROOT / original_command['receipt'])
    status['command'] = ['python', '-c', 'print("never executed")']
    # Keep the files inside the repository so path confinement alone cannot
    # reject them; only an archive/inventory binding proves frozen evidence.
    private = ROOT / 'var'
    private.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='unarchived-acceptance-', dir=private) as directory:
        path = Path(directory)
        receipt = path / 'unexecuted.log.status.json'
        raw_log = path / 'unexecuted.log'
        receipt.write_text(json.dumps(status), encoding='utf-8')
        raw_log.write_text('This output has no subprocess execution provenance.\n', encoding='utf-8')
        receipt_name = receipt.relative_to(ROOT).as_posix()
        row['commands'] = [{**original_command, 'command': status['command'], 'receipt': receipt_name}]
        row['evidence'] = [receipt_name, raw_log.relative_to(ROOT).as_posix()]
        with pytest.raises(ValueError, match='no successful frozen receipt'):
            validate(report, index)
