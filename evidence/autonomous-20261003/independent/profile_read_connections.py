"""One-off synthetic profiling; no application source is changed."""
import contextlib
import json
import math
from pathlib import Path
import platform
import random
import sqlite3
import statistics
import sys
import tempfile
import time
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from airlock.models import Settings, Invocation, GateError
from airlock.service import Gate

active = None
original_connect = sqlite3.connect


class TimedConnection(sqlite3.Connection):
    def execute(self, sql, *args, **kwargs):
        start = time.perf_counter_ns()
        try:
            return super().execute(sql, *args, **kwargs)
        finally:
            if active is not None:
                active['events'].append({'operation': 'execute', 'sql': sql, 'ms': (time.perf_counter_ns()-start)/1e6})

    def commit(self):
        start = time.perf_counter_ns()
        try:
            return super().commit()
        finally:
            if active is not None:
                active['events'].append({'operation': 'commit', 'ms': (time.perf_counter_ns()-start)/1e6})

    def close(self):
        if active is None:
            return super().close()
        files = self.execute('PRAGMA database_list').fetchall()
        database = next((r[2] for r in files if r[1] == 'main'), '')
        wal = Path(database + '-wal')
        before = wal.stat().st_size if database and wal.exists() else None
        start = time.perf_counter_ns()
        super().close()
        elapsed = (time.perf_counter_ns()-start)/1e6
        after = wal.stat().st_size if database and wal.exists() else None
        active['events'].append({'operation': 'close', 'ms': elapsed, 'wal_bytes_before': before, 'wal_bytes_after': after})


def connect(*args, **kwargs):
    start = time.perf_counter_ns()
    result = original_connect(*args, factory=TimedConnection, **kwargs)
    if active is not None:
        active['events'].append({'operation': 'connect', 'ms': (time.perf_counter_ns()-start)/1e6})
    return result


sqlite3.connect = connect


def distribution(values):
    values = sorted(values)
    return {'n': len(values), 'mean': statistics.mean(values), 'p50': values[math.ceil(.5*len(values))-1],
            'p95': values[math.ceil(.95*len(values))-1], 'max': values[-1]}


def share_request_connection(gate):
    # Experimental only: two original durable transactions still execute. The
    # same connection stays alive until the outer submit finishes or fails.
    original_connection = gate.store.connection
    original_submit = gate._submit
    held = [None]

    @contextlib.contextmanager
    def connection():
        if held[0] is not None:
            yield held[0]
        else:
            with original_connection() as conn:
                yield conn

    def submit(call, principal):
        with original_connection() as conn:
            held[0] = conn
            try:
                return original_submit(call, principal)
            finally:
                held[0] = None

    gate.store.connection = connection
    gate._submit = submit


directory = Path(__file__).parent / ('profile-databases-' + uuid.uuid4().hex)
directory.mkdir()
gates = {}
for arm in ('two_connections', 'one_request_connection'):
    settings = Settings(directory / (arm + '.db'), 'synthetic-agent-' + 'a'*32,
                        'synthetic-reviewer-' + 'b'*32, 'synthetic-audit-' + 'c'*32,
                        calls_per_minute=1000)
    gate = Gate(settings)
    if arm == 'one_request_connection':
        share_request_connection(gate)
    gates[arm] = gate
    for index in range(10):
        gate.submit(Invocation(sql='SELECT count(*) AS n FROM customers', idempotency_key=f'warmup-{index:04d}'))

rows = []
rng = random.Random(2073)
for pair in range(60):
    order = list(gates)
    rng.shuffle(order)
    for arm in order:
        active = {'arm': arm, 'pair': pair, 'order': order, 'events': []}
        start = time.perf_counter_ns()
        action = gates[arm].submit(Invocation(sql='SELECT count(*) AS n FROM customers', idempotency_key=f'read-{pair:04d}'))
        active['submit_ms'] = (time.perf_counter_ns()-start)/1e6
        active['evaluation_ms'] = action['evaluation_ms']
        assert action['state'] == 'executed' and action['result']['rows'] == [{'n': 1206}]
        rows.append(active)
        active = None

summaries = {}
for arm, gate in gates.items():
    selected = [r for r in rows if r['arm'] == arm]
    breakdown = {}
    for operation in ('connect', 'execute', 'commit', 'close'):
        breakdown[operation] = distribution([sum(e['ms'] for e in r['events'] if e['operation'] == operation) for r in selected])
    # Failed submission must not roll back expiration or its clock high-water.
    pending = gate.submit(Invocation(sql='DELETE FROM customers WHERE id=1', idempotency_key='expiry-proof'))
    target_time = pending['expires_at'] + 1
    gate.clock = lambda: target_time
    try:
        gate.submit(Invocation(sql='SELECT id FROM customers', idempotency_key='read-0000'))
        raise AssertionError('expected idempotency conflict')
    except GateError as error:
        assert error.code == 'idempotency_conflict'
    with gate.store.connection() as conn:
        persisted = json.loads(conn.execute('SELECT document FROM actions WHERE id=?', (pending['id'],)).fetchone()[0])
        high_water = float(conn.execute("SELECT value FROM meta WHERE key='clock_high_water'").fetchone()[0])
        count = conn.execute('SELECT count(*) FROM customers').fetchone()[0]
        synchronous = conn.execute('PRAGMA synchronous').fetchone()[0]
        mode = conn.execute('PRAGMA journal_mode').fetchone()[0]
    assert persisted['state'] == 'expired' and high_water == target_time and count == 1206
    audit = gate.store.verify_audit()
    assert audit['valid'] and synchronous == 2 and mode == 'wal'
    summaries[arm] = {'submit_ms': distribution([r['submit_ms'] for r in selected]), 'breakdown_ms': breakdown,
        'commits_per_request': sorted({sum(e['operation'] == 'commit' for e in r['events']) for r in selected}),
        'closes_per_request': sorted({sum(e['operation'] == 'close' for e in r['events']) for r in selected}),
        'wal_deleted_on_close': sum(e['operation'] == 'close' and e['wal_bytes_before'] is not None and e['wal_bytes_after'] is None for r in selected for e in r['events']),
        'audit_valid': audit['valid'], 'failed_request_preserves_expiry_and_clock_high_water': True,
        'synchronous': synchronous, 'journal_mode': mode}

report = {'scope': 'diagnostic only; local Windows, in-process Gate, instrumented; not the Linux native HTTP acceptance benchmark',
          'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version, 'platform': platform.platform(),
          'seed': 2073, 'samples_per_arm': 60, 'unmodified_source_commit': 'a68b11b',
          'source_edits': False, 'summaries': summaries, 'raw_requests': rows}
destination = Path(__file__).with_name('profile_read_connections.json')
destination.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'report': str(destination), 'summaries': summaries}, indent=2))
