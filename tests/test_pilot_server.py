from http.server import ThreadingHTTPServer
from threading import Thread

import httpx

from scripts.pilot_server import Handler


def test_pilot_server_only_serves_fixed_public_assets():
    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{server.server_port}', trust_env=False) as client:
                page = client.get('/')
                assert page.status_code == 200 and '单人先导练习' in page.text
                assert "connect-src 'none'" in page.headers['content-security-policy']
                assert client.get('/assets/study.js').status_code == 200
                assert client.get('/assets/lib.js').status_code == 200
                tasks = client.get('/tasks-example.json')
                assert tasks.status_code == 200 and tasks.json()['version'] == 1
                assert tasks.headers['content-disposition'].startswith('attachment')
                for path in ['/var/', '/.env', '/assets/../../AGENTS.md', '/api/actions', '/?file=.env']:
                    assert client.get(path).status_code == 404
                assert client.post('/api/actions', json={}).status_code == 501
                assert client.get('/', headers={'Host': 'attacker.invalid'}).status_code == 403
        finally:
            server.shutdown()
            thread.join(timeout=5)
