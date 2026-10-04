"""Independent malformed-wire and slow-peer regressions; no real services."""
from contextlib import contextmanager
from dataclasses import replace
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import time

import httpx
import pytest

from airlock.models import GateError, Invocation
from airlock.service import Gate
from airlock.upstream import Tool
from airlock.mcp_upstream import response_messages


def make_tool(**extra):
    return Tool(name='upstream:boundary', resource='synthetic:boundary',
                url='http://127.0.0.1:1', allow_loopback=True, arguments={}, **extra)


@pytest.mark.parametrize('wire', [
    b'{"state":"failed","state":"executed"}',
    b'{"outer":{"same":1,"same":2}}',
    b'{"number":NaN}', b'{"number":1e999}',
    b'{"text":"\\ud800"}', b'[' * 1200 + b'0' + b']' * 1200,
])
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
