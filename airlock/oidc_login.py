"""Operator-configured native OIDC Code + PKCE client; no discovery or secrets.

This is a local public client, not an identity provider or an MFA bypass.
Register its exact loopback callback at the provider. Both ID and API access
tokens are checked against the operator's fixed issuer/JWKS configuration.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit
import webbrowser

import jwt
from pydantic import BaseModel, ConfigDict, Field

from . import network, oidc
from .models import GateError


class LoginError(Exception):
    """Only a fixed, non-sensitive message is emitted by the command line."""


# A socket read timeout alone can be prolonged indefinitely by a server slowly
# dripping HTTP headers. The exchange runs in an isolated child that the parent
# terminates after this whole-operation budget (plus process launch/cleanup).
TOKEN_EXCHANGE_TIMEOUT_SECONDS = 15


class LoginConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    identity_file: str = Field(min_length=1, max_length=1024)
    client_id: str = Field(min_length=1, max_length=256)
    authorization_endpoint: str = Field(min_length=1, max_length=2048)
    token_endpoint: str = Field(min_length=1, max_length=2048)
    address_pins: list[str] = Field(default_factory=list, max_length=16)
    scopes: list[str] = Field(default_factory=lambda: ['openid'], max_length=16)
    callback_port: int = Field(default=8765, ge=0, le=65535)
    timeout_seconds: int = Field(default=180, ge=5, le=600)
    ca_file: str | None = None
    allow_loopback_issuer: bool = False


def load_config(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    if len(raw) > 16384:
        raise LoginError('login configuration size')
    config = LoginConfig.model_validate_json(raw)
    config.identity_file = str((path.parent / config.identity_file).resolve())
    if config.ca_file:
        config.ca_file = str((path.parent / config.ca_file).resolve())
    identity, _ = oidc.configuration(config.identity_file)
    origin = urlsplit(identity.issuer)
    for endpoint in (config.authorization_endpoint, config.token_endpoint):
        parsed = urlsplit(endpoint)
        if (parsed.scheme != 'https' or parsed.netloc != origin.netloc
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or not parsed.path.startswith('/') or '\\' in endpoint
                or any(ord(c) <= 32 or ord(c) == 127 for c in endpoint)):
            raise LoginError('endpoints must use the configured HTTPS issuer origin')
    network.validate_origin(f'https://{origin.netloc}', config.address_pins,
                            allow_loopback=config.allow_loopback_issuer)
    if ('openid' not in config.scopes or 'offline_access' in config.scopes
            or len(set(config.scopes)) != len(config.scopes)
            or any(not re.fullmatch(r'[A-Za-z0-9:._/-]{1,128}', s) for s in config.scopes)):
        raise LoginError('invalid login scopes')
    return config, identity


def base64url(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def validate_tokens(payload, config, identity, nonce):
    if (not isinstance(payload, dict) or not isinstance(payload.get('token_type'), str)
            or payload['token_type'].lower() != 'bearer'
            or not isinstance(payload.get('access_token'), str)
            or not isinstance(payload.get('id_token'), str)):
        raise LoginError('token response rejected')
    access_token, id_token = payload['access_token'], payload['id_token']
    if len(access_token) > 8192 or len(id_token) > 16384:
        raise LoginError('oversized token')
    # Reload current access configuration; a revoked subject/key cannot log in.
    access, who = oidc.verified_claims(access_token, config.identity_file)
    if who is None or access['client_id'] != config.client_id:
        raise LoginError('unmapped subject or client mismatch')
    current, keys = oidc.configuration(config.identity_file)
    if current.issuer != identity.issuer or current.audience != identity.audience:
        raise LoginError('identity configuration changed during login')
    header = jwt.get_unverified_header(id_token)
    if (header.get('alg') != 'RS256' or header.get('typ', 'JWT') != 'JWT'
            or any(key in header for key in ('jku', 'x5u', 'jwk', 'crit'))):
        raise LoginError('ID token profile rejected')
    claims = jwt.decode(id_token, keys[header['kid']], algorithms=['RS256'], issuer=current.issuer,
                        audience=config.client_id, options={'require': ['iss', 'aud', 'sub', 'iat', 'exp', 'nonce'],
                                                           'strict_aud': True})
    if (not isinstance(claims['nonce'], str) or not hmac.compare_digest(claims['nonce'], nonce)
            or claims['sub'] != access['sub'] or claims.get('azp', config.client_id) != config.client_id
            or any(type(claims[field]) is not int for field in ('iat', 'exp'))
            or not 0 < claims['exp'] - claims['iat'] <= current.max_token_seconds):
        raise LoginError('ID token binding rejected')
    if 'at_hash' in claims:
        expected = base64url(hashlib.sha256(access_token.encode('ascii')).digest()[:16])
        if not isinstance(claims['at_hash'], str) or not hmac.compare_digest(claims['at_hash'], expected):
            raise LoginError('access token hash mismatch')
    return {'access_token': access_token, 'token_type': 'Bearer', 'expires_at': access['exp'],
            'issuer': current.issuer, 'audience': current.audience, 'identity': who}


class CallbackServer(HTTPServer):
    """One successful state-bound response; invalid traffic never consumes it."""
    allow_reuse_address = False

    def handle_error(self, request, client_address):
        # No callback URL or authentication material goes to server logs.
        pass

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(0.5)
        return connection, address


def callback_server(port, state, issuer):
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            # Bound the whole local request, including an attacker dripping
            # headers more quickly than the per-read socket timeout.
            self.expiration = threading.Timer(1.0, self.expire)
            self.expiration.daemon = True
            self.expiration.start()

        def expire(self):
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        def finish(self):
            try:
                super().finish()
            finally:
                self.expiration.cancel()

        def log_message(self, *args):
            pass

        def do_GET(self):
            try:
                url = urlsplit(self.path)
                if (len(self.path) > 8192 or url.path != '/oidc/callback' or url.scheme or url.netloc
                        or self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}'
                        or url.fragment or result):
                    raise ValueError()
                pairs = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True, max_num_fields=8)
                values = dict(pairs)
                if (len(pairs) != len(values)
                        or not set(values) <= {'state', 'code', 'iss', 'session_state', 'error', 'error_description', 'error_uri'}
                        or not hmac.compare_digest(values.get('state', ''), state)
                        or values.get('iss', issuer) != issuer):
                    raise ValueError()
                if 'error' in values and 'code' not in values:
                    result['error'] = True
                elif (set(values).isdisjoint({'error', 'error_description', 'error_uri'})
                      and isinstance(values.get('code'), str) and 1 <= len(values['code']) <= 4096):
                    result['code'] = values['code']
                else:
                    raise ValueError()
                status, body = 200, b'Login response received. You may close this window.'
            except (ValueError, TypeError):
                status, body = 400, b'Login response rejected.'
            self.send_response(status)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = CallbackServer(('127.0.0.1', port), Handler)
    server.timeout = 0.25
    return server, result


def private_token_file(directory, value):
    """Create an exclusive private directory before any token bytes are written."""
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    private = Path(tempfile.mkdtemp(prefix='session-', dir=directory))
    try:
        if os.name == 'nt':
            account = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], check=True,
                                     capture_output=True, text=True).stdout
            sid = re.search(r'S-1-\d+(?:-\d+)+', account)
            if not sid:
                raise LoginError('cannot identify private token owner')
            subprocess.run(['icacls', str(private), '/inheritance:r', '/grant:r', f'*{sid.group()}:(OI)(CI)F'],
                           check=True, capture_output=True)
        else:
            private.chmod(0o700)
        target = private / 'access-token.json'
        with open(target, 'x', encoding='utf-8', opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
            json.dump(value, stream, ensure_ascii=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        return target
    except Exception:
        # Never emit a token, IDP payload or exception arguments to a terminal.
        target = private / 'access-token.json'
        if target.exists():
            target.unlink()
        private.rmdir()
        raise


def _exchange_in_child(config, code, redirect_uri, verifier):
    """Only the bounded child calls this; token bytes stay inside private pipes."""
    parsed = urlsplit(config.token_endpoint)
    with network.client(f'https://{parsed.netloc}', pins=config.address_pins,
                        allow_loopback=config.allow_loopback_issuer, ca_file=config.ca_file, timeout=10) as client:
        with client.stream('POST', config.token_endpoint,
                           headers={'Accept': 'application/json', 'Accept-Encoding': 'identity'},
                           data={'grant_type': 'authorization_code', 'code': code,
                                 'client_id': config.client_id, 'redirect_uri': redirect_uri,
                                 'code_verifier': verifier}) as response:
            if (response.status_code != 200 or response.headers.get('content-type', '').split(';')[0] != 'application/json'
                    or response.headers.get('content-encoding', 'identity') != 'identity'):
                raise LoginError('token exchange rejected')
            data = bytearray()
            token_deadline = time.monotonic() + 15
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > 32768 or time.monotonic() >= token_deadline:
                    raise LoginError('token exchange limit exceeded')
    return json.loads(data)


def exchange_tokens(config_path, code, redirect_uri, verifier):
    request = {'config_path': str(Path(config_path).resolve()), 'code': code,
               'redirect_uri': redirect_uri, 'verifier': verifier}
    env = {k: v for k, v in os.environ.items() if k.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP'}}
    env['PYTHONUTF8'] = '1'
    try:
        process = subprocess.run([sys.executable, '-m', 'airlock.oidc_login', '--token-exchange-worker'],
                                 input=json.dumps(request).encode('utf-8'), stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, timeout=TOKEN_EXCHANGE_TIMEOUT_SECONDS,
                                 cwd=Path(__file__).resolve().parents[1], env=env)
    except subprocess.TimeoutExpired:
        # subprocess.run kills and waits for this child before raising. It never
        # leaves a daemon network thread handling an authorization code behind.
        raise LoginError('token exchange deadline exceeded') from None
    if process.returncode != 0 or len(process.stdout) > 32768:
        raise LoginError('token exchange rejected')
    return json.loads(process.stdout)


def _exchange_worker():
    """Private one-request protocol; credentials never appear in argv or logs."""
    try:
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            return 1
        request = json.loads(raw)
        if (not isinstance(request, dict) or set(request) != {'config_path', 'code', 'redirect_uri', 'verifier'}
                or any(not isinstance(value, str) for value in request.values())
                or not 1 <= len(request['code']) <= 4096
                or not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', request['verifier'])
                or not re.fullmatch(r'http://127\.0\.0\.1:[0-9]{1,5}/oidc/callback', request['redirect_uri'])):
            return 1
        config, _ = load_config(request['config_path'])
        result = _exchange_in_child(config, request['code'], request['redirect_uri'], request['verifier'])
        data = json.dumps(result, ensure_ascii=True).encode('utf-8')
        if len(data) > 32768:
            return 1
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        return 0
    except Exception:
        return 1


def login(config_path, output_directory, *, open_browser=webbrowser.open):
    config, identity = load_config(config_path)
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    server, result = callback_server(config.callback_port, state, identity.issuer)
    deadline = time.monotonic() + config.timeout_seconds
    try:
        redirect_uri = f'http://127.0.0.1:{server.server_port}/oidc/callback'
        parameters = {'response_type': 'code', 'client_id': config.client_id, 'redirect_uri': redirect_uri,
                      'scope': ' '.join(config.scopes), 'audience': identity.audience, 'state': state,
                      'nonce': nonce, 'code_challenge': base64url(hashlib.sha256(verifier.encode('ascii')).digest()),
                      'code_challenge_method': 'S256'}
        if not open_browser(config.authorization_endpoint + '?' + urlencode(parameters)):
            raise LoginError('browser unavailable')
        while not result and time.monotonic() < deadline:
            server.handle_request()
        if time.monotonic() >= deadline or 'code' not in result:
            raise LoginError('login expired or declined')
    finally:
        server.server_close()
    payload = exchange_tokens(config_path, result['code'], redirect_uri, verifier)
    value = validate_tokens(payload, config, identity, nonce)
    return private_token_file(output_directory, value)


def main():
    parser = argparse.ArgumentParser(description='AIRLOCK native OIDC login (public Code + S256 PKCE client)')
    parser.add_argument('--config', required=True)
    parser.add_argument('--output-dir', default='var/oidc-login')
    args = parser.parse_args()
    try:
        target = login(args.config, args.output_dir)
    except (Exception, KeyboardInterrupt):
        print('OIDC login failed; no credential was exported.', file=sys.stderr)
        return 1
    print(target)
    return 0


if __name__ == '__main__':
    raise SystemExit(_exchange_worker() if sys.argv[1:] == ['--token-exchange-worker'] else main())
