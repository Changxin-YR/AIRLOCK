"""Fail closed before enabling WAL on an unconfirmed SQLite runtime.

The upstream WAL-reset race was fixed in 3.51.3 and the 3.50.7/3.44.6
backport branches. Old distribution version strings may include vendor patches,
but this project has no verified vendor build allowlist. They are unconfirmed,
not automatically labelled vulnerable. CI/Docker use the pinned upstream source.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import platform
import re
import sqlite3


def upstream_wal_fix_confirmed(version):
    if not isinstance(version, str) or not re.fullmatch(r'3\.\d+\.\d+', version):
        return False
    major, minor, patch = (int(part) for part in version.split('.'))
    return ((major, minor, patch) >= (3, 51, 3)
            or minor == 50 and patch >= 7 or minor == 44 and patch >= 6)


def runtime_info(connection):
    version, source_id = connection.execute('SELECT sqlite_version(), sqlite_source_id()').fetchone()
    return {'version': version, 'source_id': source_id,
            'wal_reset_fix': 'upstream_fixed_version' if upstream_wal_fix_confirmed(version) else 'unconfirmed_vendor_or_upstream',
            'compile_options': sorted(row[0] for row in connection.execute('PRAGMA compile_options')),
            'python': platform.python_version(), 'sqlite_threadsafety': sqlite3.threadsafety}


def require_safe_sqlite(connection):
    info = runtime_info(connection)
    if not upstream_wal_fix_confirmed(info['version']):
        raise RuntimeError('SQLite WAL-reset fix is unconfirmed; use the pinned runtime before opening AIRLOCK for writes')
    if sqlite3.threadsafety == 0 or 'THREADSAFE=0' in info['compile_options']:
        raise RuntimeError('thread-safe SQLite runtime required')
    return info


def require_safe_python_runtime():
    """Check only memory before any existing WAL file is opened or recovered.

    Closing an existing WAL connection can checkpoint it even when application
    startup subsequently fails. This check must precede persistent-file access.
    """
    with closing(sqlite3.connect(':memory:')) as connection:
        return require_safe_sqlite(connection)


def enable_wal(connection):
    info = require_safe_sqlite(connection)
    mode = connection.execute('PRAGMA journal_mode=WAL').fetchone()[0]
    if mode.lower() != 'wal':
        raise RuntimeError('WAL journal could not be enabled')
    connection.execute('PRAGMA synchronous=FULL')
    return info


def mapped_sqlite_libraries(maps_path=None):
    """Hash the files actually mapped by Linux, not a guessed install prefix."""
    maps = maps_path or Path('/proc/self/maps')
    if maps_path is None and platform.system() != 'Linux':
        return []
    if not maps.exists():
        raise RuntimeError('loaded SQLite library mappings unavailable')
    paths = set()
    for line in maps.read_text().splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) == 6 and 'libsqlite3.so' in fields[5]:
            path = Path(fields[5])
            if not re.fullmatch(r'libsqlite3\.so(?:\.\d+)*', path.name) or not path.is_file():
                raise RuntimeError('loaded SQLite library is missing or changed')
            paths.add(path)
    return [{'path': str(path), 'bytes': path.stat().st_size,
             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(paths)]


def verify_linked_build_report(info, pin, report_path):
    raw = report_path.read_bytes()
    build = json.loads(raw)
    libraries = info['loaded_shared_library_files']
    if (build.get('mode') != 'official_source_shared_runtime' or build.get('pin') != pin
            or len(libraries) != 1 or libraries[0]['sha256'] != build.get('library_sha256')
            or any(build.get('verified_python_runtime', {}).get(key) != info[key]
                   for key in ('version', 'source_id', 'compile_options'))):
        raise RuntimeError('loaded SQLite binary does not match the verified build report')
    info['build_report_verified'] = True
    info['build_report_sha256'] = hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pin-file', type=Path)
    parser.add_argument('--build-report', type=Path, help='Explicit Linux build report; verify the actually mapped binary SHA256')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.build_report and not args.pin_file:
        parser.error('--build-report requires --pin-file')
    info = require_safe_python_runtime()
    if args.pin_file:
        pin = json.loads(args.pin_file.read_text(encoding='utf-8'))
        if info['version'] != pin['version'] or info['source_id'] != pin['source_id']:
            raise RuntimeError('Python did not load the pinned SQLite runtime')
        info['pin_verified'] = True
        info['archive_sha256'] = pin['archive_sha256']
        info['amalgamation_sha3_256'] = pin['amalgamation_sha3_256']
    info['loaded_shared_library_files'] = mapped_sqlite_libraries()
    info['loaded_shared_libraries'] = [item['path'] for item in info['loaded_shared_library_files']]
    if args.build_report:
        verify_linked_build_report(info, pin, args.build_report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(info, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(info, indent=2))


if __name__ == '__main__':
    main()
