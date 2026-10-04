from dataclasses import replace
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import threading
from airlock.service import Gate
from airlock import telemetry
from conftest import call,decision,count


def test_real_otlp_http_export_failure_retains_spans_and_does_not_grant_approval(settings):
    received=[];failure=[True]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            assert self.path=='/v1/traces'
            received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(503 if failure[0] else 200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{}')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        gate=Gate(replace(settings,otlp_url=f'http://127.0.0.1:{server.server_port}/v1/traces',otlp_allow_loopback=True))
        action=gate.submit(call())
        assert telemetry.export(gate.store)['status']=='retryable_error'
        assert count(gate)==1206 and telemetry.metrics(gate.store)['pending_spans']==1
        failure[0]=False
        assert telemetry.export(gate.store)=={'status':'ok','exported':1}
        span=received[-1]['resourceSpans'][0]['scopeSpans'][0]['spans'][0]
        assert span['traceId']==action['trace_id'] and span==received[0]['resourceSpans'][0]['scopeSpans'][0]['spans'][0]
        raw=json.dumps(received)
        assert 'DELETE FROM' not in raw and settings.agent_token not in raw and settings.audit_key not in raw
        assert gate.decide(action['id'],decision(action))['state']=='executed'
        assert telemetry.export(gate.store)['exported']==1
        assert telemetry.metrics(gate.store)['exported_spans']==2
    finally:server.shutdown();server.server_close();thread.join(5)


def test_export_endpoint_is_operator_only(client,settings):
    assert client.post('/v1/observability/export',headers={'Authorization':'Bearer '+settings.agent_token}).status_code==403
