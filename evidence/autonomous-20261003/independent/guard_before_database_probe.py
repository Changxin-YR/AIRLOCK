"""Synthetic guard-order counterexample; never opens live/demo databases."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from airlock.models import Settings
from airlock.store import Store

directory = Path(__file__).parent / ('guard-order-' + uuid.uuid4().hex)
directory.mkdir()
database = directory / 'synthetic.db'
writer = """import os,sqlite3,sys
c=sqlite3.connect(sys.argv[1]);c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA synchronous=FULL');c.execute('PRAGMA wal_autocheckpoint=0')
c.execute('CREATE TABLE fixture(value TEXT)');c.execute('INSERT INTO fixture VALUES(?)',('synthetic guard test',));c.commit();os._exit(0)
"""
subprocess.run([sys.executable, '-c', writer, str(database)], check=True)

def snapshot():
    return {path.name: {'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in directory.iterdir() if path.is_file()}

before = snapshot()
original = sqlite3.connect
def unconfirmed(*args, **kwargs):
    connection = original(*args, **kwargs)
    connection.create_function('sqlite_version', 0, lambda: '3.45.1')
    return connection
sqlite3.connect = unconfirmed
try:
    Store(Settings(database, 'synthetic-agent-'+'a'*32, 'synthetic-reviewer-'+'b'*32, 'synthetic-audit-'+'c'*32))
    raise AssertionError('unconfirmed runtime should be rejected')
except RuntimeError as error:
    assert 'unconfirmed' in str(error)
finally:
    sqlite3.connect = original
after = snapshot()
report = {'scope': 'Guard ordering only. Actual SQLite is safe 3.53.1; sqlite_version is overridden to exercise rejection. No data-corruption claim.',
          'runtime_rejected': True, 'target_wal_existed_before': 'synthetic.db-wal' in before,
          'target_wal_exists_after': 'synthetic.db-wal' in after,
          'database_changed_despite_rejection': before['synthetic.db'] != after['synthetic.db'],
          'before': before, 'after': after}
assert report['database_changed_despite_rejection'] and not report['target_wal_exists_after']
destination = Path(__file__).with_suffix('.json')
destination.write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report, indent=2))
