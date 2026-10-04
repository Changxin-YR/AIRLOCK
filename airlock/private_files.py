"""Exclusive private output reservations for one-use credentials.

The requested filename is a reservation name: ``claim.json`` is stored as
``claim.json.private/claim.json``. Reserving the private directory before any
external call prevents a rerun from consuming another one-use operation. Failed
reservations remain in place for explicit operator inspection; no automatic retry.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import subprocess


def restrict_directory(directory):
    """Restrict a newly created empty directory before any secret is written."""
    if os.name == 'nt':
        system = Path(os.environ.get('SYSTEMROOT', r'C:\Windows')) / 'System32'
        account = subprocess.run([str(system / 'whoami.exe'), '/user', '/fo', 'csv', '/nh'],
                                 check=True, capture_output=True, text=True).stdout
        sid = re.search(r'S-1-\d+(?:-\d+)+', account)
        if not sid:
            raise PermissionError('private output owner unavailable')
        subprocess.run([str(system / 'icacls.exe'), str(directory), '/inheritance:r',
                        '/grant:r', f'*{sid.group()}:(OI)(CI)F'],
                       check=True, capture_output=True)
    else:
        directory.chmod(0o700)


@contextmanager
def reserve_private_output(requested_path):
    requested = Path(requested_path).absolute()
    if not requested.name or requested.exists() or requested.is_symlink():
        raise FileExistsError('private output reservation already exists')
    requested.parent.mkdir(parents=True, exist_ok=True)
    private = requested.with_name(requested.name + '.private')
    private.mkdir(mode=0o700)  # Exclusive; a failure must happen before the call.
    restrict_directory(private)
    actual = private / requested.name
    with open(actual, 'x', encoding='utf-8',
              opener=lambda name, flags: os.open(name, flags, 0o600)) as destination:
        try:
            yield actual, destination
        finally:
            destination.flush()
            os.fsync(destination.fileno())
