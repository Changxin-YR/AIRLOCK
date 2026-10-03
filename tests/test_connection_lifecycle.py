"""Request-local reuse preserves distinct durable transactions and authorization."""
import json
import sqlite3

import pytest

from airlock.models import GateError, Invocation
from airlock.service import Gate
from airlock.sql import restricted
from conftest import call


def track_connections(monkeypatch):
    original = sqlite3.connect
    events = []

    class TrackedConnection(sqlite3.Connection):
        def commit(self):
            # FULL=2, EXTRA=3; neither NORMAL nor OFF is acceptable. A runtime
            # compatibility policy may select stronger EXTRA durability.
            assert self.execute('PRAGMA synchronous').fetchone()[0] >= 2
            super().commit()
            events.append(('commit', id(self), self.in_transaction))

        def rollback(self):
            super().rollback()
            events.append(('rollback', id(self), self.in_transaction))

        def close(self):
            events.append(('close', id(self), self.in_transaction))
            super().close()

    def connect(*args, **kwargs):
        assert kwargs.get('cached_statements') == 0
        result = original(*args, **kwargs, factory=TrackedConnection)
        events.append(('connect', id(result), result.in_transaction))
        return result

    monkeypatch.setattr(sqlite3, 'connect', connect)
    return events


def test_submit_uses_one_connection_and_two_full_commits(gate, monkeypatch):
    events = track_connections(monkeypatch)
    result = gate.submit(call('SELECT count(*) AS n FROM customers'))
    assert result['state'] == 'executed' and result['result']['rows'] == [{'n': 1206}]
    assert [kind for kind, _, _ in events] == ['connect', 'commit', 'commit', 'close']
    assert len({identity for _, identity, _ in events}) == 1
    assert all(not active for _, _, active in events)


def test_failed_submit_keeps_expiration_and_high_water_committed(settings, monkeypatch):
    clock = [1000.0]
    gate = Gate(settings, clock=lambda: clock[0])
    pending = gate.submit(call(key='pending-for-expiry'))
    gate.submit(call('SELECT id FROM customers', key='conflicting-key'))
    clock[0] = pending['expires_at'] + 1
    with monkeypatch.context() as tracked:
        events = track_connections(tracked)
        with pytest.raises(GateError, match='idempotency_conflict'):
            gate.submit(call('SELECT name FROM customers', key='conflicting-key'))
        assert [kind for kind, _, _ in events] == ['connect', 'commit', 'rollback', 'close']
        assert len({identity for _, identity, _ in events}) == 1
    with gate.store.connection() as conn:
        action = json.loads(conn.execute('SELECT document FROM actions WHERE id=?', (pending['id'],)).fetchone()[0])
        assert action['state'] == 'expired'
        assert float(conn.execute("SELECT value FROM meta WHERE key='clock_high_water'").fetchone()[0]) == clock[0]
        assert conn.execute('SELECT count(*) FROM customers').fetchone()[0] == 1206
    assert gate.store.verify_audit()['valid']
    clock[0] -= 2
    with pytest.raises(GateError, match='clock_regression_detected'):
        gate.submit(call('SELECT id FROM customers', key='clock-regression'))


def test_reused_connection_reauthorizes_prepared_sql_and_restores_limits(gate):
    # The exact same SQL was prepared under trusted server access first. A
    # statement cache would otherwise risk skipping authorizer recompilation.
    with gate.store.connection() as conn:
        with gate.store.transaction(conn):
            assert conn.execute('SELECT value FROM meta').fetchall()
        original_limit = conn.getlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH)
        with gate.store.transaction(conn):
            with restricted(conn):
                with pytest.raises(sqlite3.DatabaseError):
                    conn.execute('SELECT value FROM meta').fetchall()
            assert conn.getlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH) == original_limit
            assert conn.execute('SELECT value FROM meta').fetchall()
        with gate.store.transaction(conn):
            with restricted(conn):
                with pytest.raises(sqlite3.DatabaseError):
                    conn.execute('SELECT value FROM meta').fetchall()


def test_borrowed_transaction_does_not_commit_an_existing_outer_transaction(gate):
    with gate.store.connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute("INSERT INTO meta VALUES('not_committed','test')")
        with pytest.raises(ValueError, match='nested transactions'):
            with gate.store.transaction(conn):
                pytest.fail('must not enter nested transaction')
        assert conn.in_transaction
        conn.rollback()
    with gate.store.connection() as conn:
        assert conn.execute("SELECT value FROM meta WHERE key='not_committed'").fetchone() is None


def test_submit_audit_failure_rolls_back_action_but_keeps_high_water(settings, monkeypatch):
    gate = Gate(settings, clock=lambda: 1000.0)
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError('synthetic audit write failure')
    monkeypatch.setattr(gate.store, 'audit', fail)
    with pytest.raises(sqlite3.OperationalError):
        gate.submit(Invocation(sql='SELECT count(*) FROM customers', idempotency_key='audit-failure-read'))
    with gate.store.connection() as conn:
        assert conn.execute('SELECT count(*) FROM actions').fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM audit').fetchone()[0] == 0
        assert float(conn.execute("SELECT value FROM meta WHERE key='clock_high_water'").fetchone()[0]) == 1000.0
