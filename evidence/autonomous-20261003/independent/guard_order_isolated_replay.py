"""Replay the old connection order beside the fixed Store, without git resets.

The old arm embeds only the formerly executed connection/PRAGMA/guard/close
sequence. The initial actual-Store counterexample remains separately archived.
Actual SQLite is safe; an overridden version function simulates rejection.
This proves guard ordering, not the upstream database-corruption bug.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from airlock.models import Settings
from airlock.sqlite_runtime import enable_wal
from airlock.store import Store

original = sqlite3.connect
root = Path(__file__).parent / ('guard-replay-' + uuid.uuid4().hex)
root.mkdir()
writer = """import os,sqlite3,sys
c=sqlite3.connect(sys.argv[1]);c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA synchronous=FULL');c.execute('PRAGMA wal_autocheckpoint=0')
c.execute('CREATE TABLE fixture(value TEXT)');c.execute('INSERT INTO fixture VALUES(?)',('synthetic replay',));c.commit();os._exit(0)
"""


def old_connection_order(database):
    # Former Store.connection() plus the first guarded constructor operation.
    connection = sqlite3.connect(database, isolation_level=None, timeout=3, cached_statements=0)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    connection.execute('PRAGMA synchronous=FULL')
    connection.execute('PRAGMA trusted_schema=OFF')
    try:
        enable_wal(connection)
    finally:
        connection.close()


results = []
for arm in ('old_connection_order', 'fixed_store_constructor'):
    directory = root / arm
    directory.mkdir()
    database = directory / 'synthetic.db'
    subprocess.run([sys.executable, '-c', writer, str(database)], check=True)
    def snapshot():
        return {path.name: {'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in directory.iterdir() if path.is_file()}
    before = snapshot()
    opened = []
    def simulated_old_runtime(*args, **kwargs):
        opened.append(str(args[0]))
        connection = original(*args, **kwargs)
        connection.create_function('sqlite_version', 0, lambda: '3.45.1')
        return connection
    sqlite3.connect = simulated_old_runtime
    try:
        if arm == 'old_connection_order':
            old_connection_order(database)
        else:
            Store(Settings(database, 'synthetic-agent-'+'a'*32, 'synthetic-reviewer-'+'b'*32, 'synthetic-audit-'+'c'*32))
        raise AssertionError('expected unconfirmed-runtime rejection')
    except RuntimeError as error:
        assert 'unconfirmed' in str(error)
    finally:
        sqlite3.connect = original
    after = snapshot()
    changed = before != after
    assert changed is (arm == 'old_connection_order')
    results.append({'arm': arm, 'runtime_rejected': True, 'connected_targets': opened,
                    'persistent_files_changed': changed, 'before': before, 'after': after})
report = {'scope': __doc__, 'actual_runtime': sqlite3.sqlite_version, 'simulated_reported_version': '3.45.1', 'results': results}
destination = Path(__file__).with_suffix('.json')
destination.write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps({'output': str(destination), 'old_changed': results[0]['persistent_files_changed'],
                  'fixed_changed': results[1]['persistent_files_changed'], 'data_corruption_reproduced': False}))
