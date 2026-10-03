"""Independent fixed-order checks; real runtime is safe, old version is simulated."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from airlock.github_adapter import AdapterConfig, IssueAdapter
from airlock.models import Settings
from airlock.store import Store

directory = Path(__file__).parent / ('guard-fixed-' + uuid.uuid4().hex)
directory.mkdir()
writer = """import os,sqlite3,sys
c=sqlite3.connect(sys.argv[1]);c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA synchronous=FULL');c.execute('PRAGMA wal_autocheckpoint=0')
c.execute('CREATE TABLE fixture(value TEXT)');c.execute('INSERT INTO fixture VALUES(?)',('synthetic guard test',));c.commit();os._exit(0)
"""
original = sqlite3.connect
results = []
for kind in ('store', 'github_adapter'):
    for existing_wal in (True, False):
        case = directory / (kind + ('-wal' if existing_wal else '-fresh'))
        database = case / 'synthetic.db'
        if existing_wal:
            case.mkdir()
            subprocess.run([sys.executable, '-c', writer, str(database)], check=True)
        def snapshot():
            return {path.name: {'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                    for path in case.iterdir() if path.is_file()} if case.exists() else {}
        before = snapshot()
        touched = []
        def unconfirmed(*args, **kwargs):
            touched.append(str(args[0]))
            connection = original(*args, **kwargs)
            connection.create_function('sqlite_version', 0, lambda: '3.45.1')
            return connection
        sqlite3.connect = unconfirmed
        try:
            if kind == 'store':
                Store(Settings(database, 'synthetic-agent-'+'a'*32, 'synthetic-reviewer-'+'b'*32, 'synthetic-audit-'+'c'*32))
            else:
                config = AdapterConfig(repository_node_id='R_synthetic', repository_full_name='example/project', public_repository=True, mode='relay')
                IssueAdapter(config, database)
            raise AssertionError('unconfirmed runtime should be rejected')
        except RuntimeError as error:
            assert 'unconfirmed' in str(error)
        finally:
            sqlite3.connect = original
        after = snapshot()
        assert touched == [':memory:'] and before == after
        if not existing_wal:
            assert not case.exists()
        results.append({'kind': kind, 'existing_wal': existing_wal, 'runtime_rejected': True,
                        'connected_targets': touched, 'persistent_paths_unchanged': before == after,
                        'fresh_parent_directory_created': not existing_wal and case.exists(),
                        'before': before, 'after': after})
report = {'scope': 'Guard ordering only. Actual SQLite is safe 3.53.1; sqlite_version is overridden to exercise rejection. No data-corruption claim.',
          'results': results}
destination = Path(__file__).with_suffix('.json')
destination.write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps({'output': str(destination), 'cases': len(results), 'all_persistent_paths_unchanged': True}))
