"""Second-author probes; all wire, DNS and target effects are synthetic/local."""
from concurrent.futures import ThreadPoolExecutor
import ast
import codecs
import json
import os
from pathlib import Path
import socket
from threading import Event
import time

import httpcore
import httpx
import pytest

from airlock import network
from airlock.mcp_upstream import response_messages
from airlock.models import Decision, Invocation, Settings
from airlock.service import Gate
from airlock.upstream import Tool


@pytest.fixture(autouse=True)
def original_sse_parser_only(monkeypatch):
    if os.getenv('AIRLOCK_SSE_COUNTERCHECK_BASELINE') != '1':
        return
    source = (Path(__file__).parent / 'baseline-mcp-upstream.py').read_text(encoding='utf-8')
    method = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == 'response_messages')
    namespace = {'json': json, 'codecs': codecs, 'time': time}
    exec(compile(ast.get_source_segment(source, method), 'baseline-mcp-upstream.py:response_messages', 'exec'), namespace)
    monkeypatch.setitem(globals(), 'response_messages', namespace['response_messages'])


def test_deadline_nesting_exception_and_thread_context(monkeypatch):
    monkeypatch.setattr(network.time, 'monotonic', lambda: 100.0)
    assert network._deadline.get() is None
    with network.request_deadline(110.0):
        assert network._timeout(20) == 10.0
        with network.request_deadline(200.0):
            assert network._timeout(None) == 10.0
        with pytest.raises(RuntimeError):
            with network.request_deadline(102.0):
                assert network._timeout(20) == 2.0
                raise RuntimeError('synthetic nested failure')
        assert network._timeout(20) == 10.0
        with ThreadPoolExecutor(max_workers=1) as pool:
            def separate_context():
                assert network._deadline.get() is None
                with network.request_deadline(130.0):
                    assert network._timeout(50) == 30.0
                return network._deadline.get()
            assert pool.submit(separate_context).result(timeout=5) is None
        with network.request_deadline(99.0), pytest.raises(httpcore.WriteTimeout):
            network._timeout(5, httpcore.WriteTimeout)
    assert network._deadline.get() is None and network._timeout(20) == 20


class Fragmented(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
    def __iter__(self):
        yield from self.chunks


def test_sse_mixed_newlines_bom_unicode_all_two_chunk_splits():
    wire = ('\ufeff: hello\r\ndata: {"jsonrpc":"2.0",\rdata: "id":1,"result":{"text":"中文"}}\r\n\r'
        'data: {"jsonrpc":"2.0","id":2,"result":{}}\n\n').encode('utf-8')
    expected = [{'jsonrpc': '2.0', 'id': 1, 'result': {'text': '中文'}},
        {'jsonrpc': '2.0', 'id': 2, 'result': {}}]
    # All split positions, including UTF-8 BOM/codepoint and CRLF boundaries.
    for split in range(1, len(wire)):
        response = httpx.Response(200, headers={'content-type': 'text/event-stream'},
            stream=Fragmented([wire[:split], wire[split:]]))
        assert list(response_messages(response, time.monotonic() + 5)) == expected, split
    one_byte = httpx.Response(200, headers={'content-type': 'text/event-stream'},
        stream=Fragmented([bytes([byte]) for byte in wire]))
    assert list(response_messages(one_byte, time.monotonic() + 5)) == expected


@pytest.mark.parametrize('length,accepted', [(5457, True), (5458, False)])
def test_response_budget_is_utf8_bytes_not_character_count(length, accepted):
    body = ('{"text":"' + '中' * length + '"}').encode('utf-8')
    response = httpx.Response(200, stream=Fragmented([body[:100], body[100:]]))
    if accepted:
        result = network.strict_json(b''.join(network.response_bytes(response, time.monotonic() + 5)))
        assert result == {'text': '中' * length}
    else:
        with pytest.raises(ValueError, match='response budget'):
            list(network.response_bytes(response, time.monotonic() + 5))


@pytest.mark.parametrize('encoding', ['gzip', 'br', 'Identity,gzip'])
def test_encoded_response_is_rejected_before_any_body_read(encoding):
    class MustNotRead(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError('untrusted encoded stream was consumed')
            yield b''
    response = httpx.Response(200, headers={'content-encoding': encoding}, stream=MustNotRead())
    with pytest.raises(ValueError, match='encoded response rejected'):
        list(network.response_bytes(response, time.monotonic() + 5))


def test_expired_dns_worker_cannot_connect_after_lookup_finishes(monkeypatch):
    started, release, completed = Event(), Event(), Event()
    sent = []

    def resolve(host, port, **kwargs):
        assert host == 'synthetic-transport.example'
        started.set()
        try:
            assert release.wait(5)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', port))]
        finally:
            completed.set()

    def send(self, request):
        sent.append(str(request.url))
        return httpx.Response(200, stream=httpx.ByteStream(b'{}'))

    monkeypatch.setattr(network.socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', send)
    origin = 'http://synthetic-transport.example'
    with network.client(origin, pins=['127.0.0.1'], allow_loopback=True) as client:
        try:
            with network.request_deadline(time.monotonic() + .03), pytest.raises(httpx.ConnectTimeout):
                client.get(origin)
            assert started.is_set() and sent == []
        finally:
            release.set()
        assert completed.wait(5)
        assert network._deadline.get() is None and sent == []
        # A new request can succeed; the expired one is never resumed or replayed.
        with network.request_deadline(time.monotonic() + 2):
            assert client.get(origin).status_code == 200
        assert len(sent) == 1


def test_bad_execution_receipt_keeps_unknown_reservation_until_readonly_reconcile(tmp_path, monkeypatch):
    target = {'effects': 0, 'good_receipt': False}
    calls = []

    def respond(request):
        calls.append((request.method, request.url.path))
        assert request.headers['Accept-Encoding'] == 'identity'
        if request.url.path == '/preview':
            return httpx.Response(200, json={'target_version': '1', 'impact_units': 1,
                'summary': 'Synthetic counter change', 'before': {'count': 0}, 'after': {'count': 1}})
        if request.url.path == '/execute':
            payload = json.loads(request.content)
            target['effects'] += 1
            target['receipt'] = {'action_id': payload['action_id'], 'request_hash': payload['request_hash'],
                'state': 'executed', 'result': {'count': 1}}
        if target['good_receipt']:
            return httpx.Response(200, json=target['receipt'])
        return httpx.Response(200, content=b'{"state":"failed","state":"executed"}')

    monkeypatch.setattr(Tool, 'client', lambda self: httpx.Client(transport=httpx.MockTransport(respond)))
    tool = Tool(name='upstream:countercheck', resource='synthetic:countercheck',
        url='http://127.0.0.1:1', allow_loopback=True, arguments={})
    path = tmp_path / 'upstream.json'
    path.write_text(json.dumps({'tools': [tool.model_dump()]}), encoding='utf-8')
    gate = Gate(Settings(tmp_path / 'state.db', 'a' * 32, 'b' * 32, 'c' * 32,
        upstream_file=path, seed_rows=3, budget_units=1))
    invocation = Invocation(tool=tool.name, idempotency_key='countercheck-effect')
    action = gate.submit(invocation)
    result = gate.decide(action['id'], Decision(decision='approve', review_digest=action['review_digest'],
        expected_version=action['version'], reason='Synthetic independent exact review'))
    assert result['state'] == 'unknown' and target['effects'] == 1
    assert gate.submit(invocation)['state'] == 'unknown'
    assert gate.remote.reconcile(result)['state'] == 'unknown'
    with gate.store.connection() as conn:
        assert conn.execute('SELECT state FROM risk_budget WHERE action_id=?', (action['id'],)).fetchone()[0] == 'reserved'
        assert conn.execute('SELECT count(*) FROM customers').fetchone()[0] == 3
    target['good_receipt'] = True
    assert gate.remote.reconcile(result)['state'] == 'executed'
    with gate.store.connection() as conn:
        assert conn.execute('SELECT state FROM risk_budget WHERE action_id=?', (action['id'],)).fetchone()[0] == 'settled'
    assert sum(path == '/execute' for _, path in calls) == target['effects'] == 1
    assert gate.store.verify_audit()['valid'] and network._deadline.get() is None
