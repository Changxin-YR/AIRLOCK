"""Isolated real HTTP server for acceptance tests; secrets are never printed."""
from __future__ import annotations
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]


def stop_process_tree(process):
    """Terminate only the fixture we spawned, including Windows venv children."""
    if process.poll() is not None: return
    if os.name=='nt':
        result=subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
        if result.returncode and process.poll() is None: process.kill()
    else: process.terminate()
    try: process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill();process.wait(timeout=5)


@contextmanager
def server(overrides=None):
    with tempfile.TemporaryDirectory(prefix='airlock-acceptance-') as directory:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        keys = {name: secrets.token_urlsafe(32) for name in
                ('AIRLOCK_AGENT_TOKEN', 'AIRLOCK_REVIEWER_TOKEN', 'AIRLOCK_AUDIT_KEY')}
        keys['AIRLOCK_DB']=str(Path(directory)/'demo.db')
        env = {k:v for k,v in os.environ.items() if not k.startswith('AIRLOCK_')} | keys | {'AIRLOCK_DB': str(Path(directory) / 'demo.db'),
                                   'AIRLOCK_ORIGIN': url, 'PYTHONPATH': str(ROOT)}
        env.update(overrides or {})
        with open(Path(directory) / 'server.log', 'w') as log:
            process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'airlock.api:create_app',
                '--factory', '--host', '127.0.0.1', '--port', str(port), '--no-access-log'],
                cwd=ROOT, env=env, stdout=log, stderr=log)
            try:
                with httpx.Client(base_url=url, trust_env=False, timeout=3) as client:
                    for _ in range(100):
                        if process.poll() is not None:
                            raise RuntimeError('Acceptance server exited; inspect environment and dependencies.')
                        try:
                            if client.get('/healthz').status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(.05)
                    else:
                        raise RuntimeError('Acceptance server failed to start.')
                    yield url, keys, client
            finally:
                stop_process_tree(process)
