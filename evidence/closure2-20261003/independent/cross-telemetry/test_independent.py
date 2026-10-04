"""Cross-author OTLP checks. Uses a throwaway local collector and synthetic DB."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time

import pytest
from airlock import telemetry
from airlock.models import Invocation, Settings
from airlock.service import Gate


@contextmanager
def collector(handler):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            try:handler(self,body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield f'http://127.0.0.1:{server.server_port}/v1/traces'
    finally:server.shutdown();server.server_close();thread.join(2)


def make_gate(tmp_path,url):
    return Gate(Settings(tmp_path/'test.db','agent-'+'a'*32,'reviewer-'+'b'*32,'audit-'+'c'*32,
                         otlp_url=url,otlp_allow_loopback=True))


def submit(gate,key='cross-telemetry-1'):
    return gate.submit(Invocation(sql='DELETE FROM customers WHERE id=1',idempotency_key=key))


def send(http,body,status=200,headers=None):
    http.send_response(status)
    for name,value in (headers or {}).items():http.send_header(name,value)
    http.send_header('Content-Length',str(len(body)));http.end_headers();http.wfile.write(body)


def verify(gate,actions):
    assert all(gate.get(a['id'])['state']=='pending' for a in actions)
    with gate.store.connection() as conn:assert conn.execute('SELECT count(*) FROM customers').fetchone()[0]==1206
    assert gate.store.verify_audit()['valid']


def test_normal_collector_negotiates_identity_so_ack_is_not_rejected(tmp_path):
    encodings=[]
    def handle(http,body):
        encoding=http.headers.get('Accept-Encoding','');encodings.append(encoding)
        compressed='gzip' in encoding
        send(http,gzip.compress(b'{}') if compressed else b'{}',headers={'Content-Encoding':'gzip' if compressed else 'identity'})
    with collector(handle) as url:
        gate=make_gate(tmp_path,url);action=submit(gate)
        assert telemetry.export(gate.store)=={'status':'ok','exported':1}
        assert encodings==['identity']
        verify(gate,[action])


@pytest.mark.parametrize('wire', [b'[]',b'null',b'{"partialSuccess":null}',b'{"partialSuccess":{"rejectedSpans":true}}',b'{"nested":{"x":0,"x":1}}'])
def test_wire_counterexamples_keep_original_span(tmp_path,wire):
    with collector(lambda http,body:send(http,wire)) as url:
        gate=make_gate(tmp_path,url);action=submit(gate)
        assert telemetry.export(gate.store)['status']=='retryable_error'
        assert telemetry.metrics(gate.store)['pending_spans']==1
        assert telemetry.metrics(gate.store)['exported_spans']==0
        verify(gate,[action])


def test_redirect_does_not_contact_replacement_collector(tmp_path):
    calls=[]
    def replacement(http,body):calls.append('replacement');send(http,b'{}')
    with collector(replacement) as replacement_url:
        def redirect(http,body):calls.append('origin');send(http,b'',302,{'Location':replacement_url})
        with collector(redirect) as url:
            gate=make_gate(tmp_path,url);action=submit(gate)
            assert telemetry.export(gate.store)['status']=='retryable_error'
            assert calls==['origin']
            assert telemetry.metrics(gate.store)['pending_spans']==1
            verify(gate,[action])


def test_new_event_while_export_waits_is_not_deleted(tmp_path):
    entered=threading.Event(); release=threading.Event(); sent=[]
    def handle(http,body):
        sent.append(body);entered.set();assert release.wait(3);send(http,b'{}')
    with collector(handle) as url:
        gate=make_gate(tmp_path,url);first=submit(gate)
        with ThreadPoolExecutor(max_workers=1) as pool:
            result=pool.submit(telemetry.export,gate.store)
            try:
                assert entered.wait(2)
                second=submit(gate,'cross-telemetry-2')
            finally:release.set()
            assert result.result(timeout=3)=={'status':'ok','exported':1}
        assert telemetry.metrics(gate.store)['pending_spans']==1
        assert telemetry.metrics(gate.store)['exported_spans']==1
        assert len(sent[0]['resourceSpans'][0]['scopeSpans'][0]['spans'])==1
        assert telemetry.export(gate.store)=={'status':'ok','exported':1}
        assert telemetry.metrics(gate.store)['pending_spans']==0
        assert telemetry.metrics(gate.store)['exported_spans']==2
        verify(gate,[first,second])


def test_dripping_body_then_retry_preserves_span_identity(tmp_path,monkeypatch):
    monkeypatch.setattr(telemetry,'EXPORT_TIMEOUT_SECONDS',.15)
    sent=[]
    def handle(http,body):
        sent.append(body)
        if len(sent)>1:return send(http,b'{}')
        http.send_response(200);http.end_headers();http.wfile.write(b'{');http.wfile.flush()
        for _ in range(10):
            time.sleep(.04);http.wfile.write(b' ');http.wfile.flush()
        http.wfile.write(b'}')
    with collector(handle) as url:
        gate=make_gate(tmp_path,url);action=submit(gate)
        start=time.monotonic()
        assert telemetry.export(gate.store)['status']=='retryable_error'
        assert time.monotonic()-start<.5
        assert telemetry.metrics(gate.store)['pending_spans']==1
        assert telemetry.export(gate.store)=={'status':'ok','exported':1}
        assert sent[0]==sent[1]
        verify(gate,[action])
