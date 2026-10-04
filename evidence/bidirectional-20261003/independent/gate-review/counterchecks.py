"""Cross-author checks; all mutations are in memory or our disposable directory."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from docs.acceptance.validate_matrix import read_json, validate
from scripts.verify_evidence import verify_latency


def distribution(values, mean=False):
    values = sorted(values)
    result = {'n': len(values), **{'p' + str(p): values[math.ceil(len(values) * p / 100) - 1] for p in (50, 95, 99)}}
    if mean:
        result['mean'] = sum(values) / len(values)
    return result


def inspect(name, should_reject, function):
    try:
        function()
        rejected, reason = False, None
    except (ValueError, KeyError, TypeError) as error:
        rejected, reason = True, str(error)
    return {'case': name, 'should_reject': should_reject, 'rejected': rejected,
            'pass': should_reject == rejected, 'reason': reason}


def main():
    ledger = read_json(ROOT / 'docs/acceptance/COMPLETION_MATRIX.json')
    index = read_json(ROOT / 'docs/acceptance/AIRLOCK-acceptance-targets.json')
    latency = read_json(ROOT / 'evidence/single-person-20261003/ci/verified/latency.json')
    cases = [inspect('original_matrix', False, lambda: validate(ledger, index)),
             inspect('original_latency', False, lambda: verify_latency(latency))]
    for name in ['missing_raw', 'missing_summary', 'changed_raw', 'nan_raw', 'slow_honest',
                 'boundary_read', 'boundary_static', 'boundary_preview']:
        altered = deepcopy(latency)
        if name == 'missing_raw':
            del altered['raw_read_pairs']
        elif name == 'missing_summary':
            del altered['read']['proxy_ms']['p99']
        elif name == 'changed_raw':
            altered['raw_read_pairs'][0]['proxy_ms'] += 1
        elif name == 'nan_raw':
            altered['raw_writes'][0]['evaluation_ms'] = float('nan')
        elif name in ('boundary_read', 'slow_honest'):
            for row in altered['raw_read_pairs']:
                row.update(direct_ms=1., proxy_ms=101., added_ms=100.)
            altered['read'] = {key: distribution([r[key] for r in altered['raw_read_pairs']], mean=True)
                               for key in ('direct_ms', 'proxy_ms', 'added_ms')}
            if name == 'boundary_read':
                altered['read']['added_ms']['p95'] = math.nextafter(100., 0.)
        else:
            field, limit = ('static_ms', 300.) if name == 'boundary_static' else ('preview_ms', 5000.)
            for row in altered['raw_writes']:
                row[field] = limit
            altered['write'][field] = distribution([limit] * len(altered['raw_writes']))
            altered['write'][field]['p95'] = math.nextafter(limit, 0.)
        cases.append(inspect(name, True, lambda: verify_latency(altered)))

    for name in ('matrix_missing_log', 'matrix_command_mismatch', 'matrix_missing_receipt'):
        altered = deepcopy(ledger)
        row = altered['targets'][0]
        if name == 'matrix_missing_log':
            row['evidence'].remove(row['commands'][0]['receipt'][:-len('.status.json')])
        elif name == 'matrix_command_mismatch':
            row['commands'][0]['command'] = ['python', '-c', 'print("unexecuted")']
        else:
            row['commands'][0]['receipt'] = 'var/bidirectional-20261003/gate-review/not-found.log.status.json'
        cases.append(inspect(name, True, lambda: validate(altered, index)))

    with tempfile.TemporaryDirectory(prefix='unarchived-', dir=Path(__file__).parent) as directory:
        path = Path(directory)
        receipt = path / 'unexecuted.log.status.json'
        raw_log = path / 'unexecuted.log'
        altered = deepcopy(ledger)
        row = altered['targets'][0]
        original_command = row['commands'][0]
        status = read_json(ROOT / original_command['receipt'])
        status['command'] = ['python', '-c', 'print("not actually executed")']
        receipt.write_text(json.dumps(status), encoding='utf-8')
        raw_log.write_text('Fabricated output; no subprocess was executed.\n', encoding='utf-8')
        receipt_name, raw_name = receipt.relative_to(ROOT).as_posix(), raw_log.relative_to(ROOT).as_posix()
        row['commands'] = [{**original_command, 'command': status['command'], 'receipt': receipt_name}]
        row['evidence'] = [receipt_name, raw_name]
        cases.append(inspect('matrix_unarchived_forged_frozen_receipt', True, lambda: validate(altered, index)))
    result = {'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              'dirty': subprocess.check_output(['git', 'status', '--porcelain'], text=True).splitlines(),
              'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in [
                  'docs/acceptance/validate_matrix.py', 'scripts/verify_evidence.py',
                  'tests/test_acceptance_matrix.py', 'tests/test_evidence_gate.py']},
              'cases': cases,
              'scope': 'structure, provenance and numeric consistency only; no functional or human acceptance'}
    print(json.dumps(result, indent=2))
    return 0 if all(row['pass'] for row in cases) else 1


if __name__ == '__main__':
    raise SystemExit(main())
