"""Independent synthetic counterexamples. No business stores or real credentials."""
import asyncio
from http.server import ThreadingHTTPServer
from threading import Thread
import time
import uuid

import httpx
from fastapi.testclient import TestClient

from airlock.alert_inbox import create_app
from scripts.pilot_server import Handler


WRITE = 'independent-synthetic-writer-' + 'w' * 32
READ = 'independent-synthetic-reader-' + 'r' * 32
BASE = 'http://127.0.0.1:8767'


def payload():
    return {'version': 1, 'event_id': str(uuid.uuid4()), 'kind': 'alert',
            'status': 'alert', 'alert_codes': ['audit_integrity_failed'], 'resolved_codes': []}


def test_cross_identity_and_replay_never_grant_approval_or_second_insert(tmp_path):
    app = create_app(tmp_path / 'review.sqlite3', write_token=WRITE, read_token=READ)
    event = payload()
    with TestClient(app, base_url=BASE) as client:
        headers = {'Authorization': 'Bearer ' + WRITE, 'Idempotency-Key': event['event_id']}
        assert client.post('/airlock/events', json=event, headers={**headers, 'Authorization': 'Bearer ' + READ}).status_code == 401
        assert client.get('/api/events', headers={'Authorization': 'Bearer ' + WRITE}).status_code == 401
        assert client.post('/airlock/events', json=event, headers={**headers, 'Origin': 'https://malicious.invalid'}).status_code == 403
        assert client.post('/airlock/events', json=event, headers=headers).status_code == 201
        assert client.post('/airlock/events', json=event, headers=headers).status_code == 200
        changed = dict(event, alert_codes=['pending_expiry_backlog'])
        assert client.post('/airlock/events', json=changed, headers=headers).status_code == 409
        for path in ['/approve', '/api/actions/approve', '/reconcile', '/retry', '/execute']:
            assert client.post(path, json=event, headers=headers).status_code == 404
        rows = client.get('/api/events', headers={'Authorization': 'Bearer ' + READ}).json()['events']
        assert len(rows) == 1 and rows[0]['alert_codes'] == ['audit_integrity_failed']


def test_authorized_chunked_slow_body_times_out_without_event(tmp_path):
    app = create_app(tmp_path / 'review.sqlite3', write_token=WRITE, read_token=READ)
    async def scenario():
        async def body():
            yield b'{'
            await asyncio.sleep(10)
            yield b'}'
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
            start = time.monotonic()
            response = await client.post('/airlock/events', content=body(), headers={
                'Authorization': 'Bearer ' + WRITE, 'Idempotency-Key': str(uuid.uuid4()),
                'Content-Type': 'application/json'})
            elapsed = time.monotonic() - start
            assert response.status_code == 408 and 4.5 <= elapsed < 8
            assert (await client.get('/api/events', headers={'Authorization': 'Bearer ' + READ})).json()['events'] == []
    asyncio.run(scenario())


def test_pilot_static_server_cannot_read_private_paths_or_submit_actions():
    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{server.server_port}', trust_env=False) as client:
                for path in ['/var/real-work/', '/.env', '/%2e%2e/.env', '/assets/%2e%2e/%2e%2e/.env', '/?file=var/private.json']:
                    assert client.get(path).status_code == 404
                assert client.get('/', headers={'Host': 'malicious.invalid'}).status_code == 403
                assert client.post('/api/actions', json={'decision': 'approve'}).status_code == 501
                page = client.get('/')
                assert "connect-src 'none'" in page.headers['content-security-policy']
                assert '单人先导练习' in page.text
        finally:
            server.shutdown()
            thread.join(timeout=5)
            assert not thread.is_alive()
