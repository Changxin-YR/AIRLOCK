"""Independent deterministic counterexample: one mutation, two valid observations."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from airlock.github_adapter import AdapterConfig, ExecuteRequest, IssueAdapter, IssueArguments, ObservedIssue
from airlock.models import GateError


def outcome(future):
    try:
        return {'state': future.result(timeout=3)['state']}
    except GateError as error:
        return {'error': error.code}


def main():
    observations = []
    for first in ('readback', 'response'):
        with tempfile.TemporaryDirectory(prefix='race-', dir=Path(__file__).parent) as directory:
            cfg = AdapterConfig(repository_node_id='R_synthetic', repository_full_name='synthetic/counterexample',
                                public_repository=True, mode='direct', api_pinned_addresses=['140.82.112.6'])
            adapter = IssueAdapter(cfg, Path(directory) / 'synthetic.db')
            arguments = IssueArguments(title='Synthetic race', body='No external operation')
            request = ExecuteRequest(action_id='a' * 32, request_hash='b' * 64, arguments=arguments,
                                     expected_version=adapter._plan_digest(arguments))
            mutation_done, allow_response, read_started, allow_readback = (Event() for _ in range(4))
            effects = []
            def create(row):
                effects.append(ObservedIssue(repository_node_id=cfg.repository_node_id,
                    repository_full_name=cfg.repository_full_name, issue_node_id='I_synthetic', number=8,
                    url='https://github.com/synthetic/counterexample/issues/8', title=row['title'], body=row['body']))
                mutation_done.set()
                assert allow_response.wait(3)
                return effects[0]
            def read_issue(_):
                read_started.set()
                assert allow_readback.wait(3)
                return effects[0]
            adapter.api.create = create
            adapter.api.read_issue = read_issue
            with ThreadPoolExecutor(max_workers=2) as pool:
                execution = pool.submit(adapter.execute, request)
                assert mutation_done.wait(3)
                reconciliation = pool.submit(adapter.reconcile_direct, request.action_id, 'I_synthetic')
                assert read_started.wait(3)
                if first == 'readback':
                    allow_readback.set()
                    read_result = outcome(reconciliation)
                    allow_response.set()
                    execute_result = outcome(execution)
                else:
                    allow_response.set()
                    execute_result = outcome(execution)
                    allow_readback.set()
                    read_result = outcome(reconciliation)
            receipt = adapter.receipt(request.action_id)
            observations.append({'first': first, 'execution': execute_result, 'reconciliation': read_result,
                                 'stored_state': receipt['state'], 'stored_verification': receipt['result']['receipt_verification'],
                                 'synthetic_effects': len(effects), 'replay_equals_receipt': adapter.execute(request) == receipt})
    evidence = {'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
                'dirty': subprocess.check_output(['git', 'status', '--porcelain'], text=True).splitlines(),
                'source_sha256': hashlib.sha256((ROOT / 'airlock/github_adapter.py').read_bytes()).hexdigest(),
                'observations': observations, 'network_calls': 0}
    print(json.dumps(evidence, indent=2))
    return 0 if all(o['execution'] == o['reconciliation'] == {'state': 'executed'} and o['synthetic_effects'] == 1
                    and o['replay_equals_receipt'] for o in observations) else 1


if __name__ == '__main__':
    raise SystemExit(main())
