import datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import socket
import ssl
import threading
import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from airlock.network import client,validate_origin,PinnedTransport


def test_dns_pin_tls_sni_and_no_rebinding(tmp_path,monkeypatch):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'upstream.example')]);now=datetime.datetime.now(datetime.timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1))
        .not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName('upstream.example')]),False)
        .add_extension(x509.BasicConstraints(ca=True,path_length=None),True).sign(key,hashes.SHA256()))
    ca=tmp_path/'ca.pem';private=tmp_path/'key.pem';ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    seen=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            seen.append(self.headers['Host']);body=b'{"ok":true}'
            self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(ca,private)
    server.socket=context.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    original=socket.getaddrinfo;answers=['127.0.0.1'];lookups=[]
    def resolve(host,port,*args,**kwargs):
        lookups.append(host)
        if host=='upstream.example':return [(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,port)) for ip in answers]
        return original(host,port,*args,**kwargs)
    monkeypatch.setattr(socket,'getaddrinfo',resolve)
    url=f'https://upstream.example:{server.server_port}'
    try:
        with client(url,pins=['127.0.0.1'],allow_loopback=True,ca_file=str(ca)) as http:
            assert http.get(url).json()=={'ok':True}
            assert seen==[f'upstream.example:{server.server_port}']
            assert lookups.count('upstream.example')==1  # connection resolves only the literal IP
            answers[:]=['127.0.0.1','169.254.169.254']
            with pytest.raises(ValueError,match='DNS changed'):http.get(url)
            assert len(seen)==1
        with client(url,pins=['127.0.0.1'],allow_loopback=True) as http:
            answers[:]=['127.0.0.1']
            with pytest.raises(httpx.ConnectError):http.get(url)  # untrusted certificate stays rejected
    finally:server.shutdown();server.server_close();thread.join(2)


@pytest.mark.parametrize('url,pins,private',[
    ('https://unconfigured.example',[],False),('http://public.example',['8.8.8.8'],False),('http://public.example',['8.8.8.8'],True),
    ('https://metadata.example',['169.254.169.254'],True),('https://multicast.example',['224.0.0.1'],True),
    ('https://private.example',['10.0.0.1'],False),('https://10.0.0.1',[],True),
    ('https://user:pass@upstream.example',['8.8.8.8'],False)])
def test_unsafe_or_unpinned_origins_rejected(url,pins,private):
    with pytest.raises(ValueError):validate_origin(url,pins,False,private)


def test_default_https_port_and_pinned_isolated_network(monkeypatch):
    seen=[]
    def transport(self,request):
        seen.append((str(request.url),request.headers['Host'],request.extensions['sni_hostname']))
        return httpx.Response(200,stream=httpx.ByteStream(b'{}'))
    monkeypatch.setattr(httpx.HTTPTransport,'handle_request',transport)
    with client('https://8.8.8.8') as http:assert http.get('https://8.8.8.8').status_code==200
    assert seen==[('https://8.8.8.8','8.8.8.8','8.8.8.8')]
    validate_origin('http://10.0.0.2',['10.0.0.2'],False,True)
