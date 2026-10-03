"""Resolve, validate and pin the actual connection while preserving TLS identity.

Operator configuration is the only source of origins, address pins and CA files.
Checking DNS then asking another layer to resolve it again is intentionally
avoided: the HTTP connection uses the validated literal IP, original Host and
original TLS SNI/certificate hostname. Redirects and environment proxies stay off.
"""
import ipaddress
import re
import socket
import ssl
from urllib.parse import urlparse
import httpx


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
        super().__init__(verify=ssl.create_default_context(cafile=ca_file),retries=0)

    def handle_request(self,request):
        parsed=self.parsed;port=parsed.port or (443 if parsed.scheme=='https' else 80)
        request_port=request.url.port or (443 if request.url.scheme=='https' else 80)
        if request.url.host!=parsed.hostname or request.url.scheme!=parsed.scheme or request_port!=port:
            raise ValueError('connection origin changed')
        if self.literal:addresses=[str(self.literal)]
        else:
            records=socket.getaddrinfo(parsed.hostname,port,type=socket.SOCK_STREAM)
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
