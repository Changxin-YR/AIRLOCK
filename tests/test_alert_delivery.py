from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from airlock.alert_delivery import AlertConfig, deliver_alerts


TOKEN = 'synthetic-webhook-token-' + 'w' * 32
REVIEWER = 'synthetic-reviewer-token-' + 'r' * 32
CODE = 'pending_expiry_backlog'


def report(*codes):
    return {'status': 'alert' if codes else 'ok',
            'alerts': [{'code': code, 'severity': 'warning', 'count': 42} for code in codes],
            'recommended_exit_code': 2 if codes else 0,
            'sql': 'DELETE FROM secret_customer_data', 'principal': 'private-user@example.invalid',
            'token': REVIEWER, 'checked_at': 123456789}


@contextmanager
def receiver():
    state = {'status': 204, 'mode': 'reply', 'received': [], 'effects': set(), 'report': report(CODE), 'gets': []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            payload = json.loads(body)
            state['received'].append({'path': self.path, 'body': payload,
                                      'authorization': self.headers.get('Authorization'),
                                      'idempotency_key': self.headers.get('Idempotency-Key')})
            if state['mode'] == 'drop':
                state['effects'].add(payload['event_id'])
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            if state['mode'] == 'slow':
                time.sleep(0.2)
            if 200 <= state['status'] < 300:
                state['effects'].add(payload['event_id'])
            self.send_response(state['status'])
            if state['status'] == 302:
                self.send_header('Location', state['origin'] + '/redirected')
            self.send_header('Content-Length', '0')
            self.end_headers()

        def do_GET(self):
            state['gets'].append((self.path, self.headers.get('Authorization')))
            body = json.dumps(state['report']).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    state['origin'] = f'http://127.0.0.1:{server.server_port}'
    state['endpoint'] = state['origin'] + '/airlock/events'
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.fixture
def webhook(monkeypatch):
    monkeypatch.setenv('AIRLOCK_ALERT_WEBHOOK_TOKEN', TOKEN)
    with receiver() as state:
        yield state


def config(webhook, **overrides):
    return AlertConfig(endpoint=webhook['endpoint'], allow_loopback_fixture=True, **overrides)


def events(path):
    with sqlite3.connect(path) as conn:
        return conn.execute('SELECT event_id,delivery_state,attempts,payload FROM notification_events ORDER BY seq').fetchall()


def test_actual_delivery_persistent_dedup_recovery_and_no_sensitive_payload(webhook, tmp_path, monkeypatch):
    state = tmp_path / 'outbox.sqlite'
    # No environment proxy may see the dedicated bearer or payload.
    for name in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'):
        monkeypatch.setenv(name, 'http://127.0.0.1:1')
    monkeypatch.setenv('NO_PROXY', '')
    first = deliver_alerts(config(webhook), report(CODE), state)
    assert first['status'] == 'delivered' and first['pending_count'] == 0
    assert len(webhook['received']) == 1
    incoming = webhook['received'][0]
    assert incoming['authorization'] == 'Bearer ' + TOKEN
    assert incoming['idempotency_key'] == first['event_ids'][0] == incoming['body']['event_id']
    assert incoming['body'] == {'version': 1, 'event_id': first['event_ids'][0], 'kind': 'alert',
                                'status': 'alert', 'alert_codes': [CODE], 'resolved_codes': []}
    # A new config object/connection represents the next scheduler process.
    assert deliver_alerts(config(webhook), report(CODE), state)['status'] == 'unchanged'
    assert len(webhook['received']) == 1
    recovered = deliver_alerts(config(webhook), report(), state)
    assert recovered['status'] == 'delivered' and recovered['event_ids'] != first['event_ids']
    assert webhook['received'][-1]['body']['kind'] == 'recovery'
    assert webhook['received'][-1]['body']['resolved_codes'] == [CODE]
    assert deliver_alerts(config(webhook), report(), state)['status'] == 'unchanged'
    assert len(webhook['received']) == 2
    serialized = json.dumps([x['body'] for x in webhook['received']]) + json.dumps([first, recovered])
    disk = state.read_bytes()
    for sensitive in ('DELETE', 'secret_customer_data', 'private-user', REVIEWER, TOKEN):
        assert sensitive not in serialized and sensitive.encode() not in disk
    assert all(row[1:3] == ('delivered', 1) for row in events(state))


def test_initial_healthy_is_quiet_and_changed_codes_emit_partial_recovery(webhook, tmp_path):
    state = tmp_path / 'outbox.sqlite'
    assert deliver_alerts(config(webhook), report(), state)['status'] == 'unchanged'
    assert webhook['received'] == []
    deliver_alerts(config(webhook), report(CODE, 'audit_integrity_failed'), state)
    deliver_alerts(config(webhook), report('audit_integrity_failed'), state)
    assert len(webhook['received']) == 2
    partial = webhook['received'][-1]['body']
    assert partial['status'] == 'alert' and partial['resolved_codes'] == [CODE]


@pytest.mark.parametrize('status', [302, 401, 429, 500])
def test_http_failures_and_redirects_never_acknowledge_and_keep_event_id(webhook, tmp_path, status):
    state = tmp_path / 'outbox.sqlite'
    webhook['status'] = status
    failed = deliver_alerts(config(webhook), report(CODE), state)
    assert failed['status'] == 'failed' and failed['pending_count'] == 1
    assert events(state)[0][1:3] == ('failed', 1)
    assert len(webhook['received']) == 1 and webhook['received'][0]['path'] == '/airlock/events'
    webhook['status'] = 204
    retried = deliver_alerts(config(webhook), report(CODE), state)
    assert retried['status'] == 'delivered' and retried['event_ids'] == [failed['event_id']]
    assert [x['idempotency_key'] for x in webhook['received']] == [failed['event_id']] * 2
    assert events(state)[0][1:3] == ('delivered', 2)


def test_lost_response_retries_same_event_and_orders_recovery_after_alert(webhook, tmp_path):
    state = tmp_path / 'outbox.sqlite'
    webhook['mode'] = 'drop'
    unknown = deliver_alerts(config(webhook), report(CODE), state)
    assert unknown['status'] == 'unknown' and unknown['pending_count'] == 1
    assert events(state)[0][1] == 'unknown'
    assert len(webhook['effects']) == 1  # Accepted remotely, response deliberately lost.
    webhook['mode'] = 'reply'
    recovered = deliver_alerts(config(webhook), report(), state)
    assert recovered['status'] == 'delivered' and recovered['pending_count'] == 0
    assert recovered['event_ids'][0] == unknown['event_id']
    incoming = webhook['received']
    assert [x['body']['kind'] for x in incoming] == ['alert', 'alert', 'recovery']
    assert incoming[0]['idempotency_key'] == incoming[1]['idempotency_key']
    assert len(webhook['effects']) == 2  # Receiver deduplicates retries.


def test_timeout_is_unknown_and_never_delivered(webhook, tmp_path):
    webhook['mode'] = 'slow'
    state = tmp_path / 'outbox.sqlite'
    result = deliver_alerts(config(webhook, timeout_seconds=0.03), report(CODE), state)
    assert result['status'] == 'unknown' and result['pending_count'] == 1
    assert events(state)[0][1] == 'unknown'


def test_remote_acceptance_then_local_commit_failure_keeps_original_id(webhook, tmp_path, monkeypatch):
    import airlock.alert_delivery as delivery
    state = tmp_path / 'outbox.sqlite'
    original = delivery._connect
    class CommitFailure:
        def __init__(self, conn):
            self.conn, self.commits = conn, 0
        def __getattr__(self, name):
            return getattr(self.conn, name)
        def commit(self):
            self.commits += 1
            if self.commits == 2:
                raise sqlite3.OperationalError('simulated commit failure after remote acceptance')
            return self.conn.commit()
    monkeypatch.setattr(delivery, '_connect', lambda path: CommitFailure(original(path)))
    unknown = deliver_alerts(config(webhook), report(CODE), state)
    assert unknown['status'] == 'unknown'
    assert unknown['event_id'] == webhook['received'][0]['idempotency_key']
    assert events(state)[0][1] == 'pending' and len(webhook['effects']) == 1
    monkeypatch.setattr(delivery, '_connect', original)
    retry = deliver_alerts(config(webhook), report(CODE), state)
    assert retry['event_ids'] == [unknown['event_id']]
    assert len(webhook['received']) == 2 and len(webhook['effects']) == 1


def test_failed_recovery_is_retried_without_false_healthy_ack(webhook, tmp_path):
    state = tmp_path / 'outbox.sqlite'
    deliver_alerts(config(webhook), report(CODE), state)
    webhook['status'] = 503
    failed = deliver_alerts(config(webhook), report(), state)
    assert failed['status'] == 'failed' and failed['pending_count'] == 1
    webhook['status'] = 204
    success = deliver_alerts(config(webhook), report(), state)
    assert success['event_ids'] == [failed['event_id']]
    assert webhook['received'][-1]['body']['kind'] == 'recovery'


def test_target_and_credential_changes_do_not_swallow_active_alert(webhook, tmp_path, monkeypatch):
    state = tmp_path / 'outbox.sqlite'
    first = deliver_alerts(config(webhook), report(CODE), state)
    with receiver() as second:
        moved = deliver_alerts(config(second), report(CODE), state)
        assert moved['status'] == 'delivered' and len(second['received']) == 1
        assert moved['event_ids'] != first['event_ids']
    returned = deliver_alerts(config(webhook), report(CODE), state)
    assert returned['status'] == 'delivered' and returned['event_ids'] != first['event_ids']
    rotated = TOKEN + '-rotated'
    monkeypatch.setenv('AIRLOCK_ALERT_WEBHOOK_TOKEN', rotated)
    assert deliver_alerts(config(webhook), report(CODE), state)['status'] == 'delivered'
    assert webhook['received'][-1]['authorization'] == 'Bearer ' + rotated
    assert rotated.encode() not in state.read_bytes()


def test_failed_old_destination_is_never_retried_to_new_destination(webhook, tmp_path):
    state = tmp_path / 'outbox.sqlite'
    webhook['status'] = 500
    old = deliver_alerts(config(webhook), report(CODE), state)
    with receiver() as second:
        new = deliver_alerts(config(second), report(CODE), state)
        assert new['status'] == 'delivered' and len(second['received']) == 1
        assert old['event_id'] != second['received'][0]['idempotency_key']
    assert events(state)[0][1] == 'failed'


def test_concurrent_schedulers_serialize_without_duplicate_delivery(webhook, tmp_path):
    state = tmp_path / 'outbox.sqlite'
    deliver_alerts(config(webhook), report(), state)
    webhook['mode'] = 'slow'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: deliver_alerts(config(webhook), report(CODE), state), range(2)))
    assert sorted(x['status'] for x in results) == ['delivered', 'unchanged']
    assert len(webhook['received']) == 1


@pytest.mark.parametrize('endpoint,pins,loopback', [
    ('http://8.8.8.8/events', [], False),
    ('https://unconfigured.example/events', [], False),
    ('https://metadata.example/events', ['169.254.169.254'], False),
    ('https://127.0.0.1/events', [], False),
    ('http://10.0.0.1/events', ['10.0.0.1'], True),
    ('https://user:secret@webhook.example/events', ['8.8.8.8'], False),
    ('https://webhook.example/events?token=secret', ['8.8.8.8'], False),
    ('https://webhook.example/events#fragment', ['8.8.8.8'], False),
    ('https://webhook.example/events\n', ['8.8.8.8'], False),
])
def test_fixed_endpoint_configuration_rejects_unsafe_destinations(endpoint, pins, loopback):
    with pytest.raises(ValueError):
        AlertConfig(endpoint=endpoint, address_pins=pins, allow_loopback_fixture=loopback)


def test_dns_outside_operator_pin_is_blocked_before_receiver(webhook, tmp_path, monkeypatch):
    original = socket.getaddrinfo
    def resolve(host, port, *args, **kwargs):
        if host == 'webhook.example':
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.2', port))]
        return original(host, port, *args, **kwargs)
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    cfg = AlertConfig(endpoint=webhook['endpoint'].replace('127.0.0.1', 'webhook.example'),
                      address_pins=['127.0.0.1'], allow_loopback_fixture=True)
    result = deliver_alerts(cfg, report(CODE), tmp_path / 'outbox.sqlite')
    assert result['status'] == 'blocked' and webhook['received'] == []


@pytest.mark.parametrize('token', [None, '', ' ', 'short', 'invalid\ntoken-' + 'x' * 32])
def test_missing_or_invalid_dedicated_credential_never_sends(webhook, tmp_path, monkeypatch, token):
    if token is None:
        monkeypatch.delenv('AIRLOCK_ALERT_WEBHOOK_TOKEN', raising=False)
    else:
        monkeypatch.setenv('AIRLOCK_ALERT_WEBHOOK_TOKEN', token)
    monkeypatch.setenv('AIRLOCK_REVIEWER_TOKEN', REVIEWER)
    result = deliver_alerts(config(webhook), report(CODE), tmp_path / 'outbox.sqlite')
    assert result['status'] == 'blocked' and webhook['received'] == []


@pytest.mark.parametrize('bad_report', [
    {'status': 'alert', 'alerts': [{'code': 'DELETE FROM customers'}]},
    {'status': 'ok', 'alerts': [{'code': CODE}]},
    {'status': 'alert', 'alerts': []},
    {'status': 'alert', 'alerts': [{'code': CODE}, {'code': CODE}]},
    {'status': 'alert', 'alerts': [{'code': ['private-text']}]},
])
def test_unknown_or_inconsistent_health_payload_cannot_be_exfiltrated(webhook, tmp_path, bad_report):
    result = deliver_alerts(config(webhook), bad_report, tmp_path / 'outbox.sqlite')
    assert result['status'] == 'blocked' and webhook['received'] == []


def test_corrupt_notification_state_fails_closed_without_sending(webhook, tmp_path):
    state = tmp_path / 'outbox.sqlite'
    state.write_text('corrupt-not-a-database')
    assert deliver_alerts(config(webhook), report(CODE), state)['status'] == 'blocked'
    assert webhook['received'] == []


def run_check(webhook, tmp_path, *extra):
    # Use synthetic credentials, never the operator's real reviewer credential.
    env = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR', 'PATH', 'TEMP', 'TMP') if key in os.environ}
    env.update(AIRLOCK_REVIEWER_TOKEN=REVIEWER, AIRLOCK_ALERT_WEBHOOK_TOKEN=TOKEN)
    return subprocess.run([sys.executable, 'scripts/operational_check.py', '--url', webhook['origin'],
                           '--output', str(tmp_path / 'report.json'), *extra],
                          cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=15)


def test_operator_cli_default_quiet_then_delivery_dedup_recovery_and_failure(webhook, tmp_path):
    default = run_check(webhook, tmp_path)
    assert default.returncode == 2, default.stderr
    assert webhook['received'] == []
    cfg = tmp_path / 'alert.json'
    cfg.write_text(config(webhook).model_dump_json())
    flags = ('--alert-config', str(cfg), '--alert-state', str(tmp_path / 'outbox.sqlite'))
    delivered = run_check(webhook, tmp_path, *flags)
    assert delivered.returncode == 2, delivered.stderr
    assert json.loads(delivered.stdout)['notification']['status'] == 'delivered'
    duplicate = run_check(webhook, tmp_path, *flags)
    assert duplicate.returncode == 2 and len(webhook['received']) == 1
    webhook['report'] = report()
    webhook['status'] = 500
    failed = run_check(webhook, tmp_path, *flags)
    assert failed.returncode == 3, failed.stderr
    assert json.loads(failed.stdout)['notification']['status'] == 'failed'
    webhook['status'] = 204
    recovered = run_check(webhook, tmp_path, *flags)
    assert recovered.returncode == 0, recovered.stderr
    assert json.loads(recovered.stdout)['notification']['status'] == 'delivered'
    assert all(path == '/v1/operations/health' and auth == 'Bearer ' + REVIEWER for path, auth in webhook['gets'])
    assert all(item['authorization'] == 'Bearer ' + TOKEN for item in webhook['received'])
    assert REVIEWER not in recovered.stdout and TOKEN not in recovered.stdout
    assert all(item['body'].get('decision') is None for item in webhook['received'])


def test_operator_cli_invalid_notification_config_sanitizes_error(webhook, tmp_path):
    cfg = tmp_path / 'invalid.json'
    cfg.write_text('{"endpoint":"https://secret:password@webhook.example"}')
    result = run_check(webhook, tmp_path, '--alert-config', str(cfg), '--alert-state', str(tmp_path / 'outbox.sqlite'))
    assert result.returncode == 3
    assert json.loads(result.stdout)['error_code'] == 'alert_configuration_invalid'
    assert 'password' not in result.stdout + result.stderr
    assert webhook['gets'] == [] and webhook['received'] == []


def test_operator_cli_cannot_overwrite_outbox_with_report(webhook, tmp_path):
    cfg = tmp_path / 'alert.json'
    cfg.write_text(config(webhook).model_dump_json())
    result = run_check(webhook, tmp_path, '--alert-config', str(cfg), '--alert-state', str(tmp_path / 'report.json'))
    assert result.returncode == 2 and 'must be separate files' in result.stderr
    assert webhook['gets'] == [] and webhook['received'] == []
    assert not (tmp_path / 'report.json').exists()
