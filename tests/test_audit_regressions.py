import mimetypes
from airlock.api import create_app
from fastapi.testclient import TestClient


def test_console_javascript_mime_survives_host_registry(settings):
    old=mimetypes.guess_type('app.js')[0]
    try:
        mimetypes.add_type('text/plain','.js')
        with TestClient(create_app(settings),base_url=settings.origin) as client:
            response=client.get('/assets/app.js')
            assert response.status_code==200
            assert response.headers['content-type']=='text/javascript; charset=utf-8'
            assert 'nosniff'==response.headers['x-content-type-options']
    finally:
        mimetypes.add_type(old or 'text/javascript','.js')


def test_stdio_utf8_roundtrip():
    from test_live_transport import exchange,init,rpc
    from scripts.support import server
    with server() as (url,keys,client):
        rows=exchange(url,keys['AIRLOCK_AGENT_TOKEN'],init()+[
            rpc('tools/call',2,name='sql_execute',arguments={
                'sql':"SELECT '审批🔒' AS text",'idempotency_key':'unicode-audit-001'})])
        assert rows[-1]['result']['structuredContent']['result']['rows']==[{'text':'审批🔒'}]
