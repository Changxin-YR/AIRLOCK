"""Stateless Streamable HTTP JSON responses, sharing the existing MCP dispatcher.

No capability is advertised for Tasks or server-initiated SSE. GET and DELETE
return 405 as permitted for a stateless server. An action receipt is durable;
HTTP/MCP sessions have no execution or approval authority.
"""
import httpx
from .mcp import Bridge,VERSIONS
from .models import Invocation,GateError
from .service import agent_view


class LocalAgentAPI:
    def __init__(self,gate,principal):self.gate,self.principal=gate,principal

    def request(self,method,path,json=None,headers=None):
        try:
            if method=='GET' and path=='/v1/tools':payload={'items':self.gate.registry.discover(self.principal)}
            elif method=='POST' and path=='/v1/actions':payload=agent_view(self.gate.submit(Invocation.model_validate(json),self.principal))
            elif method=='GET' and path.startswith('/v1/actions/'):
                payload=agent_view(self.gate.get(path.removeprefix('/v1/actions/'),self.principal))
            else:raise GateError('not_found',404)
            return httpx.Response(200,json=payload,request=httpx.Request(method,'http://in-process'+path))
        except GateError as error:
            return httpx.Response(error.status,json={'error':error.code,'execution_occurred':False if error.status in (401,403,422) else None},request=httpx.Request(method,'http://in-process'+path))

    def get(self,path,**kwargs):return self.request('GET',path,**kwargs)
    def post(self,path,**kwargs):return self.request('POST',path,**kwargs)


def dispatch(gate,principal,request):
    bridge=Bridge(LocalAgentAPI(gate,principal),'not-a-credential')
    # Stateless transports authenticate each request; no client-controlled session
    # can substitute for the server identity or the persisted action state.
    bridge.initialized=bridge.ready=True
    return bridge.handle(request)
