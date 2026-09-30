"""Create-only local initialization and explicit service entry points."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time

from .auth import add_principal
from .client import AgentClient
from .common import canonical
from .demo import SCENARIOS, scenario_request
from .storage import Store
from .target import initialize_target

ROOT = Path(__file__).resolve().parent.parent


def private_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as out: out.write(content)


def load_env(path: Path) -> dict[str, str]:
    """No shell evaluation, expansion, or commands in environment files."""
    result = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'): continue
        key, separator, value = line.partition('=')
        if not separator or not key.startswith('AIRLOCK_') or not key.replace('_','').isalnum():
            raise ValueError('Invalid AIRLOCK environment file')
        if key in result: raise ValueError('Duplicate environment key')
        result[key] = value
    return result


def initialize(data_dir: Path, *, port: int = 8080, runner_port: int = 8090) -> dict:
    root = data_dir.resolve()
    if root.exists() and any(root.iterdir()):
        raise RuntimeError('Initialization is create-only: select a NEW empty directory. Existing data is never reset.')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in ('gateway','runner','agent','human'):
        (root/name).mkdir(mode=0o700)
    service_secret, execution_secret = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    agent_token, password = secrets.token_urlsafe(48), secrets.token_urlsafe(24)
    store = Store(root/'gateway/meta.db'); store.initialize()
    add_principal(store, 'agent', 'agent', 'demo', token=agent_token)
    add_principal(store, 'reviewer', 'human', 'demo', username='reviewer', password=password)
    store.close()
    initialize_target(root/'runner/target.db')
    gateway = {'AIRLOCK_META_DB':str(root/'gateway/meta.db'),
        'AIRLOCK_RUNNER_URL':f'http://127.0.0.1:{runner_port}',
        'AIRLOCK_RUNNER_SECRET':service_secret,'AIRLOCK_EXECUTION_SECRET':execution_secret,
        'AIRLOCK_POLICY':str(ROOT/'policies/default.yaml'),'AIRLOCK_DIST':str(ROOT/'apps/web/dist'),
        'AIRLOCK_ORIGINS':f'http://127.0.0.1:{port},http://localhost:{port}',
        'AIRLOCK_HOSTS':'127.0.0.1,localhost,gateway','AIRLOCK_DEMO':'1'}
    runner = {'AIRLOCK_TARGET_DB':str(root/'runner/target.db'),
        'AIRLOCK_RUNNER_SECRET':service_secret,'AIRLOCK_EXECUTION_SECRET':execution_secret}
    agent = {'AIRLOCK_BASE_URL':f'http://127.0.0.1:{port}','AIRLOCK_AGENT_TOKEN':agent_token}
    for name, values in [('gateway',gateway),('runner',runner),('agent',agent)]:
        private_write(root/name/'.env',''.join(f'{k}={v}\n' for k,v in values.items()))
    private_write(root/'human/credentials.json',json.dumps({'username':'reviewer','password':password},indent=2)+'\n')
    return {'data_dir':str(root),'human_credentials_file':str(root/'human/credentials.json'),
        'gateway_url':agent['AIRLOCK_BASE_URL'], 'source':'synthetic_demo',
        'note':'Local processes share a host identity. Use the Compose boundary for restricted Agent isolation.'}


def service_environment(path: Path) -> dict:
    # Do not inherit another Airlock role's configuration by accident.
    return {k:v for k,v in os.environ.items() if not k.startswith('AIRLOCK_')} | load_env(path)


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description='AIRLOCK · Agent Change Review')
    commands=parser.add_subparsers(dest='command',required=True)
    init=commands.add_parser('init',help='Create a new demo database and independent credentials; never overwrite')
    init.add_argument('--data-dir',type=Path,default=Path('runtime'))
    init.add_argument('--port',type=int,default=8080); init.add_argument('--runner-port',type=int,default=8090)
    serve=commands.add_parser('serve',help='Launch gateway and executor as separate LOCAL processes')
    serve.add_argument('--data-dir',type=Path,default=Path('runtime'))
    serve.add_argument('--port',type=int,default=8080); serve.add_argument('--runner-port',type=int,default=8090)
    for name,port in [('gateway',8080),('runner',8090)]:
        cmd=commands.add_parser(name)
        cmd.add_argument('--env-file',type=Path)
        cmd.add_argument('--host',default='127.0.0.1'); cmd.add_argument('--port',type=int,default=port)
    demo=commands.add_parser('demo',help='Submit a scripted proposal via the Agent-only HTTP API')
    demo.add_argument('scenario',choices=SCENARIOS)
    demo.add_argument('--env-file',type=Path,default=Path('runtime/agent/.env'))
    demo.add_argument('--key',default=None)
    demo.add_argument('--wait',type=float,default=0)
    args=parser.parse_args(argv)
    try:
        if args.command=='init': print(json.dumps(initialize(args.data_dir,port=args.port,runner_port=args.runner_port),ensure_ascii=False,indent=2))
        elif args.command in {'gateway','runner'}:
            if args.env_file:
                for key in list(os.environ):
                    if key.startswith('AIRLOCK_'): del os.environ[key]
                os.environ.update(load_env(args.env_file))
            import uvicorn
            if args.command=='gateway':
                from .api import create_app
            else:
                from .runner_api import create_app
            uvicorn.run(create_app(),host=args.host,port=args.port,proxy_headers=False,access_log=False)
        elif args.command=='serve':
            processes=[]
            try:
                for role,port in [('runner',args.runner_port),('gateway',args.port)]:
                    env=service_environment(args.data_dir/role/'.env')
                    if role=='gateway':
                        env['AIRLOCK_RUNNER_URL']=f'http://127.0.0.1:{args.runner_port}'
                        env['AIRLOCK_ORIGINS']=f'http://127.0.0.1:{args.port},http://localhost:{args.port}'
                    processes.append(subprocess.Popen([sys.executable,'-m','airlock.cli',role,'--port',str(port)],env=env))
                    import httpx
                    with httpx.Client(trust_env=False, timeout=1) as health:
                        for attempt in range(80):
                            if processes[-1].poll() is not None: raise RuntimeError(f'{role} failed to start')
                            try:
                                if health.get(f'http://127.0.0.1:{port}/healthz').status_code == 200: break
                            except httpx.HTTPError: pass
                            time.sleep(.1)
                        else: raise RuntimeError(f'{role} startup health check timed out')
                print(f'Approval workbench: http://127.0.0.1:{args.port}',flush=True)
                while all(p.poll() is None for p in processes): time.sleep(.25)
                raise RuntimeError('One service stopped; stopping its peer. Inspect the preceding error.')
            except KeyboardInterrupt: pass
            finally:
                for process in processes:
                    if process.poll() is None: process.terminate()
                for process in processes:
                    try: process.wait(timeout=15)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
        elif args.command=='demo':
            env=load_env(args.env_file)
            with AgentClient(env['AIRLOCK_BASE_URL'],env['AIRLOCK_AGENT_TOKEN']) as client:
                result=client.submit(scenario_request(args.scenario),args.key or 'demo-'+secrets.token_hex(12))
                if args.wait: result=client.wait(result['id'],timeout=args.wait)
                print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except Exception as exc:
        # Domain errors and configuration exceptions never include environment contents.
        print(f'{type(exc).__name__}: {exc}',file=sys.stderr)
        return 1


if __name__=='__main__': raise SystemExit(main())
