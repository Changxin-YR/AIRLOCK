import hashlib
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile

import pytest

from airlock.sqlite_runtime import (enable_wal, mapped_sqlite_libraries, require_safe_sqlite,
                                    upstream_wal_fix_confirmed, verify_linked_build_report)
from scripts.build_sqlite_runtime import verify_archive
from airlock.github_adapter import AdapterConfig, IssueAdapter
from airlock.store import Store


@pytest.mark.parametrize('version,confirmed', [
    ('3.45.1', False), ('3.51.2', False), ('3.51.3', True), ('3.53.1', True),
    ('3.44.5', False), ('3.44.6', True), ('3.50.6', False), ('3.50.7', True),
    ('3.45.1-vendor-patched', False), ('4.0.0', False), ('3.51', False), (None, False),
])
def test_sqlite_wal_fix_requires_confirmed_upstream_version(version, confirmed):
    assert upstream_wal_fix_confirmed(version) is confirmed


def test_sqlite_guard_rejects_unconfirmed_runtime_before_enabling_wal(tmp_path):
    with sqlite3.connect(tmp_path/'unconfirmed.db') as connection:
        connection.create_function('sqlite_version', 0, lambda: '3.45.1')
        with pytest.raises(RuntimeError, match='unconfirmed'):
            enable_wal(connection)
        assert connection.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'


@pytest.mark.parametrize('component', ['store', 'github_adapter'])
@pytest.mark.parametrize('existing_wal', [False, True])
def test_sqlite_runtime_rejection_never_opens_persistent_database(settings, tmp_path, monkeypatch, component, existing_wal):
    """Real leftover WAL, simulated unconfirmed runtime; no corruption claim."""
    directory = tmp_path/'persistent-target'
    database = directory/'existing.db'
    if existing_wal:
        directory.mkdir()
        writer = """import os,sqlite3,sys
c=sqlite3.connect(sys.argv[1]);c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA synchronous=FULL');c.execute('PRAGMA wal_autocheckpoint=0')
c.execute('CREATE TABLE fixture(value TEXT)');c.execute('INSERT INTO fixture VALUES(?)',('synthetic guard test',));c.commit();os._exit(0)
"""
        subprocess.run([sys.executable, '-c', writer, str(database)], check=True, timeout=15)
        assert Path(str(database)+'-wal').is_file()
        before = {path.name: path.read_bytes() for path in directory.iterdir()}
        assert before['existing.db-wal'] and len(before['existing.db']) == 4096
    else:
        before = {}
    connect, opened, closed = sqlite3.connect, [], []

    class ObservedConnection(sqlite3.Connection):
        def close(self):
            closed.append(self.opened_target)
            return super().close()

    def unconfirmed(target, *args, **kwargs):
        opened.append(str(target))
        connection = connect(target, *args, factory=ObservedConnection, **kwargs)
        connection.opened_target = str(target)
        connection.create_function('sqlite_version', 0, lambda: '3.45.1')
        return connection

    monkeypatch.setattr(sqlite3, 'connect', unconfirmed)
    with pytest.raises(RuntimeError, match='unconfirmed'):
        if component == 'store':
            Store(replace(settings, database=database))
        else:
            config = AdapterConfig(repository_node_id='R_synthetic', repository_full_name='example/synthetic',
                                   public_repository=True, mode='relay')
            IssueAdapter(config, database)
    assert opened == [':memory:'] and closed == [':memory:']
    if existing_wal:
        after = {path.name: path.read_bytes() for path in directory.iterdir()}
        assert after == before  # Presence and all bytes of DB/WAL/SHM unchanged.
    else:
        assert not directory.exists() and not database.exists()


def test_sqlite_confirmed_runtime_preserves_wal_and_full_sync(tmp_path):
    with sqlite3.connect(tmp_path/'safe.db') as connection:
        info = enable_wal(connection)
        assert info['wal_reset_fix'] == 'upstream_fixed_version'
        assert connection.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert connection.execute('PRAGMA synchronous').fetchone()[0] == 2


def test_sqlite_pinned_runtime_survives_minimal_child_environment():
    # The actual relay server clears LD_LIBRARY_PATH. A build that is only
    # correct in the invoking shell must fail this integration gate.
    env = {key: value for key, value in os.environ.items() if key.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP'}}
    run = subprocess.run([sys.executable, '-m', 'airlock.sqlite_runtime', '--pin-file', 'configs/sqlite-runtime.json'],
                         env=env, cwd=Path(__file__).resolve().parents[1],
                         capture_output=True, text=True, timeout=15)
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)
    assert result['version'] == '3.53.1' and result['pin_verified'] is True
    assert result['sqlite_threadsafety'] > 0


def test_sqlite_builder_rejects_archive_or_official_source_hash_mismatch(tmp_path):
    archive = tmp_path/'fixture.tar.gz'
    source = b'synthetic amalgamation; never compiled'
    with tarfile.open(archive, 'w:gz') as writer:
        member = tarfile.TarInfo('source/sqlite3.c')
        member.size = len(source)
        writer.addfile(member, io.BytesIO(source))
    pin = {'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
           'amalgamation_path': 'source/sqlite3.c', 'amalgamation_sha3_256': hashlib.sha3_256(source).hexdigest()}
    assert verify_archive(archive, pin) == source
    with pytest.raises(ValueError, match='archive SHA256'):
        verify_archive(archive, dict(pin, archive_sha256='0'*64))
    with pytest.raises(ValueError, match='official release SHA3'):
        verify_archive(archive, dict(pin, amalgamation_sha3_256='0'*64))


def test_sqlite_binary_provenance_hashes_actual_mapping_and_matches_build(tmp_path):
    library = tmp_path/'libsqlite3.so.0'
    library.write_bytes(b'synthetic library fixture; never loaded')
    maps = tmp_path/'maps'
    maps.write_text('1000-2000 r-xp 00000000 00:00 1 '+str(library)+'\n'
                    '2000-3000 r--p 00000000 00:00 1 '+str(library)+'\n')
    libraries = mapped_sqlite_libraries(maps)
    assert libraries == [{'path': str(library), 'bytes': library.stat().st_size,
                          'sha256': hashlib.sha256(library.read_bytes()).hexdigest()}]
    pin = {'version': 'synthetic'}
    info = {'version': 'synthetic', 'source_id': 'synthetic', 'compile_options': ['THREADSAFE=1'],
            'loaded_shared_library_files': libraries}
    report = tmp_path/'build.json'
    document = {'mode': 'official_source_shared_runtime', 'pin': pin, 'library_sha256': libraries[0]['sha256'],
                'verified_python_runtime': {key: info[key] for key in ('version','source_id','compile_options')}}
    report.write_text(json.dumps(document))
    verify_linked_build_report(info, pin, report)
    assert info['build_report_verified'] and info['build_report_sha256'] == hashlib.sha256(report.read_bytes()).hexdigest()
    library.write_bytes(b'different binary with same claimed version')
    info['loaded_shared_library_files'] = mapped_sqlite_libraries(maps)
    with pytest.raises(RuntimeError, match='binary does not match'):
        verify_linked_build_report(info, pin, report)


def test_sqlite_binary_provenance_rejects_missing_or_ambiguous_mapping(tmp_path):
    maps = tmp_path/'maps'
    maps.write_text('1000-2000 r-xp 00000000 00:00 1 /missing/libsqlite3.so.0 (deleted)\n')
    with pytest.raises(RuntimeError, match='missing or changed'):
        mapped_sqlite_libraries(maps)
    report = tmp_path/'build.json'
    report.write_text(json.dumps({'mode': 'official_source_shared_runtime', 'pin': {}}))
    for libraries in ([], [{'sha256': 'x'}, {'sha256': 'x'}]):
        with pytest.raises(RuntimeError, match='binary does not match'):
            verify_linked_build_report({'loaded_shared_library_files': libraries}, {}, report)
