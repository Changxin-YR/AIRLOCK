"""Real subprocess services with temporary databases and generated credentials."""
from __future__ import annotations
import contextlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import httpx
from airlock.cli import initialize, service_environment, load_env

ROOT=Path(__file__).resolve().parent.parent


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


class LiveSystem:
    def __init__(self,root:Path):
        self.root=root;self.port=free_port();self.runner_port=free_port()
        while self.runner_port==self.port:self.runner_port=free_port()
        initialize(root,port=self.port,runner_port=self.runner_port)
        self.url=f'http://127.0.0.1:{self.port}';self.processes={};self.logs=[]
        self.agent_config=load_env(root/'agent/.env')
        self.human_credentials=json.loads((root/'human/credentials.json').read_text())
        self.http=httpx.Client(base_url=self.url,timeout=10,trust_env=False)
    def start_role(self,role):
        port=self.port if role=='gateway' else self.runner_port
        stream=(self.root/role/'process.log').open('a');self.logs.append(stream)
        env=service_environment(self.root/role/'.env')
        self.processes[role]=subprocess.Popen([sys.executable,'-m','airlock.cli',role,'--port',str(port)],
            cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
        for _ in range(100):
            if self.processes[role].poll() is not None: raise RuntimeError('Service exited: '+role)
            try:
                response=httpx.get(f'http://127.0.0.1:{port}/healthz',timeout=.2,trust_env=False)
                if response.status_code==200:return
            except httpx.HTTPError:pass
            time.sleep(.05)
        raise RuntimeError('Service did not become healthy: '+role)
    def start(self):
        self.start_role('runner');self.start_role('gateway');return self
    def login(self):
        response=self.http.post('/api/session',json=self.human_credentials,headers={'Origin':self.url})
        response.raise_for_status()
        self.http.headers.update({'Origin':self.url,'X-CSRF-Token':response.json()['csrf']})
        return response.json()
    def wait(self,operation_id,states,timeout=10):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            response=self.http.get('/api/operations/'+operation_id);response.raise_for_status();op=response.json()
            if op['state'] in states:return op
            time.sleep(.1)
        raise AssertionError('Operation did not reach expected state: '+op['state'])
    def stop_role(self,role):
        process=self.processes.pop(role,None)
        if process:
            process.terminate()
            try:process.wait(timeout=12)
            except subprocess.TimeoutExpired:process.kill();process.wait()
    def close(self):
        for role in list(self.processes):self.stop_role(role)
        self.http.close()
        for stream in self.logs:stream.close()
    def __enter__(self):return self.start()
    def __exit__(self,*args):self.close()
