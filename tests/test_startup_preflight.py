"""Startup checks run before any application database construction."""
import base64
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from airlock import api
from airlock.models import Settings


def console_build(root):
    console = root / 'console'
    (console / '_next').mkdir(parents=True)
    (console / '_next' / 'app.js').write_text('/* synthetic asset */', encoding='utf-8')
    inline = 'self.syntheticStartupCheck = 1;'
    (console / 'index.html').write_text(
        '<!doctype html><html><head><script src="/_next/app.js"></script>'
        f'<script>{inline}</script></head><body>AIRLOCK</body></html>', encoding='utf-8')
    digest = "'sha256-" + base64.b64encode(hashlib.sha256(inline.encode()).digest()).decode() + "'"
    (console / 'csp.json').write_text(json.dumps({'script_hashes': [digest]}), encoding='utf-8')
    return console


@pytest.mark.parametrize('fault', ['malformed_csp', 'missing_csp', 'missing_index', 'mismatched_csp', 'missing_asset'])
@pytest.mark.parametrize('existing', [False, True])
def test_invalid_console_fails_before_database_access(settings, tmp_path, monkeypatch, fault, existing):
    console = console_build(tmp_path)
    if fault == 'malformed_csp':
        (console / 'csp.json').write_text('{synthetic-private-marker', encoding='utf-8')
    elif fault == 'missing_csp':
        (console / 'csp.json').unlink()
    elif fault == 'missing_index':
        (console / 'index.html').unlink()
    elif fault == 'mismatched_csp':
        (console / 'csp.json').write_text('{"script_hashes":[]}', encoding='utf-8')
    else:
        (console / '_next' / 'app.js').unlink()
    database = tmp_path / 'private-state' / 'database.sqlite'
    if existing:
        database.parent.mkdir()
        database.write_bytes(b'unchanged synthetic database sentinel')
    configured = replace(settings, database=database)
    monkeypatch.setattr(api, 'CONSOLE', console)
    def forbidden_gate(*args, **kwargs):
        pytest.fail('console failure reached Gate/database construction')
    monkeypatch.setattr(api, 'Gate', forbidden_gate)
    with pytest.raises(ValueError, match='console build is incomplete or invalid') as error:
        api.create_app(configured)
    assert 'synthetic-private-marker' not in str(error.value)
    if existing:
        assert database.read_bytes() == b'unchanged synthetic database sentinel'
        assert list(database.parent.iterdir()) == [database]
    else:
        assert not database.parent.exists()


def test_complete_console_starts_and_emits_bound_csp(settings, tmp_path, monkeypatch):
    console = console_build(tmp_path)
    monkeypatch.setattr(api, 'CONSOLE', console)
    with TestClient(api.create_app(settings), base_url=settings.origin) as client:
        response = client.get('/')
        hashes = json.loads((console / 'csp.json').read_text())['script_hashes']
        assert response.status_code == 200
        assert hashes[0] in response.headers['content-security-policy']
        assert client.get('/_next/app.js').status_code == 200


def test_headless_api_keeps_liveness_separate_from_console_readiness(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(api, 'CONSOLE', tmp_path / 'no-console')
    with TestClient(api.create_app(settings), base_url=settings.origin) as client:
        assert client.get('/healthz').status_code == 200
        response = client.get('/')
        assert response.status_code == 503 and response.json()['error'] == 'console_assets_missing'


@pytest.mark.parametrize('key,value', [
    ('AIRLOCK_TTL', 'private-synthetic-marker'),
    ('AIRLOCK_ORIGIN', 'http://localhost:private-synthetic-marker'),
    ('AIRLOCK_BUDGET_UNITS', 'private-synthetic-marker'),
    ('AIRLOCK_AGENT_TOKEN', 'short'),
])
def test_direct_settings_validation_never_echoes_environment(key, value, tmp_path):
    environment = {'AIRLOCK_AGENT_TOKEN': 'a' * 32, 'AIRLOCK_REVIEWER_TOKEN': 'r' * 32,
                   'AIRLOCK_AUDIT_KEY': 'k' * 32, 'AIRLOCK_DB': str(tmp_path / 'untouched' / 'db')}
    environment[key] = value
    before = dict(environment)
    with pytest.raises(ValueError, match='invalid AIRLOCK environment configuration') as error:
        Settings.from_env(environment)
    assert 'private-synthetic-marker' not in str(error.value)
    assert error.value.__suppress_context__ and environment == before and not list(tmp_path.iterdir())


def test_empty_explicit_settings_mapping_does_not_read_host_environment(monkeypatch):
    import airlock.models as models
    class ForbiddenEnvironment(dict):
        def __getitem__(self, key):
            pytest.fail('read host environment')
        def get(self, key, *args):
            pytest.fail('read host environment')
    monkeypatch.setattr(models, 'os', SimpleNamespace(environ=ForbiddenEnvironment()))
    with pytest.raises(ValueError, match='invalid AIRLOCK environment configuration'):
        Settings.from_env({})


@pytest.mark.skipif(os.name == 'nt', reason='ENVIRONMENT BLOCKED: real POSIX symlinks are verified on Linux CI')
@pytest.mark.parametrize('kind', ['asset', 'directory', 'root'])
def test_console_real_symlinks_rejected(tmp_path, kind):
    from airlock.diagnostics import ConsoleValidationError, validate_console
    console = console_build(tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'app.js').write_text('/* synthetic external asset */', encoding='utf-8')
    if kind == 'asset':
        (console / '_next' / 'app.js').unlink()
        (console / '_next' / 'app.js').symlink_to(outside / 'app.js')
    elif kind == 'directory':
        (console / '_next' / 'app.js').unlink()
        (console / '_next').rmdir()
        (console / '_next').symlink_to(outside, target_is_directory=True)
    else:
        link = tmp_path / 'console-link'
        link.symlink_to(console, target_is_directory=True)
        console = link
    with pytest.raises(ConsoleValidationError, match='console_unsafe_path'):
        validate_console(console)
    assert (outside / 'app.js').read_text(encoding='utf-8') == '/* synthetic external asset */'
