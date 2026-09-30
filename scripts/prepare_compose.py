"""Host administrator setup only; never run inside the Agent container.

Linux bind mounts must be writable by UID 10001. Windows/macOS Docker Desktop
handles bind permissions differently; do not blindly chmod unrelated paths.
"""
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from airlock.cli import initialize
root=Path('runtime')
if not root.exists():initialize(root)
if os.name=='posix':
    if os.geteuid()!=0:
        raise SystemExit('For Linux Compose, use sudo chown -R 10001:10001 runtime/gateway runtime/runner AFTER initialization. Only these two directories.')
    for name in ('gateway','runner'):
        folder=root/name
        for entry in [folder,*folder.rglob('*')]:
            if entry.is_symlink():raise SystemExit('Refusing to follow a symlink in runtime')
            os.chown(entry,10001,10001)
print('Prepared only runtime/gateway and runtime/runner; human and Agent credentials remain separate.')
