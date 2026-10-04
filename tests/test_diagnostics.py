"""Synthetic, offline startup checks with no persistent SQLite connections."""
import base64
from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import stat
from types import SimpleNamespace

import pytest

from airlock import diagnostics


BODY = 'window.__fixture="合成预检";'
HASH = "'sha256-" + base64.b64encode(hashlib.sha256(BODY.encode()).digest()).decode() + "'"
SOURCE_ID = '2026-05-05 10:34:17 ' + 'a' * 64


def make_console(root, *, body=BODY):
    root.mkdir()
    assets = root / '_next' / 'static'
    assets.mkdir(parents=True)
    (assets / 'app.js').write_text('window.fixture=true;', encoding='utf-8')
    (assets / 'app.css').write_text('body{color:#123}', encoding='utf-8')
    html = ('<!DOCTYPE html><html><head><link rel="stylesheet" href="/_next/static/app.css">'
            '<link rel="preload" as="script" href="_next/static/app.js">'
            '<script src="/_next/static/app.js"></script></head><body>'
            f'<script>{body}</script></body></html>')
    (root / 'index.html').write_text(html, encoding='utf-8', newline='')
    value = "'sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() + "'"
    (root / 'csp.json').write_text(json.dumps({'script_hashes': [value] if body else []}), encoding='utf-8')
    return root


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden_network(*args, **kwargs):
        pytest.fail('startup preflight attempted network access')
    monkeypatch.setattr(socket, 'create_connection', forbidden_network)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden_network)
    monkeypatch.setattr(socket.socket, 'connect', forbidden_network)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden_network)
    connect = sqlite3.connect
    connections = []
    def only_memory(database, *args, **kwargs):
        assert database == ':memory:', 'startup preflight attempted persistent SQLite access'
        connections.append(database)
        return connect(database, *args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', only_memory)
    def runtime():
        connection = sqlite3.connect(':memory:')
        connection.close()
        return {'version': '3.53.1', 'source_id': SOURCE_ID, 'extra': 'must-never-be-reported'}
    monkeypatch.setattr(diagnostics, 'require_safe_python_runtime', runtime)
    return connections


@pytest.fixture
def inputs(tmp_path):
    console = make_console(tmp_path / 'console')
    environment = {key: 'synthetic-' + str(number) + '-' + 'x' * 32
                   for number, key in enumerate(diagnostics.REQUIRED_KEYS)}
    environment.update(AIRLOCK_DB=str(tmp_path / 'absent' / 'never-opened.sqlite3'),
                       AIRLOCK_OIDC_FILE=str(tmp_path / 'private-oidc-do-not-read.json'),
                       AIRLOCK_REVIEWER_FILE=str(tmp_path / 'private-reviewers-do-not-read.json'),
                       AIRLOCK_AUDIT_KEY_FILE=str(tmp_path / 'private-key-ring-do-not-read.json'),
                       AIRLOCK_SEMANTIC_FILE=str(tmp_path / 'private-model-do-not-read.json'))
    return environment, console


def check(report, identifier):
    return next(item for item in report['checks'] if item['id'] == identifier)


def test_diagnostics_valid_preflight_only_reads_static_build_and_memory_sqlite(inputs, offline, monkeypatch):
    environment, console = inputs
    original = dict(environment)
    reads = []
    open_file = os.open
    def static_only(path, flags, *args, **kwargs):
        assert Path(path) in {console / 'index.html', console / 'csp.json'}
        assert not flags & (os.O_CREAT | os.O_WRONLY | os.O_RDWR)
        reads.append(Path(path).name)
        return open_file(path, flags, *args, **kwargs)
    monkeypatch.setattr(diagnostics.os, 'open', static_only)
    report = diagnostics.collect_checks(environment, console)
    assert report['status'] == 'PASS' and report['scope'] == 'local_startup_preflight'
    assert report['service_started'] is False
    assert report['not_checked'] == ['persistent_database', 'remote_services', 'optional_integrations']
    assert check(report, 'configuration') == {'id': 'configuration', 'status': 'PASS', 'code': 'configuration_valid'}
    assert check(report, 'sqlite_runtime')['version'] == '3.53.1'
    assert check(report, 'sqlite_runtime')['source_id'] == SOURCE_ID
    assert sorted(reads) == ['csp.json', 'index.html'] and offline == [':memory:']
    assert original == environment and not Path(environment['AIRLOCK_DB']).parent.exists()
    text = json.dumps(report)
    assert all(value not in text for value in environment.values())
    assert 'must-never-be-reported' not in text and str(console) not in text


@pytest.mark.parametrize('key,value', [
    ('AIRLOCK_AGENT_TOKEN', 'short-secret-marker'),
    ('AIRLOCK_AUDIT_KEY', None),
    ('AIRLOCK_ORIGIN', 'https://private-name.invalid/path-secret-marker'),
    ('AIRLOCK_TTL', 'not-a-number-secret-marker'),
    ('AIRLOCK_BUDGET_UNITS', '0'),
])
def test_diagnostics_invalid_environment_is_fixed_error_without_value_leak(inputs, key, value):
    environment, console = inputs
    environment[key] = value
    report = diagnostics.collect_checks(environment, console)
    assert report['status'] == 'FAIL'
    assert check(report, 'configuration') == {'id': 'configuration', 'status': 'FAIL', 'code': 'configuration_invalid'}
    assert 'secret-marker' not in json.dumps(report)
    assert check(report, 'console')['status'] == 'PASS'


def test_diagnostics_missing_and_duplicate_credentials_are_not_satisfied_by_process_environment(inputs, monkeypatch):
    from airlock import models
    environment, console = inputs
    monkeypatch.setattr(models, 'os', SimpleNamespace(environ={
        'AIRLOCK_AGENT_TOKEN': 'synthetic-host-value-must-not-fill-explicit-map'}))
    del environment['AIRLOCK_AGENT_TOKEN']
    report = diagnostics.collect_checks(environment, console)
    assert check(report, 'configuration')['code'] == 'configuration_missing'
    environment['AIRLOCK_AGENT_TOKEN'] = environment['AIRLOCK_REVIEWER_TOKEN']
    assert check(diagnostics.collect_checks(environment, console), 'configuration')['code'] == 'configuration_invalid'


def test_diagnostics_never_enumerates_unrelated_integration_credentials(inputs):
    environment, console = inputs
    class CallerMapping(Mapping):
        def __getitem__(self, key):
            assert key not in {'DEEPSEEK_API_KEY', 'AWS_SECRET_ACCESS_KEY', 'AIRLOCK_UPSTREAM_TOKEN'}
            return environment[key]
        def __iter__(self):
            pytest.fail('preflight must not enumerate arbitrary environment credentials')
        def __len__(self):
            return len(environment)
    assert diagnostics.collect_checks(CallerMapping(), console)['status'] == 'PASS'


def test_diagnostics_runtime_exception_is_redacted_and_other_checks_still_run(inputs, monkeypatch):
    def unavailable():
        raise RuntimeError('synthetic-runtime-secret-and-private-path')
    monkeypatch.setattr(diagnostics, 'require_safe_python_runtime', unavailable)
    report = diagnostics.collect_checks(*inputs)
    assert report['status'] == 'FAIL'
    assert check(report, 'sqlite_runtime') == {'id': 'sqlite_runtime', 'status': 'FAIL', 'code': 'sqlite_runtime_unavailable'}
    assert 'synthetic-runtime-secret' not in json.dumps(report)
    assert check(report, 'console')['status'] == 'PASS'


def test_diagnostics_runtime_metadata_does_not_echo_unexpected_text(inputs, monkeypatch):
    monkeypatch.setattr(diagnostics, 'require_safe_python_runtime', lambda: {
        'version': 'secret-version-marker', 'source_id': '/private/runtime/secret-marker', 'token': 'secret-marker'})
    item = check(diagnostics.collect_checks(*inputs), 'sqlite_runtime')
    assert item == {'id': 'sqlite_runtime', 'status': 'PASS', 'code': 'sqlite_runtime_ready'}


@pytest.mark.parametrize('body', ['', ' ', '\nconsole.log("<&");\n', BODY])
def test_console_inline_hashes_match_raw_package_console_algorithm(tmp_path, body):
    console = make_console(tmp_path / 'console', body=body)
    expected = json.loads((console / 'csp.json').read_text())['script_hashes']
    assert diagnostics.validate_console(console) == expected


@pytest.mark.parametrize('newline', ['\r\n', '\r'])
def test_console_browser_newline_normalization_rejects_raw_hash_and_accepts_effective_hash(tmp_path, newline):
    body = newline + 'window.fixture=true;' + newline
    console = make_console(tmp_path / 'console', body=body)
    with pytest.raises(diagnostics.ConsoleValidationError, match='console_csp_mismatch'):
        diagnostics.validate_console(console)
    normalized = body.replace('\r\n', '\n').replace('\r', '\n')
    digest = base64.b64encode(hashlib.sha256(normalized.encode()).digest()).decode()
    hashes = ["'sha256-" + digest + "'"]
    (console / 'csp.json').write_text(json.dumps({'script_hashes': hashes}), encoding='utf-8')
    assert diagnostics.validate_console(console) == hashes


def test_console_nul_preprocessing_cannot_produce_a_false_positive(tmp_path):
    console = make_console(tmp_path / 'console', body='window.fixture="\x00";')
    with pytest.raises(diagnostics.ConsoleValidationError, match='console_index_invalid'):
        diagnostics.validate_console(console)


@pytest.mark.parametrize('filename', ['index.html', 'csp.json', '_next/static/app.js', '_next/static/app.css'])
def test_console_missing_build_files_are_reported(inputs, filename):
    environment, console = inputs
    (console / filename).unlink()
    item = check(diagnostics.collect_checks(environment, console), 'console')
    assert item['status'] == 'FAIL'
    assert item['code'] == ('console_missing' if filename in {'index.html', 'csp.json'} else 'console_asset_missing')
    assert filename not in json.dumps(item)


@pytest.mark.parametrize('contents', [
    '[]', 'null', '{}', '{"script_hashes":"private-value"}',
    '{"script_hashes":["unsafe-inline"]}', '{"script_hashes":[null]}',
    '{"script_hashes":[],"script_hashes":[]}', 'broken-private-json',
    json.dumps({'script_hashes': [HASH, HASH]}),
])
def test_console_invalid_csp_never_returns_manifest_values(inputs, contents):
    environment, console = inputs
    (console / 'csp.json').write_text(contents, encoding='utf-8')
    item = check(diagnostics.collect_checks(environment, console), 'console')
    assert item == {'id': 'console', 'status': 'FAIL', 'code': 'console_csp_invalid'}


def test_console_stale_csp_or_missing_inline_hash_fails(inputs):
    environment, console = inputs
    (console / 'index.html').write_text((console / 'index.html').read_text().replace(BODY, 'window.changed=true;'), encoding='utf-8')
    assert check(diagnostics.collect_checks(environment, console), 'console')['code'] == 'console_csp_mismatch'
    (console / 'csp.json').write_text('{"script_hashes":[]}', encoding='utf-8')
    assert check(diagnostics.collect_checks(environment, console), 'console')['code'] == 'console_csp_mismatch'


@pytest.mark.parametrize('reference', [
    'https://private-host.invalid/app.js', '//private-host.invalid/app.js',
    'file:///private/app.js', 'C:/private/app.js', '/private/app.js',
    '/_next/../private/app.js', '/_next/%2e%2e/private.js', '/_next/static/%61pp.js',
    '/_next\\static\\app.js', '/_next/static/app.js?private=query', '/_next/static/app.js#fragment',
    '/_next//static/app.js', '/_next/static/CON.js', '/_next/static./app.js',
])
def test_console_asset_paths_cannot_escape_or_fetch_remote_files(inputs, reference):
    environment, console = inputs
    html = (console / 'index.html').read_text().replace('/_next/static/app.js', reference)
    (console / 'index.html').write_text(html, encoding='utf-8')
    item = check(diagnostics.collect_checks(environment, console), 'console')
    assert item == {'id': 'console', 'status': 'FAIL', 'code': 'console_asset_invalid'}
    assert reference not in json.dumps(item)


@pytest.mark.parametrize('injection,code', [
    ('<base href="https://private-host.invalid">', 'console_asset_invalid'),
    ('<img src="https://private-host.invalid/image.png">', 'console_asset_invalid'),
    ('<script src="/_next/static/app.js" src="https://private-host.invalid/x.js"></script>', 'console_index_invalid'),
    ('<script src="/_next/static/app.js"/>', 'console_index_invalid'),
])
def test_console_ambiguous_or_remote_asset_markup_rejected(inputs, injection, code):
    environment, console = inputs
    (console / 'index.html').write_text((console / 'index.html').read_text().replace('</head>', injection + '</head>'), encoding='utf-8')
    assert check(diagnostics.collect_checks(environment, console), 'console')['code'] == code


@pytest.mark.parametrize('target_name', ['index.html', 'csp.json', '_next', '_next/static/app.js'])
def test_console_symlink_file_and_parent_metadata_rejected_before_read(inputs, monkeypatch, target_name):
    environment, console = inputs
    target = console / target_name
    original = Path.lstat
    def symbolic(path, *args, **kwargs):
        if path == target:
            return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_file_attributes=0)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'lstat', symbolic)
    assert check(diagnostics.collect_checks(environment, console), 'console')['code'] == 'console_unsafe_path'


def test_console_windows_junction_or_reparse_directory_rejected(inputs, monkeypatch):
    environment, console = inputs
    original = Path.lstat
    def reparse(path, *args, **kwargs):
        if path == console:
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'lstat', reparse)
    assert check(diagnostics.collect_checks(environment, console), 'console')['code'] == 'console_unsafe_path'


@pytest.mark.parametrize('limit_name', ['MAX_INDEX_BYTES', 'MAX_CSP_BYTES', 'MAX_ASSET_BYTES'])
def test_console_size_limits(inputs, monkeypatch, limit_name):
    environment, console = inputs
    monkeypatch.setattr(diagnostics, limit_name, 1)
    assert check(diagnostics.collect_checks(environment, console), 'console')['code'] == 'console_too_large'


def test_console_io_error_is_redacted(inputs, monkeypatch):
    def unreadable(*args, **kwargs):
        raise PermissionError('private-path-and-secret-value')
    monkeypatch.setattr(diagnostics.os, 'open', unreadable)
    report = diagnostics.collect_checks(*inputs)
    assert check(report, 'console')['code'] == 'console_unreadable'
    assert 'private-path-and-secret-value' not in json.dumps(report)


def test_console_missing_directory_does_not_create_it(inputs, tmp_path):
    environment, _ = inputs
    absent = tmp_path / 'missing-console'
    assert check(diagnostics.collect_checks(environment, absent), 'console')['code'] == 'console_missing'
    assert not absent.exists()
