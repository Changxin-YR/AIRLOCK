"""Launcher tests use synthetic credentials and never start a server or database."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from airlock import __main__ as launcher


KEYS = ('AIRLOCK_AGENT_TOKEN', 'AIRLOCK_REVIEWER_TOKEN', 'AIRLOCK_AUDIT_KEY')
SYNTHETIC = {key: 'synthetic-' + str(index) + '-' + 'x' * 32 for index, key in enumerate(KEYS)}


@pytest.fixture
def isolated_launcher(tmp_path, monkeypatch):
    # Replace the entire mapping instead of inspecting or copying host secrets.
    environment = {}
    # Replace only this module's OS view; pytest's own environment bookkeeping
    # must not write into the synthetic launcher's mapping.
    monkeypatch.setattr(launcher, 'os', SimpleNamespace(environ=environment, open=os.open))
    monkeypatch.chdir(tmp_path)
    calls = []
    def run(target, **kwargs):
        calls.append({'target': target, **kwargs, 'environment': dict(environment)})
    monkeypatch.setitem(sys.modules, 'uvicorn', SimpleNamespace(run=run))
    def invoke(*arguments):
        monkeypatch.setattr(sys, 'argv', ['airlock', *arguments])
        return launcher.main()
    return tmp_path, environment, calls, invoke


def write_config(path, values=None, encoding='utf-8'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(SYNTHETIC if values is None else values), encoding=encoding)


@pytest.mark.parametrize('target_kind', ['missing', 'directory'])
def test_launcher_explicit_missing_or_nonfile_rejected_before_uvicorn(isolated_launcher, target_kind, capsys):
    root, environment, calls, invoke = isolated_launcher
    environment.update(SYNTHETIC)
    path = root / 'selected-config.json'
    if target_kind == 'directory':
        path.mkdir()
    with pytest.raises(SystemExit) as error:
        invoke('serve', '--config', str(path))
    assert error.value.code == 2 and calls == []
    assert environment == SYNTHETIC and not (root / 'var').exists()
    output = capsys.readouterr()
    assert 'readable regular UTF-8 JSON file' in output.err
    assert not any(secret in output.err + output.out for secret in SYNTHETIC.values())


def test_launcher_default_missing_config_keeps_environment_only_compatibility(isolated_launcher):
    root, environment, calls, invoke = isolated_launcher
    environment.update(SYNTHETIC)
    environment['AIRLOCK_DB'] = str(root / 'never-opened.sqlite3')
    invoke('serve')
    assert len(calls) == 1 and calls[0]['environment'] == environment
    assert calls[0]['target'] == 'airlock.api:create_app' and calls[0]['factory'] is True
    assert calls[0]['host'] == '127.0.0.1' and calls[0]['port'] == 8000
    assert calls[0]['access_log'] is False and not list(root.iterdir())


@pytest.mark.parametrize('explicit,encoding', [(False, 'utf-8'), (True, 'utf-8'), (True, 'utf-8-sig')])
def test_launcher_valid_config_retains_environment_precedence(isolated_launcher, explicit, encoding):
    root, environment, calls, invoke = isolated_launcher
    path = root / ('explicit.json' if explicit else 'var/local.json')
    write_config(path, {**SYNTHETIC, 'AIRLOCK_DB': 'ignored-config-field.sqlite3'}, encoding)
    environment['AIRLOCK_AGENT_TOKEN'] = 'synthetic-environment-agent-' + 'z' * 32
    environment['AIRLOCK_DB'] = str(root / 'environment-only-database.sqlite3')
    invoke('serve', *(['--config', str(path)] if explicit else []))
    assert len(calls) == 1
    assert environment['AIRLOCK_AGENT_TOKEN'].startswith('synthetic-environment-agent-')
    assert environment['AIRLOCK_REVIEWER_TOKEN'] == SYNTHETIC['AIRLOCK_REVIEWER_TOKEN']
    assert environment['AIRLOCK_AUDIT_KEY'] == SYNTHETIC['AIRLOCK_AUDIT_KEY']
    assert environment['AIRLOCK_DB'] == str(root / 'environment-only-database.sqlite3')
    assert not Path(environment['AIRLOCK_DB']).exists()


@pytest.mark.parametrize('contents', [
    b'{"AIRLOCK_AGENT_TOKEN":"synthetic-secret-marker",',
    b'\xffsynthetic-secret-marker',
    b'[]', b'null', b'"synthetic-secret-marker"',
    b'{"AIRLOCK_AGENT_TOKEN":"synthetic-secret-marker","AIRLOCK_AUDIT_KEY":42}',
])
def test_launcher_invalid_configuration_is_sanitized_and_does_not_partially_merge(isolated_launcher, contents, capsys):
    root, environment, calls, invoke = isolated_launcher
    path = root / 'invalid.json'
    path.write_bytes(contents)
    with pytest.raises(SystemExit) as error:
        invoke('serve', '--config', str(path))
    assert error.value.code == 2 and calls == [] and environment == {}
    output = capsys.readouterr()
    assert 'synthetic-secret-marker' not in output.err + output.out
    assert 'Traceback' not in output.err and 'readable regular UTF-8 JSON file' in output.err


def test_launcher_unreadable_configuration_does_not_echo_filesystem_error(isolated_launcher, monkeypatch, capsys):
    root, environment, calls, invoke = isolated_launcher
    path = root / 'unreadable.json'
    write_config(path)
    def denied(*args, **kwargs):
        raise PermissionError('synthetic-private-filesystem-detail')
    monkeypatch.setattr(Path, 'open', denied)
    with pytest.raises(SystemExit) as error:
        invoke('serve', '--config', str(path))
    assert error.value.code == 2 and calls == [] and environment == {}
    assert 'synthetic-private-filesystem-detail' not in capsys.readouterr().err


def test_launcher_default_directory_is_a_controlled_error(isolated_launcher):
    root, environment, calls, invoke = isolated_launcher
    (root / 'var' / 'local.json').mkdir(parents=True)
    environment.update(SYNTHETIC)
    with pytest.raises(SystemExit) as error:
        invoke('serve')
    assert error.value.code == 2 and calls == []


@pytest.mark.parametrize('explicit', [False, True])
def test_launcher_init_stays_exclusive_and_does_not_rotate_existing_config(isolated_launcher, monkeypatch, explicit, capsys):
    root, environment, calls, invoke = isolated_launcher
    counter = iter(SYNTHETIC.values())
    monkeypatch.setattr(launcher.secrets, 'token_urlsafe', lambda _: next(counter))
    path = root / ('other/private.json' if explicit else 'var/local.json')
    arguments = ['init', *(['--config', str(path)] if explicit else [])]
    invoke(*arguments)
    before = path.read_bytes()
    assert json.loads(before) == SYNTHETIC and calls == [] and environment == {}
    assert not any(secret in capsys.readouterr().out for secret in SYNTHETIC.values())
    monkeypatch.setattr(launcher.secrets, 'token_urlsafe', lambda _: 'unused-synthetic-key-' + 'u' * 32)
    with pytest.raises(FileExistsError):
        invoke(*arguments)
    assert path.read_bytes() == before and calls == []


@pytest.mark.parametrize('name,value', [
    ('AIRLOCK_TTL', 'synthetic-input-marker'),
    ('AIRLOCK_ORIGIN', 'http://localhost:synthetic-input-marker'),
    ('AIRLOCK_BUDGET_UNITS', 'synthetic-input-marker'),
    ('AIRLOCK_BUDGET_WINDOW', 'synthetic-input-marker'),
    ('AIRLOCK_AGENT_TOKEN', ''),
])
def test_launcher_invalid_environment_fails_before_start_without_merging_credentials(
        isolated_launcher, name, value, capsys):
    root, environment, calls, invoke = isolated_launcher
    path = root / 'config.json'
    write_config(path)
    environment[name] = value
    before = dict(environment)
    with pytest.raises(SystemExit) as error:
        invoke('serve', '--config', str(path))
    assert error.value.code == 2 and calls == [] and environment == before
    output = capsys.readouterr()
    assert 'invalid AIRLOCK environment configuration' in output.err
    assert 'synthetic-input-marker' not in output.err and 'Traceback' not in output.err
    assert not (root / 'var').exists()


@pytest.mark.parametrize('contents', [
    b'{"AIRLOCK_AGENT_TOKEN":"a","AIRLOCK_AGENT_TOKEN":"b"}',
    b'{"unrecognized":NaN}',
    b'{' + b' ' * launcher.MAX_CONFIG_BYTES + b'}',
    b'[' * 1200 + b']' * 1200,
])
def test_launcher_rejects_ambiguous_or_unbounded_json_before_start(isolated_launcher, contents):
    root, environment, calls, invoke = isolated_launcher
    environment.update(SYNTHETIC)
    path = root / 'invalid.json'
    path.write_bytes(contents)
    with pytest.raises(SystemExit) as error:
        invoke('serve', '--config', str(path))
    assert error.value.code == 2 and calls == [] and environment == SYNTHETIC


@pytest.mark.parametrize('status', ['PASS', 'FAIL'])
def test_doctor_json_preserves_environment_and_never_invokes_uvicorn(
        isolated_launcher, monkeypatch, status, capsys):
    from airlock import diagnostics
    root, environment, calls, invoke = isolated_launcher
    path = root / 'config.json'
    write_config(path)
    environment['AIRLOCK_AGENT_TOKEN'] = 'synthetic-environment-' + 'z' * 32
    before = dict(environment)
    report = {'scope': 'local_startup_preflight', 'status': status,
              'checks': [{'id': 'configuration', 'status': status, 'code': 'test_status'}],
              'not_checked': ['persistent_database', 'remote_services', 'optional_integrations'],
              'service_started': False}
    received = []
    def collect(mapping):
        received.append(dict(mapping))
        return report
    monkeypatch.setattr(diagnostics, 'collect_checks', collect)
    if status == 'PASS':
        invoke('doctor', '--json', '--config', str(path))
    else:
        with pytest.raises(SystemExit) as error:
            invoke('doctor', '--json', '--config', str(path))
        assert error.value.code == 2
    output = capsys.readouterr()
    assert json.loads(output.out) == report and output.err == ''
    assert received == [{**SYNTHETIC, **before}]
    assert environment == before and calls == [] and not (root / 'var').exists()
    assert not any(secret in output.out for secret in (*SYNTHETIC.values(), *before.values()))


def test_doctor_invalid_file_json_is_controlled_even_with_valid_environment(isolated_launcher, capsys):
    root, environment, calls, invoke = isolated_launcher
    environment.update(SYNTHETIC)
    with pytest.raises(SystemExit) as error:
        invoke('doctor', '--json', '--config', str(root / 'missing.json'))
    assert error.value.code == 2 and calls == [] and environment == SYNTHETIC
    output = capsys.readouterr()
    report = json.loads(output.out)
    assert report['status'] == 'FAIL' and report['checks'][0]['code'] == 'configuration_file_invalid'
    assert report['service_started'] is False and output.err == ''


def test_doctor_text_describes_scope_without_values(isolated_launcher, monkeypatch, capsys):
    from airlock import diagnostics
    root, environment, calls, invoke = isolated_launcher
    monkeypatch.setattr(diagnostics, 'collect_checks', lambda _: {
        'scope': 'local_startup_preflight', 'status': 'FAIL',
        'checks': [{'id': 'console', 'status': 'FAIL', 'code': 'console_missing'}],
        'not_checked': ['persistent_database', 'remote_services', 'optional_integrations'],
        'service_started': False})
    with pytest.raises(SystemExit) as error:
        invoke('doctor')
    assert error.value.code == 2 and calls == [] and not list(root.iterdir())
    output = capsys.readouterr()
    assert 'console_missing' in output.out and 'persistent_database' in output.out
    assert 'No service was started' in output.out and output.err == ''


def test_json_switch_does_not_initialize_configuration(isolated_launcher):
    root, environment, calls, invoke = isolated_launcher
    with pytest.raises(SystemExit) as error:
        invoke('init', '--json')
    assert error.value.code == 2 and not list(root.iterdir()) and environment == {} and calls == []
