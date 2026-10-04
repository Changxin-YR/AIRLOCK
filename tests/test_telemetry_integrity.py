"""Real loopback OTLP responses and concurrent acknowledgement accounting."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time

import pytest

from airlock import telemetry
from airlock.service import Gate
from conftest import call, count


@contextmanager
def collector(body=b'{}', barrier=None, slow_headers=False, encodings=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            if barrier is not None:
                barrier.wait(timeout=3)
            try:
                if slow_headers:
                    self.connection.sendall(b'HTTP/1.1 200 OK\r\n')
                    for _ in range(20):
                        self.connection.sendall(b'X-Progress: yes\r\n')
                        time.sleep(.05)
                    self.connection.sendall(b'Content-Length: 2\r\n\r\n{}')
                else:
                    wire=body
                    if encodings is not None:
                        encodings.append(self.headers.get('Accept-Encoding',''))
                        if 'gzip' in encodings[-1]:wire=gzip.compress(body)
                    self.send_response(200)
                    if wire!=body:self.send_header('Content-Encoding','gzip')
                    self.send_header('Content-Length', str(len(wire)))
                    self.end_headers()
                    self.wfile.write(wire)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1/traces'
    finally:
        server.shutdown()
        server.server_close()
        worker.join(3)


@pytest.mark.parametrize('body', [
    b'{"partialSuccess":{"rejectedSpans":1},"partialSuccess":{}}',
    b'{"unexpected":NaN}', b'{"unexpected":"\\ud800"}',
])
def test_ambiguous_otlp_acknowledgement_retains_unsent_span(settings, body):
    with collector(body) as url:
        gate = Gate(replace(settings, otlp_url=url, otlp_allow_loopback=True))
        action = gate.submit(call())
        assert telemetry.export(gate.store)['status'] == 'retryable_error'
        metrics = telemetry.metrics(gate.store)
        assert metrics['pending_spans'] == 1 and metrics['exported_spans'] == 0
        assert gate.get(action['id'])['state'] == 'pending'
        assert count(gate) == 1206 and gate.store.verify_audit()['valid']


def test_concurrent_otlp_acknowledgements_count_each_persisted_span_once(settings):
    with collector(barrier=threading.Barrier(2)) as url:
        gate = Gate(replace(settings, otlp_url=url, otlp_allow_loopback=True))
        action = gate.submit(call())
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(telemetry.export, gate.store) for _ in range(2)]
            receipts = [future.result(timeout=5) for future in futures]
        assert all(receipt['status'] == 'ok' for receipt in receipts)
        assert sum(receipt['exported'] for receipt in receipts) == 1
        assert telemetry.metrics(gate.store)['exported_spans'] == 1
        assert telemetry.metrics(gate.store)['pending_spans'] == 0
        assert count(gate) == 1206 and gate.get(action['id'])['state'] == 'pending'
        assert gate.store.verify_audit()['valid']


def test_otlp_slow_headers_have_total_deadline_and_keep_pending_span(settings, monkeypatch):
    monkeypatch.setattr(telemetry, 'EXPORT_TIMEOUT_SECONDS', .2, raising=False)
    with collector(slow_headers=True) as url:
        gate = Gate(replace(settings, otlp_url=url, otlp_allow_loopback=True))
        gate.submit(call())
        start = time.monotonic()
        report = telemetry.export(gate.store)
        elapsed = time.monotonic() - start
        assert elapsed < .7
        assert report['status'] == 'retryable_error'
        assert telemetry.metrics(gate.store)['pending_spans'] == 1
        assert count(gate) == 1206 and gate.store.verify_audit()['valid']


def test_otlp_negotiates_identity_with_compression_capable_collector(settings):
    encodings=[]
    with collector(encodings=encodings) as url:
        gate=Gate(replace(settings,otlp_url=url,otlp_allow_loopback=True))
        action=gate.submit(call())
        assert telemetry.export(gate.store)=={'status':'ok','exported':1}
        assert encodings==['identity']
        assert telemetry.metrics(gate.store)['pending_spans']==0
        assert gate.get(action['id'])['state']=='pending' and count(gate)==1206
