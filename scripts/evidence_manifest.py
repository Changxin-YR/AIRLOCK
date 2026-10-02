"""Inventory actual CI artifacts. A manifest records files; it is not a test verdict."""
from __future__ import annotations
import hashlib
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess

ROOT = Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,default=ROOT/'evidence');args=parser.parse_args()
TARGET=args.directory
TARGET.mkdir(parents=True,exist_ok=True)
versions = {}
for package in ('fastapi', 'starlette', 'pydantic', 'uvicorn', 'httpx', 'pytest', 'playwright', 'mcp', 'anyio','cel-python','PyYAML','pip-audit'):
    try:
        versions[package] = importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        versions[package] = None
result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
files = {}
for path in sorted(TARGET.iterdir()):
    if path.is_file() and path.name != 'manifest.json' and path.suffix in {'.json', '.jsonl', '.log', '.txt', '.png', '.zip', '.xml'}:
        data = path.read_bytes()
        files[path.name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
report = {'commit': result.stdout.strip() if result.returncode == 0 else None,
          'github_run_id': os.getenv('GITHUB_RUN_ID'), 'python': platform.python_version(),
          'sqlite': sqlite3.sqlite_version, 'packages': versions, 'files': files,
          'not_claimed': ['live LLM validation', 'human A/B study', 'production security certification'],
          'warning': 'File existence and hashes are not proof of success. Read exit codes, raw logs and GitHub job results.'}
(TARGET / 'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'commit': report['commit'], 'artifact_files': len(files)}))
