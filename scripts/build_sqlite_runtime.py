"""Build one hash-pinned official SQLite amalgamation for Linux Python.

No system library is replaced. The child process must actually resolve the new
library and report the exact official source ID before this build is accepted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
FLAGS = ['-O2', '-fPIC', '-shared', '-Wl,-soname,libsqlite3.so.0', '-DSQLITE_THREADSAFE=1',
         '-DSQLITE_ENABLE_COLUMN_METADATA', '-DSQLITE_ENABLE_FTS3', '-DSQLITE_ENABLE_FTS5',
         '-DSQLITE_ENABLE_RTREE', '-DSQLITE_ENABLE_DBSTAT_VTAB', '-DSQLITE_ENABLE_MATH_FUNCTIONS',
         '-DSQLITE_USE_URI=1']


def verify_archive(archive, pin):
    if hashlib.sha256(archive.read_bytes()).hexdigest() != pin['archive_sha256']:
        raise ValueError('SQLite source archive SHA256 mismatch')
    with tarfile.open(archive) as source:
        entry = source.getmember(pin['amalgamation_path'])
        if not entry.isfile() or not 1 <= entry.size <= 16 * 1024 * 1024:
            raise ValueError('unexpected SQLite amalgamation member')
        amalgamation = source.extractfile(entry).read()
    if hashlib.sha3_256(amalgamation).hexdigest() != pin['amalgamation_sha3_256']:
        raise ValueError('SQLite amalgamation differs from the official release SHA3-256')
    return amalgamation


def build(prefix, output, archive=None, pin_file=ROOT/'configs/sqlite-runtime.json'):
    if platform.system() != 'Linux':
        raise RuntimeError('shared runtime builder requires Linux; Windows uses its verified bundled SQLite without replacing DLLs')
    pin = json.loads(pin_file.read_text(encoding='utf-8'))
    prefix = prefix.resolve()
    prefix.mkdir(parents=True, exist_ok=False)
    libdir = prefix/'lib'
    libdir.mkdir()
    with tempfile.TemporaryDirectory(prefix='build-', dir=prefix) as temporary:
        work = Path(temporary)
        if archive is None:
            archive = work/'sqlite.tar.gz'
            # The sole pinned release URL is source distribution, not discovery.
            if pin['archive_url'] != 'https://sqlite.org/2026/sqlite-autoconf-3530100.tar.gz':
                raise ValueError('unapproved SQLite source URL')
            with urllib.request.urlopen(pin['archive_url'], timeout=30) as response:
                if response.url != pin['archive_url']:
                    raise ValueError('unexpected SQLite source redirect')
                data = response.read(16 * 1024 * 1024 + 1)
            if len(data) > 16 * 1024 * 1024:
                raise ValueError('SQLite archive size limit')
            archive.write_bytes(data)
        amalgamation = verify_archive(Path(archive), pin)
        (work/'sqlite3.c').write_bytes(amalgamation)
        library = libdir/'libsqlite3.so.0'
        command = ['cc', *FLAGS, str(work/'sqlite3.c'), '-o', str(library), '-lm', '-ldl', '-pthread']
        subprocess.run(command, check=True, timeout=300)
        (libdir/'libsqlite3.so').symlink_to(library.name)
    env = dict(os.environ, LD_LIBRARY_PATH=str(libdir))
    probe = "import json,sqlite3; c=sqlite3.connect(':memory:'); print(json.dumps({'version':sqlite3.sqlite_version,'source_id':c.execute('SELECT sqlite_source_id()').fetchone()[0],'compile_options':sorted(r[0] for r in c.execute('PRAGMA compile_options'))}))"
    child = subprocess.run([sys.executable, '-c', probe], env=env, check=True, capture_output=True, text=True, timeout=20)
    runtime = json.loads(child.stdout)
    if runtime['version'] != pin['version'] or runtime['source_id'] != pin['source_id']:
        raise RuntimeError('built SQLite did not resolve into the Python child process')
    report = {'mode': 'official_source_shared_runtime', 'platform': platform.platform(), 'pin': pin,
              'compiler': subprocess.run(['cc', '--version'], check=True, capture_output=True, text=True).stdout.splitlines()[0],
              'compiler_flags': FLAGS, 'library': str(library),
              'library_sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
              'verified_python_runtime': runtime, 'child_exit_code': child.returncode,
              'system_library_replaced': False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--archive', type=Path, help='Previously downloaded archive, verified against both official source hashes')
    args = parser.parse_args()
    build(args.prefix, args.output, args.archive)


if __name__ == '__main__':
    main()
