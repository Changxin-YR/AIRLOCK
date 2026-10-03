"""Bounded Streamable HTTP sessions for explicitly mapped CAS tools."""
import codecs
import re
import time
import httpx
from .models import GateError
from . import network


def response_messages(response,deadline):
    media=response.headers.get('content-type','').split(';')[0].strip()
    if media not in {'application/json','text/event-stream'}:raise ValueError('MCP response content type')
    decoder=codecs.getincrementaldecoder('utf-8-sig' if media=='text/event-stream' else 'utf-8')();buffer=''
    def events(final=False):
        nonlocal buffer
        # A trailing CR can be the first half of CRLF across byte chunks.
        tail='\r' if not final and buffer.endswith('\r') else ''
        content=buffer[:-1] if tail else buffer
        buffer=content.replace('\r\n','\n').replace('\r','\n')+tail
        while '\n\n' in buffer:
            event,buffer=buffer.split('\n\n',1)
            data='\n'.join(line[5:].removeprefix(' ') for line in event.split('\n') if line.startswith('data:'))
            if data:yield network.strict_json(data)
    for chunk in network.response_bytes(response,deadline):
        buffer+=decoder.decode(chunk)
        if media=='text/event-stream':yield from events()
    buffer+=decoder.decode(b'',final=True)
    if media=='application/json':yield network.strict_json(buffer)
    else:
        yield from events(final=True)
        if buffer.strip() and not buffer.lstrip().startswith(':'):raise ValueError('incomplete SSE event')


def invoke(tool,method,path,payload,headers):
    phase='receipt' if method=='GET' and path.startswith('/receipts/') else {'/preview':'preview','/execute':'execute'}.get(path)
    if phase is None:raise GateError('upstream_method_forbidden',422)
    headers=dict(headers,Accept='application/json, text/event-stream')
    headers['Accept-Encoding']='identity';deadline=time.monotonic()+10
    streaming=tool.transport=='mcp_streamable';session=None
    try:
        with network.request_deadline(deadline), tool.client() as client:
            def send(message,notification=False):
                nonlocal session
                remaining=deadline-time.monotonic()
                if remaining<=0:raise ValueError('MCP deadline')
                with client.stream('POST',tool.target()+tool.mcp_path,json=message,headers=headers,timeout=min(5,remaining)) as response:
                    if notification and response.status_code==202:return None
                    if response.status_code!=200:raise ValueError('MCP HTTP error')
                    incoming=response.headers.get('mcp-session-id')
                    if incoming:
                        if not streaming or not re.fullmatch(r'[\x21-\x7e]{1,256}',incoming):raise ValueError('MCP session rejected')
                        if session is not None and session!=incoming:raise ValueError('MCP session substitution')
                        if session is None and message.get('method')!='initialize':raise ValueError('unsolicited session')
                        session=incoming;headers['Mcp-Session-Id']=session
                    if not streaming and response.headers.get('content-type','').split(';')[0]!='application/json':raise ValueError('JSON-only upstream')
                    for data in response_messages(response,deadline):
                        if not isinstance(data,dict) or data.get('jsonrpc')!='2.0':raise ValueError('MCP invalid envelope')
                        if 'id' not in data and str(data.get('method','')).startswith('notifications/'):
                            continue
                        if type(data.get('id')) is not int or data.get('id')!=message.get('id') or 'method' in data or 'error' in data or not isinstance(data.get('result'),dict):raise ValueError('MCP response binding')
                        return data['result']
                    raise ValueError('MCP response missing')
            try:
                initialized=send({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'airlock-controlled-proxy','version':'0.3'}}})
                if initialized.get('protocolVersion') not in {'2025-11-25','2025-06-18'}:raise ValueError('MCP version')
                headers['MCP-Protocol-Version']=initialized['protocolVersion']
                send({'jsonrpc':'2.0','method':'notifications/initialized'},True)
                discovered=send({'jsonrpc':'2.0','id':2,'method':'tools/list'})
                if tool.mcp_tools[phase] not in {t.get('name') for t in discovered.get('tools',[]) if isinstance(t,dict)}:raise ValueError('registered tool absent')
                args={'action_id':path.rsplit('/',1)[1]} if phase=='receipt' else payload
                result=send({'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':tool.mcp_tools[phase],'arguments':args}})
                if result.get('isError') or not isinstance(result.get('structuredContent'),dict):raise ValueError('structured receipt missing')
                return result['structuredContent']
            finally:
                if session:
                    # Ending a session is best effort. Never retry an execution
                    # because termination failed, and never let it erase a receipt.
                    try:
                        with client.stream('DELETE',tool.target()+tool.mcp_path,headers=headers,timeout=1):pass
                    except (httpx.HTTPError,ValueError,OSError):pass
    except (httpx.HTTPError,ValueError,TypeError,KeyError,OSError):
        raise GateError('upstream_mcp_unavailable',503) from None
