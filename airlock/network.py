"""Resolve, validate and pin the actual connection while preserving TLS identity.

Operator configuration is the only source of origins, address pins and CA files.
Checking DNS then asking another layer to resolve it again is intentionally
avoided: the HTTP connection uses the validated literal IP, original Host and
original TLS SNI/certificate hostname. Redirects and environment proxies stay off.
"""
import ipaddress
from contextlib import contextmanager
from contextvars import ContextVar
import json
import math
import queue
import re
import socket
import ssl
import threading
import time
from urllib.parse import urlparse
import httpcore
import httpx


_deadline = ContextVar('airlock_network_deadline', default=None)
_dns_slots = threading.BoundedSemaphore(4)


@contextmanager
def request_deadline(deadline):
    """Keep one budget across headers, bodies and a multi-request MCP exchange."""
    parent = _deadline.get()
    token = _deadline.set(min(parent, deadline) if parent is not None else deadline)
    try:yield
    finally:_deadline.reset(token)


def _timeout(timeout, error=httpcore.ReadTimeout):
    deadline = _deadline.get()
    if deadline is None:return timeout
    remaining = deadline-time.monotonic()
    if remaining <= 0:raise error('upstream total time limit')
    return min(timeout, remaining) if timeout is not None else remaining


class _DeadlineStream(httpcore.NetworkStream):
    def __init__(self, stream):self.stream = stream
    def read(self, max_bytes, timeout=None):
        return self.stream.read(max_bytes, timeout=_timeout(timeout))
    def write(self, buffer, timeout=None):
        return self.stream.write(buffer, timeout=_timeout(timeout, httpcore.WriteTimeout))
    def close(self):self.stream.close()
    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        return _DeadlineStream(self.stream.start_tls(ssl_context, server_hostname,
            timeout=_timeout(timeout, httpcore.ConnectTimeout)))
    def get_extra_info(self, info):return self.stream.get_extra_info(info)


class _DeadlineBackend(httpcore.SyncBackend):
    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        return _DeadlineStream(super().connect_tcp(host, port,
            timeout=_timeout(timeout, httpcore.ConnectTimeout),
            local_address=local_address, socket_options=socket_options))


def _resolve(host, port):
    # getaddrinfo has no portable timeout. A bounded number of daemon workers
    # may finish an OS lookup after expiry, but can never connect or send data.
    timeout = _timeout(2, httpx.ConnectTimeout)
    if not _dns_slots.acquire(blocking=False):raise httpx.ConnectError('DNS resolver busy')
    result = queue.Queue(maxsize=1)
    def lookup():
        try:result.put((True, socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
        except Exception:result.put((False, None))
        finally:_dns_slots.release()
    try:
        threading.Thread(target=lookup, name='airlock-dns', daemon=True).start()
    except Exception:
        _dns_slots.release()
        raise httpx.ConnectError('DNS resolver unavailable') from None
    try:ok, records = result.get(timeout=timeout)
    except queue.Empty:raise httpx.ConnectTimeout('DNS time limit') from None
    _timeout(None, httpx.ConnectTimeout)
    if not ok:raise httpx.ConnectError('DNS resolution failed')
    return records


def strict_json(data):
    """Reject ambiguous or non-serializable JSON before it enters action state."""
    if isinstance(data, (bytes, bytearray)):data = data.decode('utf-8')
    if len(data.encode('utf-8')) > 16384:raise ValueError('upstream JSON size')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    def invalid_constant(value):raise ValueError('non-finite JSON number')
    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):raise ValueError('non-finite JSON number')
        return result
    try:
        value = json.loads(data, object_pairs_hook=pairs,
            parse_constant=invalid_constant, parse_float=finite_float)
    except RecursionError:raise ValueError('upstream JSON depth') from None
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 32:raise ValueError('upstream JSON depth')
        if isinstance(item, dict):
            for key, child in item.items():
                key.encode('utf-8')
                pending.append((child, depth+1))
        elif isinstance(item, list):pending.extend((child, depth+1) for child in item)
        elif isinstance(item, str):item.encode('utf-8')
    return value


def response_bytes(response, deadline):
    # Never decompress an untrusted small wire body into an unbounded buffer.
    if response.headers.get('content-encoding', 'identity').lower().strip() != 'identity':
        raise ValueError('upstream encoded response rejected')
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > 16384 or time.monotonic() > deadline:raise ValueError('upstream response budget')
        yield chunk
    if time.monotonic() > deadline:raise ValueError('upstream response budget')


def address_allowed(address, *, allow_loopback=False, allow_private=False):
    ip=ipaddress.ip_address(address)
    if ip.is_multicast or ip.is_unspecified or ip.is_link_local or ip.is_reserved:
        return False
    if ip.is_loopback:return allow_loopback
    return ip.is_global or (allow_private and ip.is_private)


def validate_origin(url, pins=(), allow_loopback=False, allow_private=False):
    parsed=urlparse(url);port=parsed.port
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('origin required')
    if parsed.scheme not in {'https','http'} or (port is not None and not 1<=port<=65535):
        raise ValueError('invalid origin')
    host=parsed.hostname
    try:literal=ipaddress.ip_address(host)
    except ValueError:literal=None
    normalized=[str(ipaddress.ip_address(p)) for p in pins]
    if len(normalized)>16 or len(set(normalized))!=len(normalized):raise ValueError('invalid address pins')
    if literal:
        if not address_allowed(str(literal),allow_loopback=allow_loopback,allow_private=allow_private):raise ValueError('upstream address rejected')
        if allow_private and not literal.is_global and not literal.is_loopback and str(literal) not in normalized:raise ValueError('private literal requires exact pin')
        if normalized and str(literal) not in normalized:raise ValueError('literal pin mismatch')
    else:
        if len(host)>253 or not re.fullmatch(r'[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?',host) or any(not label or len(label)>63 or label.startswith('-') or label.endswith('-') for label in host.split('.')):
            raise ValueError('invalid DNS hostname')
        if not normalized:raise ValueError('DNS origin requires operator address pins')
    if any(not address_allowed(p,allow_loopback=allow_loopback,allow_private=allow_private) for p in normalized):raise ValueError('unsafe address pin')
    # HTTP is limited to explicit test loopback or a pinned isolated deployment.
    private_http=allow_private and normalized and all(ipaddress.ip_address(p).is_private and not ipaddress.ip_address(p).is_loopback for p in normalized)
    if parsed.scheme=='http' and not private_http and not (allow_loopback and (literal and literal.is_loopback or normalized and all(ipaddress.ip_address(p).is_loopback for p in normalized))):
        raise ValueError('HTTPS required')
    return parsed,normalized,literal


class PinnedTransport(httpx.HTTPTransport):
    def __init__(self,origin,*,pins=(),allow_loopback=False,allow_private=False,ca_file=None):
        self.parsed,self.pins,self.literal=validate_origin(origin,pins,allow_loopback,allow_private)
        self.allow_loopback,self.allow_private=allow_loopback,allow_private
        # HTTPTransport owns this pool; use httpcore's public backend extension
        # so every socket read (including incomplete headers) sees the deadline.
        self._pool=httpcore.ConnectionPool(ssl_context=ssl.create_default_context(cafile=ca_file),
            network_backend=_DeadlineBackend(),retries=0,max_connections=10,max_keepalive_connections=10)

    def handle_request(self,request):
        parsed=self.parsed;port=parsed.port or (443 if parsed.scheme=='https' else 80)
        request_port=request.url.port or (443 if request.url.scheme=='https' else 80)
        if request.url.host!=parsed.hostname or request.url.scheme!=parsed.scheme or request_port!=port:
            raise ValueError('connection origin changed')
        if self.literal:addresses=[str(self.literal)]
        else:
            records=_resolve(parsed.hostname,port)
            addresses=sorted({str(ipaddress.ip_address(r[4][0])) for r in records})
            if not addresses or len(addresses)>16 or any(p not in self.pins for p in addresses):raise ValueError('DNS changed outside approved address pins')
        if any(not address_allowed(p,allow_loopback=self.allow_loopback,allow_private=self.allow_private) for p in addresses):raise ValueError('unsafe resolved address')
        headers=request.headers.copy()
        headers['Host']=parsed.netloc
        connected=httpx.Request(request.method,request.url.copy_with(host=addresses[0]),headers=headers,
                                stream=request.stream,extensions=dict(request.extensions,sni_hostname=parsed.hostname))
        return super().handle_request(connected)


def client(origin,*,pins=(),allow_loopback=False,allow_private=False,ca_file=None,timeout=5):
    return httpx.Client(transport=PinnedTransport(origin,pins=pins,allow_loopback=allow_loopback,
        allow_private=allow_private,ca_file=ca_file),timeout=timeout,trust_env=False,follow_redirects=False)
