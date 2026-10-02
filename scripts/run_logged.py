"""Capture a command's output without losing its exit code to a tee pipeline."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time


def run_logged(log: Path, command: list[str]) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    clock = time.monotonic()
    exit_code = 1
    start_commit=subprocess.run(['git','rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
    with log.open('wb') as output:
        try:
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
                assert process.stdout is not None
                for chunk in iter(lambda: process.stdout.read(4096), b''):
                    output.write(chunk)
                    output.flush()
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.buffer.flush()
                code = process.wait()
                exit_code = code if code >= 0 else 128 - code
        except OSError as error:
            message = f'Command could not start: {error}\n'.encode()
            output.write(message)
            sys.stderr.buffer.write(message)
            exit_code = 127
        finally:
            status = {'command': command, 'exit_code': exit_code, 'started_at_utc': started,
                      'duration_seconds': round(time.monotonic() - clock, 3)}
            commit=subprocess.run(['git','rev-parse','HEAD'],capture_output=True,text=True)
            status['tested_commit_sha']=commit.stdout.strip() if commit.returncode==0 else None
            scope=['airlock','frontend','configs','policies','benchmark','scripts','tests','tests-js','requirements.txt','requirements-dev.txt','pyproject.toml','package.json','package-lock.json','Dockerfile','compose.yaml','.github']
            dirty=subprocess.run(['git','status','--porcelain','--untracked-files=all','--']+scope,capture_output=True,text=True)
            status['tracked_source_dirty']=dirty.returncode!=0 or bool(dirty.stdout.strip()) or start_commit!=status['tested_commit_sha']
            status['started_commit_sha']=start_commit
            log.with_suffix(log.suffix + '.status.json').write_text(json.dumps(status, indent=2) + '\n')
    return exit_code


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('log', type=Path)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('A command is required')
    raise SystemExit(run_logged(args.log, command))
