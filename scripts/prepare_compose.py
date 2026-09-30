"""Prepare Linux Compose data ownership without hiding host-readable env files.

Only the registered runtime subtree is changed. Run as its host administrator,
never as the Agent. Original role environments remain private. Dedicated Compose
copies stay host-owned and are not mounted into the Agent or service containers.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from airlock.cli import initialize


def prepare(root:Path) -> None:
    if root.is_symlink():raise RuntimeError('Refusing a symlink runtime directory')
    if not root.exists():initialize(root)
    if os.name=='posix' and os.geteuid()!=0:
        raise RuntimeError('Linux preparation requires sudo using the project Python interpreter')
    owner=root.stat()
    folders=[root/name for name in ('gateway','runner')]
    config=root/'compose'
    if config.is_symlink():raise RuntimeError('Refusing a symlink Compose configuration directory')
    for folder in folders:
        if not folder.is_dir() or not (folder/'.env').is_file():raise RuntimeError('Initialize both services before Compose preparation')
        for entry in [folder,*folder.rglob('*')]:
            if entry.is_symlink():raise RuntimeError('Refusing a symlink inside runtime service data')
    config.mkdir(mode=0o700,exist_ok=True)
    if os.name=='posix':os.chown(config,owner.st_uid,owner.st_gid)
    config.chmod(0o700)
    for folder in folders:
        destination=config/(folder.name+'.env')
        if destination.is_symlink():raise RuntimeError('Refusing a symlink configuration file')
        content=(folder/'.env').read_bytes()
        fd,temporary=tempfile.mkstemp(prefix='.compose-',dir=config)
        try:
            with os.fdopen(fd,'wb') as out:out.write(content)
            if os.name=='posix':os.chown(temporary,owner.st_uid,owner.st_gid)
            os.replace(temporary,destination)
        finally:
            if os.path.exists(temporary):os.unlink(temporary)
        if os.name=='posix':
            for entry in [folder,*folder.rglob('*')]:os.chown(entry,10001,10001)
    print('Prepared service data for UID 10001 and separate host-owned runtime/compose/*.env; Agent and human credentials unchanged.')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path,default=Path('runtime'))
    args=parser.parse_args();prepare(args.data_dir)


if __name__=='__main__':main()
