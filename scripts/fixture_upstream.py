"""Independent loopback-only synthetic CAS counter service for adapter contracts."""
import argparse
import json
import os
import sqlite3
import hmac
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,required=True); parser.add_argument('--database',required=True)
    args=parser.parse_args()
    with sqlite3.connect(args.database) as conn:
        conn.executescript('CREATE TABLE counter(value INTEGER, version INTEGER); INSERT INTO counter VALUES(0,0); CREATE TABLE receipts(id TEXT PRIMARY KEY, body TEXT);')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def respond(self,code,body):
            data=json.dumps(body).encode(); self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
        def auth(self):
            if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+os.environ['AIRLOCK_UPSTREAM_TEST_TOKEN']):
                self.respond(403,{'error':'forbidden'}); return False
            return True
        def do_GET(self):
            if not self.auth(): return
            with sqlite3.connect(args.database) as conn:
                if self.path=='/state':
                    value,version=conn.execute('SELECT * FROM counter').fetchone(); self.respond(200,{'value':value,'version':version}); return
                if self.path.startswith('/receipts/'):
                    row=conn.execute('SELECT body FROM receipts WHERE id=?',(self.path.rsplit('/',1)[-1],)).fetchone()
                    self.respond(200,json.loads(row[0]) if row else {'state':'unknown'}); return
            self.respond(404,{})
        def do_POST(self):
            if not self.auth(): return
            length=int(self.headers.get('Content-Length','0'))
            if length>8192: self.respond(413,{}); return
            body=json.loads(self.rfile.read(length))
            delta=body['arguments']['delta']
            if type(delta)!=int or abs(delta)>100: self.respond(422,{}); return
            with sqlite3.connect(args.database) as conn:
                conn.execute('BEGIN IMMEDIATE')
                value,version=conn.execute('SELECT * FROM counter').fetchone()
                if self.path=='/preview':
                    self.respond(200,{'target_version':str(version),'impact_units':1,'summary':'Synthetic counter change',
                        'before':{'value':value},'after':{'value':value+delta}}); return
                if self.path!='/execute': self.respond(404,{}); return
                previous=conn.execute('SELECT body FROM receipts WHERE id=?',(body['action_id'],)).fetchone()
                if previous:
                    receipt=json.loads(previous[0])
                    if receipt['request_hash']!=body['request_hash']: self.respond(409,{}); return
                else:
                    state='stale' if str(version)!=body['expected_version'] else 'executed'
                    if state=='executed': conn.execute('UPDATE counter SET value=?,version=version+1',(value+delta,))
                    receipt={'action_id':body['action_id'],'request_hash':body['request_hash'],'state':state,
                             'result':{'value':value+delta if state=='executed' else value}}
                    conn.execute('INSERT INTO receipts VALUES(?,?)',(body['action_id'],json.dumps(receipt))); conn.commit()
                    if os.getenv('AIRLOCK_TEST_DROP_RESPONSE')=='1':
                        self.close_connection=True; return
                self.respond(200,receipt)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()


if __name__=='__main__': main()
