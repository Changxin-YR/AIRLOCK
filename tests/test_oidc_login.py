"""A real TLS/loopback integration with a simulated local issuer, not live SSO."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import ssl
import socket
import stat
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlencode, urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import httpx
import jwt
import pytest

from airlock import oidc
from airlock import oidc_login
from airlock.oidc_login import (LoginError, base64url, callback_server, load_config,
                                login, private_token_file, validate_tokens)
from airlock.models import GateError


@pytest.fixture
def local_issuer(tmp_path):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update(kid='local-test', alg='RS256', use='sig')
    (tmp_path/'jwks.json').write_text(json.dumps({'keys': [jwk]}))
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, '127.0.0.1')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(private.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
            .not_valid_after(now+timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
            .sign(private, hashes.SHA256()))
    cert_path, key_path = tmp_path/'ca.pem', tmp_path/'tls-key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
    trace = {'authorizations': [], 'exchanges': [], 'browser_errors': []}
    tokens = {}

    def make_tokens(nonce, **changes):
        now = int(time.time())
        access_claims = {'iss': identity['issuer'], 'aud': identity['audience'], 'sub': 'test-subject',
                         'iat': now, 'exp': now+300, 'jti': 'test-token', 'client_id': config['client_id']}
        access_claims.update(changes.pop('access', {}))
        access = jwt.encode(access_claims, private, algorithm='RS256', headers={'kid': 'local-test', 'typ': 'at+jwt'})
        id_claims = {'iss': identity['issuer'], 'aud': config['client_id'], 'sub': 'test-subject',
                     'iat': now, 'exp': now+300, 'nonce': nonce,
                     'at_hash': base64url(hashlib.sha256(access.encode()).digest()[:16])}
        id_claims.update(changes)
        value = {'token_type': 'Bearer', 'access_token': access,
                 'id_token': jwt.encode(id_claims, private, algorithm='RS256', headers={'kid': 'local-test', 'typ': 'JWT'})}
        tokens.update(value)
        return value

    class IssuerHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            assert urlsplit(self.path).path == '/authorize'
            args = {key: value[0] for key, value in parse_qs(urlsplit(self.path).query).items()}
            assert args['response_type'] == 'code' and args['code_challenge_method'] == 'S256'
            assert args['client_id'] == config['client_id'] and args['audience'] == identity['audience']
            assert args['scope'] == 'openid'
            trace['authorizations'].append(args)
            self.send_response(302)
            self.send_header('Location', args['redirect_uri']+'?'+urlencode({'code': 'single-code', 'state': args['state'],
                                                                           'iss': identity['issuer']}))
            self.end_headers()

        def do_POST(self):
            assert self.path == '/token'
            args = {key: value[0] for key, value in parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode()).items()}
            auth = trace['authorizations'][-1]
            assert args['grant_type'] == 'authorization_code' and args['code'] == 'single-code'
            assert args['redirect_uri'] == auth['redirect_uri'] and args['client_id'] == auth['client_id']
            assert base64url(hashlib.sha256(args['code_verifier'].encode()).digest()) == auth['code_challenge']
            assert not trace['exchanges']
            trace['exchanges'].append(args)
            if trace.get('slow_exchange'):
                # Keep making progress more often than httpx's per-read timeout.
                # Only the parent's whole-exchange deadline can stop this peer.
                prefix = (b'HTTP/1.1 200 OK\r\nX-Slow: ' if trace['slow_exchange'] == 'headers'
                          else b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 16000\r\n\r\n{"slow":"')
                try:
                    self.connection.sendall(prefix)
                    trace['slow_started'].set()
                    for _ in range(200):
                        self.connection.sendall(b'x')
                        time.sleep(.1)
                except OSError:
                    trace['slow_closed'].set()
                return
            value = make_tokens(auth['nonce'])
            body = json.dumps(value).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), IssuerHandler)
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert_path, key_path)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'https://127.0.0.1:{server.server_port}'
    identity = {'issuer': origin+'/tenant', 'audience': 'airlock-api', 'jwks_file': 'jwks.json',
                'subjects': {'test-subject': 'reviewer:simulated'}}
    identity_path = tmp_path/'identity.json'
    identity_path.write_text(json.dumps(identity))
    config = {'identity_file': 'identity.json', 'client_id': 'local-public-client',
              'authorization_endpoint': origin+'/authorize', 'token_endpoint': origin+'/token',
              'address_pins': ['127.0.0.1'], 'ca_file': str(cert_path), 'allow_loopback_issuer': True,
              'callback_port': 0, 'timeout_seconds': 5}
    config_path = tmp_path/'login.json'
    config_path.write_text(json.dumps(config))
    browser_threads = []

    def browser(url):
        def browse():
            try:
                with httpx.Client(verify=ssl.create_default_context(cafile=str(cert_path)), trust_env=False,
                                  follow_redirects=True, timeout=5) as client:
                    response = client.get(url)
                    assert response.status_code == 200
                    assert response.headers['cache-control'] == 'no-store'
                    assert tokens.get('access_token', 'never-sent') not in response.text
            except Exception as error:
                trace['browser_errors'].append(type(error).__name__)
        worker = threading.Thread(target=browse, daemon=True)
        browser_threads.append(worker)
        worker.start()
        return True

    yield config_path, config, identity_path, identity, make_tokens, browser, trace, tokens
    for worker in browser_threads:
        worker.join(timeout=6)
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_oidc_pkce_real_tls_loopback_and_private_export(local_issuer, tmp_path):
    path, _, _, _, _, browser, trace, tokens = local_issuer
    target = login(path, tmp_path/'sessions', open_browser=browser)
    value = json.loads(target.read_text())
    assert value['access_token'] == tokens['access_token'] and value['identity'] == 'reviewer:simulated'
    assert 'id_token' not in value and 'refresh_token' not in value
    assert len(trace['authorizations']) == len(trace['exchanges']) == 1
    assert not trace['browser_errors']
    if os.name != 'nt':
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700


@pytest.mark.parametrize('audience,allow,accepted', [
    ('airlock-api', [], True), (['airlock-api'], [], False),
    (['airlock-api', 'https://issuer.example/userinfo'], [], False),
    (['airlock-api', 'https://issuer.example/userinfo'], ['https://issuer.example/userinfo'], True),
    (['airlock-api', 'untrusted'], ['https://issuer.example/userinfo'], False),
    (['airlock-api', 'airlock-api'], ['https://issuer.example/userinfo'], False),
    (['https://issuer.example/userinfo'], ['https://issuer.example/userinfo'], False),
    ('https://issuer.example/userinfo', ['https://issuer.example/userinfo'], False),
    (['airlock-api', 5], ['https://issuer.example/userinfo'], False),
])
def test_oidc_audiences_require_explicit_exact_allowlist(local_issuer, audience, allow, accepted):
    _, _, identity_path, identity, make_tokens, _, _, _ = local_issuer
    identity['additional_audiences'] = allow
    identity_path.write_text(json.dumps(identity))
    token = make_tokens('nonce', access={'aud': audience})['access_token']
    if accepted:
        assert oidc.identify(token, identity_path) == 'reviewer:simulated'
    else:
        with pytest.raises(GateError):
            oidc.identify(token, identity_path)


@pytest.mark.parametrize('changes', [
    {'nonce': 'wrong'}, {'sub': 'other'}, {'aud': 'wrong'}, {'azp': 'wrong'}, {'at_hash': 'wrong'},
    {'access': {'client_id': 'wrong'}}, {'access': {'sub': 'unmapped'}},
    {'access': {'aud': 'other-api'}}, {'exp': int(time.time())-1},
])
def test_oidc_login_rejects_unbound_tokens(local_issuer, changes):
    path, _, _, _, make_tokens, _, _, _ = local_issuer
    config, identity = load_config(path)
    nonce = changes.pop('nonce', 'expected')
    value = make_tokens(nonce, **changes)
    with pytest.raises((LoginError, GateError, jwt.PyJWTError)):
        validate_tokens(value, config, identity, 'expected')


@pytest.mark.parametrize('changes', [
    {'token_endpoint': 'http://127.0.0.1/token'},
    {'token_endpoint': 'https://evil.invalid/token'},
    {'authorization_endpoint': 'https://evil.invalid/authorize'},
    {'scopes': ['openid', 'offline_access']}, {'allow_loopback_issuer': False},
])
def test_oidc_login_rejects_untrusted_configuration(local_issuer, changes):
    path, config, _, _, _, _, _, _ = local_issuer
    path.write_text(json.dumps(config | changes))
    with pytest.raises(ValueError if 'allow_loopback_issuer' in changes else LoginError):
        load_config(path)


def test_oidc_callback_rejects_wrong_state_duplicates_host_then_accepts_once():
    server, result = callback_server(0, 'expected-state', 'https://issuer.example')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/oidc/callback'
    try:
        with httpx.Client(trust_env=False) as client:
            for suffix in ('?state=wrong&code=secret', '?state=expected-state&state=expected-state&code=secret',
                           '?state=expected-state&code=secret&iss=https%3A%2F%2Fevil.invalid'):
                response = client.get(url+suffix)
                assert response.status_code == 400 and 'secret' not in response.text and not result
            assert client.get(url+'?state=expected-state&code=secret', headers={'Host': 'evil.invalid'}).status_code == 400
            assert not result
            assert client.get(url+'?state=expected-state&code=secret').status_code == 200
            assert result == {'code': 'secret'}
            assert client.get(url+'?state=expected-state&code=replay').status_code == 400
            assert result == {'code': 'secret'}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_oidc_login_browser_failure_never_exports_token(local_issuer, tmp_path):
    path, _, _, _, _, _, trace, _ = local_issuer
    with pytest.raises(LoginError):
        login(path, tmp_path/'sessions', open_browser=lambda _: False)
    assert not (tmp_path/'sessions').exists() and not trace['exchanges']


@pytest.mark.parametrize('stage', ['headers', 'body'])
def test_oidc_token_exchange_total_deadline_kills_slow_peer(local_issuer, tmp_path, monkeypatch, stage):
    path, _, _, _, _, browser, trace, _ = local_issuer
    trace.update(slow_exchange=stage, slow_started=threading.Event(), slow_closed=threading.Event())
    monkeypatch.setattr(oidc_login, 'TOKEN_EXCHANGE_TIMEOUT_SECONDS', 3)
    started = time.monotonic()
    with pytest.raises(LoginError, match='deadline exceeded'):
        login(path, tmp_path/'sessions', open_browser=browser)
    elapsed = time.monotonic() - started
    assert trace['slow_started'].is_set() and elapsed < 6
    assert trace['slow_closed'].wait(2), 'exchange child must close its live TLS connection on termination'
    assert not (tmp_path/'sessions').exists()


@pytest.mark.parametrize('changes', [
    {'nonce': '\u5371\u9669'}, {'nonce': 3}, {'azp': ['local-public-client']},
    {'aud': ['local-public-client']}, {'sub': 'different-user'}, {'iat': True},
    {'at_hash': ['invalid']}, {'access': {'client_id': 'another-application'}},
])
def test_oidc_independent_malformed_claims_fail_closed(local_issuer, changes):
    path, _, _, _, make_tokens, _, _, _ = local_issuer
    config, identity = load_config(path)
    overrides = dict(changes)
    nonce = overrides.pop('nonce', 'expected')
    payload = make_tokens(nonce, **overrides)
    with pytest.raises((LoginError, GateError, jwt.PyJWTError, TypeError)):
        validate_tokens(payload, config, identity, 'expected')


def test_private_token_export_never_overwrites_previous_session(tmp_path):
    first = private_token_file(tmp_path/'sessions', {'access_token': 'first-synthetic'})
    second = private_token_file(tmp_path/'sessions', {'access_token': 'second-synthetic'})
    assert first != second and json.loads(first.read_text())['access_token'] == 'first-synthetic'


def test_oidc_callback_total_read_deadline_preserves_next_login():
    server, result = callback_server(0, 'expected-state', 'https://issuer.example')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    started = time.monotonic()
    try:
        with socket.create_connection(('127.0.0.1', server.server_port), timeout=2) as client:
            client.sendall(b'GET /oidc/callback HTTP/1.1\r\nX-Slow: ')
            for _ in range(12):
                try:
                    client.sendall(b'x')
                    time.sleep(0.15)
                except OSError:
                    break
            assert time.monotonic()-started < 2.5
            assert not result
        with httpx.Client(trust_env=False) as client:
            response = client.get(f'http://127.0.0.1:{server.server_port}/oidc/callback?state=expected-state&code=accepted')
            assert response.status_code == 200 and result == {'code': 'accepted'}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_oidc_cli_only_emits_path_or_fixed_failure(monkeypatch, tmp_path, capsys):
    target = tmp_path/'private-session'/'access-token.json'
    monkeypatch.setattr('sys.argv', ['oidc-login', '--config', 'configuration.json'])
    monkeypatch.setattr(oidc_login, 'login', lambda *_: target)
    assert oidc_login.main() == 0
    captured = capsys.readouterr()
    assert captured.out == str(target)+'\n' and captured.err == ''

    def fail(*_):
        raise ValueError('sensitive-idp-response-or-token')
    monkeypatch.setattr(oidc_login, 'login', fail)
    assert oidc_login.main() == 1
    captured = capsys.readouterr()
    assert captured.out == '' and 'sensitive' not in captured.err
    assert captured.err == 'OIDC login failed; no credential was exported.\n'
