"""Isolated synthetic inbox fixtures; no real notification is sent externally."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import socket
import sqlite3
import threading
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
import uvicorn

from airlock.alert_delivery import AlertConfig, deliver_alerts
from airlock.alert_inbox import DEFAULT_PORT, MAX_BODY_BYTES, create_app, main


WRITE = 'synthetic-inbox-write-' + 'w' * 32
READ = 'synthetic-inbox-read-' + 'r' * 32
BASE = f'http://127.0.0.1:{DEFAULT_PORT}'
CODE = 'pending_expiry_backlog'


def event(**changes):
    return dict({'version': 1, 'event_id': str(uuid.uuid4()), 'kind': 'alert',
                 'status': 'alert', 'alert_codes': [CODE], 'resolved_codes': []}, **changes)


def auth(token):
    return {'Authorization': 'Bearer ' + token}


def send(client, payload, token=WRITE, **headers):
    return client.post('/airlock/events', json=payload,
                       headers={**auth(token), 'Idempotency-Key': payload['event_id'], **headers})


@pytest.fixture
def inbox(tmp_path):
    database = tmp_path / 'notifications' / 'test.inbox.sqlite3'
    with TestClient(create_app(database, write_token=WRITE, read_token=READ), base_url=BASE) as client:
        yield client, database


def test_inbox_dedup_persistence_conflict_and_no_business_tables(inbox):
    client, database = inbox
    payload = event()
    assert send(client, payload).status_code == 201
    assert send(client, payload).json()['duplicate'] is True
    conflict = send(client, dict(payload, alert_codes=['audit_integrity_failed']))
    assert conflict.status_code == 409
    with TestClient(create_app(database, write_token=WRITE, read_token=READ), base_url=BASE) as restarted:
        assert send(restarted, payload).status_code == 200
        rows = restarted.get('/api/events', headers=auth(READ)).json()['events']
        assert len(rows) == 1 and rows[0]['event_id'] == payload['event_id']
        assert rows[0]['alert_codes'] == [CODE]
    with sqlite3.connect(database) as conn:
        assert {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {'inbox_events', 'sqlite_sequence'}
        assert conn.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
    raw = database.read_bytes()
    assert WRITE.encode() not in raw and READ.encode() not in raw


def test_inbox_concurrent_replays_insert_once_and_conflicts_are_atomic(inbox):
    client, database = inbox
    payload = event()
    with ThreadPoolExecutor(max_workers=12) as pool:
        responses = list(pool.map(lambda _: send(client, payload), range(24)))
    assert [response.status_code for response in responses].count(201) == 1
    assert [response.status_code for response in responses].count(200) == 23
    contenders = [dict(payload, event_id=str(uuid.uuid4())) for _ in range(12)]
    same_id = str(uuid.uuid4())
    contenders += [dict(payload, event_id=same_id, alert_codes=[code])
                   for code in [CODE, 'audit_integrity_failed'] * 6]
    with ThreadPoolExecutor(max_workers=12) as pool:
        contested = list(pool.map(lambda item: send(client, item), contenders))
    assert sum(response.status_code == 201 for response in contested) == 13
    assert sum(response.status_code == 409 for response in contested) == 6
    with sqlite3.connect(database) as conn:
        assert conn.execute('SELECT count(*) FROM inbox_events').fetchone()[0] == 14


def test_inbox_read_and_write_credentials_are_separate_and_never_url_auth(inbox):
    client, _ = inbox
    payload = event()
    for token in (READ, 'wrong', ''):
        assert send(client, payload, token).status_code == 401
    assert send(client, payload).status_code == 201
    for headers in ({}, auth(WRITE), auth('wrong')):
        response = client.get('/api/events', headers=headers)
        assert response.status_code == 401 and payload['event_id'] not in response.text
    assert client.get('/api/events?token=' + READ).status_code == 401
    assert client.get('/api/events?token=ignored', headers=auth(READ)).status_code == 400
    assert client.get('/api/events', headers=auth(READ)).status_code == 200
    for path in ('/approve', '/retry', '/execute', '/actions', '/api/actions', '/docs', '/openapi.json'):
        assert client.post(path, headers=auth(WRITE), json={}).status_code == 404


@pytest.mark.parametrize('changes', [
    {'version': True}, {'version': 2}, {'kind': 'execute'}, {'status': 'approved'},
    {'sql': 'DELETE FROM private_data'}, {'alert_codes': ['unknown']},
    {'alert_codes': [CODE, CODE]}, {'resolved_codes': [CODE]},
    {'alert_codes': []}, {'kind': 'recovery'}, {'event_id': str(uuid.uuid1())},
    {'resolved_codes': [123]}, {'event_id': 'a' * 36},
])
def test_inbox_rejects_non_allowlisted_or_inconsistent_payload(inbox, changes):
    client, _ = inbox
    response = send(client, event(**changes))
    assert response.status_code == 400 and response.json() == {'error_code': 'inbox_payload_rejected'}
    assert client.get('/api/events', headers=auth(READ)).json()['events'] == []


def test_inbox_requires_exact_idempotency_binding_and_unambiguous_json(inbox):
    client, _ = inbox
    payload = event()
    headers = {**auth(WRITE), 'Content-Type': 'application/json', 'Idempotency-Key': payload['event_id']}
    assert send(client, payload, **{'Idempotency-Key': str(uuid.uuid4())}).status_code == 400
    duplicate = json.dumps(payload)[:-1] + ',"version":1}'
    assert client.post('/airlock/events', content=duplicate, headers=headers).status_code == 400
    pairs = list(headers.items()) + [('Idempotency-Key', payload['event_id'])]
    assert client.post('/airlock/events', json=payload, headers=pairs).status_code == 400
    pairs = list(headers.items()) + [('Authorization', 'Bearer ' + WRITE)]
    assert client.post('/airlock/events', json=payload, headers=pairs).status_code == 401
    encoded_headers = [(key.encode(), value.encode()) for key, value in headers.items() if key != 'Idempotency-Key']
    encoded_headers.append((b'Idempotency-Key', b'\x80' * 36))
    assert client.post('/airlock/events', json=payload, headers=encoded_headers).status_code == 400
    assert client.post('/airlock/events', content='[' * 1500 + ']' * 1500, headers=headers).status_code == 400


def test_inbox_body_limits_content_type_and_streamed_overflow(inbox):
    client, _ = inbox
    headers = {**auth(WRITE), 'Idempotency-Key': str(uuid.uuid4()), 'Content-Type': 'application/json'}
    assert client.post('/airlock/events', content=b'x' * (MAX_BODY_BYTES + 1), headers=headers).status_code == 413
    assert client.post('/airlock/events', content=b'{}', headers={**headers, 'Content-Length': '9' * 5000}).status_code == 413
    assert client.post('/airlock/events', content=b'{}', headers={**headers, 'Content-Encoding': 'gzip'}).status_code == 415
    assert client.post('/airlock/events', content=b'{}', headers={**headers, 'Content-Type': 'text/plain'}).status_code == 415
    with TestClient(client.app, base_url=BASE) as streaming:
        response = streaming.post('/airlock/events', content=iter([b'x' * 3000, b'y' * 3000]), headers=headers)
    assert response.status_code == 413


def test_inbox_rejects_dns_rebinding_cross_origin_and_duplicate_host(inbox):
    client, _ = inbox
    for headers in ({'Host': 'attacker.invalid'}, {'Host': '127.0.0.1:80'},
                    {'Origin': 'https://attacker.invalid'}, {'Origin': 'null'},
                    {'Sec-Fetch-Site': 'cross-site'},
                    [('Host', f'127.0.0.1:{DEFAULT_PORT}'), ('Host', 'attacker.invalid')]):
        assert client.get('/', headers=headers).status_code == 403
    assert client.get('/', headers={'Origin': BASE}).status_code == 200
    assert client.get('/', headers={'Host': f'localhost:{DEFAULT_PORT}'}).status_code == 200
    response = client.options('/api/events', headers={'Origin': 'https://attacker.invalid'})
    assert response.status_code == 403 and 'access-control-allow-origin' not in response.headers


def test_inbox_static_page_contains_no_events_credentials_or_inline_script(inbox):
    client, _ = inbox
    payload = event()
    send(client, payload)
    for path in ('/', '/static/alert-inbox.js', '/static/alert-inbox.css', '/api/events'):
        response = client.get(path)
        assert response.headers['cache-control'] == 'no-store'
        assert "default-src 'none'" in response.headers['content-security-policy']
        assert 'access-control-allow-origin' not in response.headers
        assert not any(secret in response.text for secret in (READ, WRITE, payload['event_id']))
    source = client.get('/static/alert-inbox.js').text
    assert '.innerHTML' not in source and 'localStorage' not in source and 'sessionStorage' not in source
    assert 'textContent' in source and "addEventListener('pagehide', logout)" in source
    assert client.get('/static/../alert_inbox.py').status_code == 404


def test_inbox_pagination_has_stable_cursor_and_validated_limits(inbox):
    client, _ = inbox
    ids = [event() for _ in range(5)]
    for item in ids:
        assert send(client, item).status_code == 201
    first = client.get('/api/events?limit=2', headers=auth(READ)).json()
    assert [row['event_id'] for row in first['events']] == [ids[4]['event_id'], ids[3]['event_id']]
    send(client, event())
    second = client.get('/api/events?limit=2&before=' + str(first['next_before']), headers=auth(READ)).json()
    assert [row['event_id'] for row in second['events']] == [ids[2]['event_id'], ids[1]['event_id']]
    for query in ('limit=101', 'limit=0', 'before=-1', 'before=9223372036854775808', 'limit=2&limit=3', 'other=1'):
        assert client.get('/api/events?' + query, headers=auth(READ)).status_code == 400


def test_inbox_rejects_other_existing_database_without_modifying_it(tmp_path):
    path = tmp_path / 'business.sqlite3'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE protected (value TEXT)')
        conn.execute("INSERT INTO protected VALUES('untouched')")
    original = path.read_bytes()
    with pytest.raises(ValueError, match='not an AIRLOCK inbox'):
        create_app(path, write_token=WRITE, read_token=READ)
    assert path.read_bytes() == original
    with pytest.raises(ValueError, match='must differ'):
        create_app(tmp_path / 'never-created.sqlite3', write_token=WRITE, read_token=WRITE)
    assert not (tmp_path / 'never-created.sqlite3').exists()


def test_inbox_storage_busy_is_retryable_and_preserves_original_event(inbox):
    client, database = inbox
    payload = event()
    with sqlite3.connect(database, isolation_level=None) as locker:
        locker.execute('BEGIN IMMEDIATE')
        response = send(client, payload)
        assert response.status_code == 503
        locker.rollback()
    assert send(client, payload).status_code == 201
    assert send(client, payload).status_code == 200


def test_inbox_unsafe_runtime_fails_before_any_database_files(tmp_path, monkeypatch):
    import airlock.alert_inbox as module
    path = tmp_path / 'missing' / 'inbox.sqlite3'
    def refuse():
        raise RuntimeError('unconfirmed runtime')
    monkeypatch.setattr(module, 'require_safe_python_runtime', refuse)
    with pytest.raises(RuntimeError, match='unconfirmed'):
        create_app(path, write_token=WRITE, read_token=READ)
    assert not path.parent.exists()


def test_inbox_unsafe_runtime_leaves_existing_database_unopened(inbox, monkeypatch):
    import airlock.alert_inbox as module
    client, database = inbox
    send(client, event())
    original = {path.name: path.read_bytes() for path in database.parent.iterdir()}
    def refuse():
        raise RuntimeError('unconfirmed runtime')
    def unexpected_connect(*args, **kwargs):
        pytest.fail('persistent database was opened before runtime preflight')
    monkeypatch.setattr(module, 'require_safe_python_runtime', refuse)
    monkeypatch.setattr(module.sqlite3, 'connect', unexpected_connect)
    with pytest.raises(RuntimeError, match='unconfirmed'):
        create_app(database, write_token=WRITE, read_token=READ)
    assert {path.name: path.read_bytes() for path in database.parent.iterdir()} == original


def test_inbox_cli_restricts_var_and_does_not_print_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as outside:
        main(['--database', 'outside.sqlite3'])
    assert outside.value.code == 2
    monkeypatch.setenv('AIRLOCK_INBOX_WRITE_TOKEN', WRITE)
    monkeypatch.setenv('AIRLOCK_INBOX_READ_TOKEN', WRITE)
    with pytest.raises(SystemExit) as duplicate:
        main(['--database', 'var/inbox.sqlite3'])
    assert duplicate.value.code == 2 and WRITE not in capsys.readouterr().err
    assert not (tmp_path / 'var').exists()


@contextmanager
def live_inbox(tmp_path):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    port = listener.getsockname()[1]
    app = create_app(tmp_path / 'live.inbox.sqlite3', write_token=WRITE, read_token=READ, port=port)
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, access_log=False, log_level='error', proxy_headers=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{port}'
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()
        assert not thread.is_alive()


def test_actual_local_sender_receiver_alert_recovery_and_receiver_restart(tmp_path, monkeypatch):
    monkeypatch.setenv('AIRLOCK_ALERT_WEBHOOK_TOKEN', WRITE)
    with live_inbox(tmp_path) as origin:
        config = AlertConfig(endpoint=origin + '/airlock/events', allow_loopback_fixture=True)
        first = deliver_alerts(config, {'status': 'alert', 'alerts': [{'code': CODE}]}, tmp_path / 'outbox.sqlite3')
        assert first['status'] == 'delivered'
        recovery = deliver_alerts(config, {'status': 'ok', 'alerts': []}, tmp_path / 'outbox.sqlite3')
        assert recovery['status'] == 'delivered'
        with httpx.Client(base_url=origin, trust_env=False) as client:
            rows = client.get('/api/events', headers=auth(READ)).json()['events']
            assert [row['kind'] for row in rows] == ['recovery', 'alert']
            original = {key: rows[1][key] for key in ('version', 'event_id', 'kind', 'status', 'alert_codes', 'resolved_codes')}
            assert send(client, original).json()['duplicate'] is True
    restarted = create_app(tmp_path / 'live.inbox.sqlite3', write_token=WRITE, read_token=READ)
    with TestClient(restarted, base_url=BASE) as client:
        assert len(client.get('/api/events', headers=auth(READ)).json()['events']) == 2
