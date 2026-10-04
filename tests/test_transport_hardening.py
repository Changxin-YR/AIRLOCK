"""Independent malformed-wire and slow-peer regressions; no real services."""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import time

import httpx
import pytest

from conftest import decision
from airlock.models import GateError, Invocation
from airlock.service import Gate
from airlock.upstream import Tool
from airlock.mcp_upstream import response_messages
from airlock import network


def make_tool(**extra):
    return Tool(name='upstream:boundary', resource='synthetic:boundary',
                url='http://127.0.0.1:1', allow_loopback=True, arguments={}, **extra)


@pytest.mark.parametrize('wire', [
    b'{"state":"failed","state":"executed"}',
    b'{"outer":{"same":1,"same":2}}',
    b'{"number":NaN}', b'{"number":1e999}',
    b'{"text":"\\ud800"}', b'[' * 1200 + b'0' + b']' * 1200,
], ids=['duplicate-state','nested-duplicate','nan','overflow','invalid-unicode','depth'])
@pytest.mark.parametrize('transport', ['http', 'mcp_json', 'mcp_streamable'])
def test_untrusted_json_is_strict_bounded_and_redacted(monkeypatch, wire, transport):
    def respond(request):
        if transport == 'http':
            return httpx.Response(200, content=wire)
        message = json.loads(request.content)
        if message['method'] == 'initialize':
            result = {'protocolVersion':'2025-11-25'}
        elif message['method'] == 'notifications/initialized':
            return httpx.Response(202)
        elif message['method'] == 'tools/list':
            result = {'tools':[{'name':'preview'}]}
        else:
            encoded = b'{"jsonrpc":"2.0","id":3,"result":{"structuredContent":' + wire + b'}}'
            return httpx.Response(200, content=encoded, headers={'content-type':'application/json'})
        return httpx.Response(200, json={'jsonrpc':'2.0','id':message['id'],'result':result})
    monkeypatch.setattr(Tool, 'client', lambda self: httpx.Client(transport=httpx.MockTransport(respond)))
    tool = make_tool(transport=transport, mcp_tools={} if transport == 'http' else
                     {'preview':'preview','execute':'execute','receipt':'receipt'})
    with pytest.raises(GateError) as error:
        tool.request('POST', '/preview', {'arguments':{}})
    assert error.value.code == ('upstream_unavailable' if transport == 'http' else 'upstream_mcp_unavailable')


def test_bad_mcp_preview_persists_blocked_action_instead_of_crashing(settings, tmp_path, monkeypatch):
    def respond(request):
        message = json.loads(request.content)
        if message['method'] == 'notifications/initialized':return httpx.Response(202)
        results = {'initialize': {'protocolVersion':'2025-11-25'},
                   'tools/list': {'tools':[{'name':'preview'}]}}
        if message['method'] == 'tools/call':
            body = b'{"jsonrpc":"2.0","id":3,"result":{"structuredContent":{"target_version":"v1","impact_units":1,"summary":"synthetic","before":{"value":NaN},"after":{"value":1}}}}'
            return httpx.Response(200, content=body, headers={'content-type':'application/json'})
        return httpx.Response(200, json={'jsonrpc':'2.0','id':message['id'],'result':results[message['method']]})
    monkeypatch.setattr(Tool, 'client', lambda self: httpx.Client(transport=httpx.MockTransport(respond)))
    tool = make_tool(transport='mcp_json', mcp_tools={'preview':'preview','execute':'execute','receipt':'receipt'})
    config = tmp_path / 'tools.json'
    config.write_text(json.dumps({'tools':[tool.model_dump()]}))
    gate = Gate(replace(settings, upstream_file=config))
    action = gate.submit(Invocation(tool=tool.name, arguments={}, idempotency_key='invalid-wire-preview'))
    assert action['state'] == 'blocked'
    assert gate.get(action['id'])['state'] == 'blocked'
    assert gate.store.verify_audit()['valid']


@pytest.mark.parametrize('newline', ['\r', '\r\n', '\n'])
def test_sse_accepts_each_standard_newline_even_when_fragmented(newline):
    wire = (': keepalive' + newline + newline + 'data: {"jsonrpc":"2.0","id":1,"result":{"text":"中文"}}' + newline + newline).encode()
    class Bytes(httpx.SyncByteStream):
        def __iter__(self):
            for byte in wire:yield bytes([byte])
    response = httpx.Response(200, headers={'content-type':'text/event-stream'}, stream=Bytes())
    assert list(response_messages(response, time.monotonic()+5)) == [{'jsonrpc':'2.0','id':1,'result':{'text':'中文'}}]


@contextmanager
def slow_headers(duration):
    stopped = threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            try:
                self.wfile.write(b'HTTP/1.1 200 OK\r\nX-Slow: '); self.wfile.flush()
                end = time.monotonic()+duration
                while time.monotonic()<end and not stopped.wait(.05):
                    self.wfile.write(b'x'); self.wfile.flush()
                self.wfile.write(b'\r\nContent-Length: 2\r\n\r\n{}'); self.wfile.flush()
            except (OSError, ValueError):pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:yield f'http://127.0.0.1:{server.server_port}'
    finally:
        stopped.set(); server.shutdown(); server.server_close(); thread.join(2)


def test_total_deadline_also_bounds_dripping_headers():
    with slow_headers(11.5) as origin:
        tool = make_tool().model_copy(update={'url':origin})
        started = time.monotonic()
        with pytest.raises(GateError, match='upstream_unavailable'):
            tool.request('POST', '/preview', {})
        elapsed = time.monotonic()-started
        assert elapsed < 11, f'10s total budget only checked after headers: {elapsed:.3f}s'


@pytest.mark.parametrize('change', ['origin', 'resource', 'removed', 'principal'])
def test_reconcile_keeps_original_target_binding(settings, tmp_path, monkeypatch, change):
    calls = []
    target = {'effects':0}
    def request(self, method, path, payload=None):
        calls.append((method, path, self.url))
        if path == '/preview':
            return {'target_version':'v1','impact_units':1,'summary':'synthetic','before':{},'after':{}}
        if path == '/execute':
            target['effects'] += 1
            target['receipt'] = {'action_id':payload['action_id'], 'request_hash':payload['request_hash'],
                                 'state':'executed', 'result':{'effects':1}}
            raise GateError('upstream_unavailable', 503)
        return target['receipt']
    monkeypatch.setattr(Tool, 'request', request)
    tool = make_tool()
    config = tmp_path / 'tools.json'; config.write_text(json.dumps({'tools':[tool.model_dump()]}))
    gate = Gate(replace(settings, upstream_file=config))
    action = gate.submit(Invocation(tool=tool.name, arguments={}, idempotency_key='original-target-key'))
    unknown = gate.decide(action['id'], decision(action))
    assert unknown['state'] == 'unknown' and target['effects'] == 1
    if change == 'removed':gate.registry.tools.clear()
    else:
        edits = {'origin':{'url':'http://127.0.0.1:2'}, 'resource':{'resource':'synthetic:different'},
                 'principal':{'principals':['agent:different']}}
        gate.registry.tools[tool.name] = tool.model_copy(update=edits[change])
    before = len(calls)
    assert gate.remote.reconcile(unknown)['state'] == 'unknown'
    assert len(calls) == before
    assert target['effects'] == 1 and gate.store.verify_audit()['valid']
    gate.registry.tools[tool.name] = tool
    assert gate.remote.reconcile(unknown)['state'] == 'executed'
    assert calls[-1][0] == 'GET' and target['effects'] == 1


def test_deadline_context_is_nested_and_thread_isolated():
    with slow_headers(.3) as origin:
        tool = make_tool().model_copy(update={'url':origin})
        def invoke(limit):
            started = time.monotonic()
            try:
                with network.request_deadline(started+limit):
                    return tool.request('POST', '/preview', {})
            except GateError:return 'expired'
        with ThreadPoolExecutor(max_workers=2) as pool:
            short = pool.submit(invoke, .12)
            long = pool.submit(invoke, 2)
            assert short.result() == 'expired'
            assert long.result() == {}
        # A prior expired context must not contaminate another request.
        assert tool.request('POST', '/preview', {}) == {}


def test_dns_timeout_and_worker_saturation_never_connect(monkeypatch):
    release = threading.Event(); finished = threading.Event(); calls = []
    def resolve(*args, **kwargs):
        calls.append('resolve')
        try:
            release.wait(2)
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 1))]
        finally:finished.set()
    def connect(*args, **kwargs):
        calls.append('connect')
        raise AssertionError('timed-out DNS must not send')
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(network, '_dns_slots', threading.BoundedSemaphore(1))
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', connect)
    try:
        with network.client('http://bounded.example', pins=['127.0.0.1'], allow_loopback=True) as client:
            with network.request_deadline(time.monotonic()+.08), pytest.raises(httpx.ConnectTimeout):
                client.get('http://bounded.example')
            with pytest.raises(httpx.ConnectError, match='resolver busy'):
                client.get('http://bounded.example')
            assert calls == ['resolve']
    finally:
        release.set(); assert finished.wait(2)


@pytest.mark.parametrize('transport', ['http','mcp_json','mcp_streamable'])
@pytest.mark.parametrize('status,encoding', [(302,None),(200,'gzip')])
def test_redirect_and_encoded_response_are_rejected_without_followup(monkeypatch, transport, status, encoding):
    calls = []
    def respond(request):
        calls.append(request)
        headers = {'location':'http://169.254.169.254/metadata'} if status == 302 else {'content-encoding':encoding}
        headers['content-type'] = 'application/json'
        # The compressed body is small; the decoder must not be invoked at all.
        wire = gzip.compress(b'{}') if encoding else b'{}'
        return httpx.Response(status, headers=headers, stream=httpx.ByteStream(wire))
    monkeypatch.setattr(Tool, 'client', lambda self: httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False))
    tool = make_tool(transport=transport, mcp_tools={} if transport == 'http' else
                     {'preview':'preview','execute':'execute','receipt':'receipt'})
    with pytest.raises(GateError):tool.request('POST','/preview',{})
    assert len(calls) == 1
    assert calls[0].headers['accept-encoding'] == 'identity'


@pytest.mark.parametrize('wire', [b'\xef\xbb\xbfdata: {"ok":true}\r\r', b'data: {"ok":true}\n\n'])
def test_sse_unicode_bom_and_plain_response_are_preserved(wire):
    response = httpx.Response(200, content=wire, headers={'content-type':'text/event-stream'})
    assert list(response_messages(response, time.monotonic()+1)) == [{'ok':True}]


@pytest.mark.parametrize('phase', ['initialize','tools/list','tools/call'])
def test_mcp_malformed_envelope_stops_at_the_exact_phase(monkeypatch, phase):
    calls = []
    def respond(request):
        body = json.loads(request.content); calls.append(body['method'])
        if body['method'] == phase:
            return httpx.Response(200, content=b'{"jsonrpc":"2.0","jsonrpc":"2.0","id":1,"result":{}}', headers={'content-type':'application/json'})
        if body['method'] == 'notifications/initialized':return httpx.Response(202)
        results = {'initialize':{'protocolVersion':'2025-11-25'}, 'tools/list':{'tools':[{'name':'execute'}]}}
        return httpx.Response(200,json={'jsonrpc':'2.0','id':body['id'],'result':results[body['method']]})
    monkeypatch.setattr(Tool, 'client', lambda self: httpx.Client(transport=httpx.MockTransport(respond)))
    tool = make_tool(transport='mcp_streamable', mcp_tools={'preview':'preview','execute':'execute','receipt':'receipt'})
    with pytest.raises(GateError, match='upstream_mcp_unavailable'):tool.request('POST','/execute',{})
    assert calls[-1] == phase
