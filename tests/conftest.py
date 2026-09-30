from dataclasses import dataclass
import pytest
from pathlib import Path
from airlock.auth import Auth, add_principal
from airlock.config import Settings
from airlock.policy import Policy
from airlock.runner import LocalRunner
from airlock.service import Service
from airlock.storage import Store
from airlock.target import TargetStore, initialize_target

AGENT_TOKEN = 'test-agent-token-' + 'a'*40
OTHER_TOKEN = 'test-other-token-' + 'b'*40
PASSWORD = 'test-reviewer-' + 'p'*24
SECRET = 'fixture-execution-' + 's'*40

class Clock:
    def __init__(self): self.value = 1801308000.0
    def __call__(self): return self.value
    def advance(self, seconds): self.value += seconds

@dataclass
class System:
    store: Store
    service: Service
    target: TargetStore
    auth: Auth
    agent: dict
    human: dict
    cookie: str
    clock: Clock
    settings: Settings

@pytest.fixture
def system(tmp_path):
    clock = Clock()
    store = Store(tmp_path/'meta.db', clock=clock)
    store.initialize()
    add_principal(store, 'agent', 'agent', 'demo', token=AGENT_TOKEN)
    add_principal(store, 'other-agent', 'agent', 'other', token=OTHER_TOKEN)
    add_principal(store, 'reviewer', 'human', 'demo', username='reviewer', password=PASSWORD)
    target_path = tmp_path/'target.db'
    initialize_target(target_path)
    target = TargetStore(target_path, SECRET, clock=clock)
    settings = Settings(meta_path=store.path, runner_url='http://runner', runner_secret='r'*48,
        execution_secret=SECRET, worker_enabled=False, lease_seconds=2,
        origins=('http://testserver',), allowed_hosts=('testserver',), demo_enabled=True)
    service = Service(store, LocalRunner(target), settings, policy=Policy(approval_ttl_seconds=30))
    auth = Auth(store)
    cookie, _ = auth.login('reviewer', PASSWORD, 'test')
    agent = auth.agent('Bearer '+AGENT_TOKEN)
    human = auth.session(cookie)
    yield System(store, service, target, auth, agent, human, cookie, clock, settings)
    store.close()
