import json
import sqlite3
import pytest
from airlock.cli import initialize,load_env
from airlock.common import AirlockError
from airlock.storage import Store


def test_init_separates_credentials_and_never_resets(tmp_path):
    root=tmp_path/'deployment';initialize(root)
    agent=load_env(root/'agent/.env');gateway=load_env(root/'gateway/.env');runner=load_env(root/'runner/.env')
    assert set(agent)=={'AIRLOCK_BASE_URL','AIRLOCK_AGENT_TOKEN'}
    assert 'AIRLOCK_AGENT_TOKEN' not in gateway and 'AIRLOCK_AGENT_TOKEN' not in runner
    creds=json.loads((root/'human/credentials.json').read_text())
    assert creds['password'] not in str(agent) and creds['password'] not in str(gateway)
    with pytest.raises(RuntimeError):initialize(root)
    with sqlite3.connect(root/'runner/target.db') as conn:
        assert conn.execute('SELECT COUNT(*) FROM customers WHERE project="demo"').fetchone()[0]==1206
    store=Store(root/'gateway/meta.db');store.verify_schema();store.close()


def test_migration_refuses_unversioned_unknown_database(tmp_path):
    path=tmp_path/'legacy.db'
    with sqlite3.connect(path) as conn:conn.execute('CREATE TABLE unknown(x)')
    store=Store(path)
    with pytest.raises(AirlockError):store.initialize()
    with sqlite3.connect(path) as conn:assert conn.execute('SELECT name FROM sqlite_master WHERE name="unknown"').fetchone()
    store.close()


def test_env_parser_does_not_execute_or_accept_duplicate_keys(tmp_path):
    file=tmp_path/'credentials.env'
    file.write_text('AIRLOCK_RUNNER_SECRET=value\nAIRLOCK_RUNNER_SECRET=changed\n')
    with pytest.raises(ValueError):load_env(file)
    file.write_text('AIRLOCK_X=$(echo unsafe)\n')
    assert load_env(file)['AIRLOCK_X']=='$(echo unsafe)'
