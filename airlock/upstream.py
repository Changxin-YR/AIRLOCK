"""Allowlisted HTTP tools with CAS previews, durable claims and reconciliation."""
from __future__ import annotations
import json
import os
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse
import ipaddress
import httpx
from pydantic import BaseModel,ConfigDict,Field
from typing import Literal
from .models import GateError,canonical,digest
from . import governance
from . import observability


class Tool(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    name: str=Field(pattern=r'^upstream:[a-zA-Z0-9_-]{1,48}$')
    resource: str=Field(pattern=r'^[a-zA-Z0-9:_-]{1,64}$')
    url: str=Field(max_length=256)
    credential_env: str | None=Field(default=None,pattern=r'^AIRLOCK_UPSTREAM_[A-Z0-9_]+$')
    allow_loopback: bool=False
    transport: Literal['http','mcp_json']='http'
    mcp_path: str=Field(default='/mcp',pattern=r'^/[a-zA-Z0-9/_-]{1,100}$')
    mcp_tools: dict[Literal['preview','execute','receipt'],str]=Field(default_factory=dict)
    compensates: str | None=Field(default=None,pattern=r'^upstream:[a-zA-Z0-9_-]{1,48}$')
    arguments: dict[str,Literal['string','integer','boolean']]
    principals: list[str]=Field(default_factory=lambda:['agent:demo'],max_length=16)

    def target(self):
        parsed=urlparse(self.url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
            raise ValueError('upstream URL must be an origin')
        address=ipaddress.ip_address(parsed.hostname or '')
        if not address.is_global and not (self.allow_loopback and address.is_loopback):
            raise ValueError('private/link-local upstream rejected')
        if parsed.scheme!='https' and not (parsed.scheme=='http' and self.allow_loopback and address.is_loopback):
            raise ValueError('upstream HTTPS required')
        if len(self.arguments)>16 or any(not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]{0,47}',k) for k in self.arguments):
            raise ValueError('invalid argument schema')
        if self.transport=='mcp_json' and (set(self.mcp_tools)!={'preview','execute','receipt'} or any(not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',name) for name in self.mcp_tools.values())):
            raise ValueError('MCP writes require explicit preview/execute/receipt tool mappings')
        if self.transport=='http' and self.mcp_tools:raise ValueError('MCP tools supplied for HTTP transport')
        return self.url.rstrip('/')

    def validate_arguments(self,values):
        types={'string':str,'integer':int,'boolean':bool}
        if set(values)!=set(self.arguments) or any(type(values[k])!=types[t] for k,t in self.arguments.items()):
            raise GateError('tool_arguments_invalid',422)
        if len(canonical(values).encode())>4096 or any(type(v)==int and abs(v)>9007199254740991 for v in values.values()):
            raise GateError('tool_arguments_invalid',422)

    def request(self,method,path,payload=None):
        deadline=time.monotonic()+10
        token=os.environ.get(self.credential_env,'') if self.credential_env else None
        if self.credential_env and len(token)<32: raise GateError('upstream_credentials_unavailable',503)
        headers={'Authorization':'Bearer '+token} if token else {}
        if self.transport=='mcp_json':return self.mcp_request(method,path,payload,headers)
        try:
            with httpx.Client(timeout=httpx.Timeout(5,connect=2),trust_env=False,follow_redirects=False) as client:
                with client.stream(method,self.target()+path,json=payload,headers=headers) as response:
                    if response.status_code>=300: raise ValueError('upstream response')
                    body=bytearray()
                    for chunk in response.iter_bytes():
                        if time.monotonic()>deadline: raise ValueError('upstream total time limit')
                        body.extend(chunk)
                        if len(body)>16384: raise ValueError('upstream output limit')
                    result=json.loads(body); canonical(result)
                    return result
        except (httpx.HTTPError,ValueError,TypeError):
            raise GateError('upstream_unavailable',503) from None

    def mcp_request(self,method,path,payload,headers):
        """Only registered CAS-contract tools, not model-suggested discovery names.

        Discovery is checked against this allowlist. Only stateless JSON response
        upstreams are accepted here; redirects, opaque SSE and session-required
        servers fail closed rather than weakening receipt reconciliation.
        """
        phase='receipt' if method=='GET' and path.startswith('/receipts/') else {'/preview':'preview','/execute':'execute'}.get(path)
        if phase is None:raise GateError('upstream_method_forbidden',422)
        headers=dict(headers,Accept='application/json, text/event-stream')
        deadline=time.monotonic()+10
        try:
            with httpx.Client(timeout=httpx.Timeout(5,connect=2),trust_env=False,follow_redirects=False) as client:
                def send(message,notification=False):
                    with client.stream('POST',self.target()+self.mcp_path,json=message,headers=headers) as response:
                        if notification and response.status_code==202:return None
                        if response.status_code!=200 or response.headers.get('mcp-session-id'):raise ValueError('stateless MCP contract required')
                        if response.headers.get('content-type','').split(';')[0]!='application/json':raise ValueError('MCP JSON response required')
                        raw=bytearray()
                        for chunk in response.iter_bytes():
                            raw.extend(chunk)
                            if len(raw)>16384 or time.monotonic()>deadline:raise ValueError('MCP response budget')
                        data=json.loads(raw)
                        if data.get('jsonrpc')!='2.0' or data.get('id')!=message.get('id') or 'error' in data or 'result' not in data:raise ValueError('MCP response binding')
                        return data['result']
                initialized=send({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'airlock-controlled-proxy','version':'0.2'}}})
                if initialized.get('protocolVersion') not in {'2025-11-25','2025-06-18'}:raise ValueError('MCP version')
                headers['MCP-Protocol-Version']=initialized['protocolVersion']
                send({'jsonrpc':'2.0','method':'notifications/initialized'},True)
                discovered=send({'jsonrpc':'2.0','id':2,'method':'tools/list'})
                if self.mcp_tools[phase] not in {t.get('name') for t in discovered.get('tools',[])}:raise ValueError('registered MCP tool absent')
                arguments={'action_id':path.rsplit('/',1)[1]} if phase=='receipt' else payload
                result=send({'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':self.mcp_tools[phase],'arguments':arguments}})
                if result.get('isError') or not isinstance(result.get('structuredContent'),dict):raise ValueError('MCP structured receipt missing')
                return result['structuredContent']
        except (httpx.HTTPError,ValueError,TypeError,KeyError):raise GateError('upstream_mcp_unavailable',503) from None


class Preview(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    target_version: str=Field(min_length=1,max_length=128)
    impact_units: int=Field(ge=0,le=5000)
    summary: str=Field(max_length=300)
    before: dict
    after: dict


class Registry:
    def __init__(self,path):
        self.tools={}
        if path:
            raw=Path(path).read_text(encoding='utf-8')
            if len(raw.encode())>32768: raise ValueError('upstream config size')
            data=json.loads(raw)
            if set(data)!={'tools'} or not isinstance(data['tools'],list) or len(data['tools'])>16: raise ValueError('upstream config')
            for item in data['tools']:
                tool=Tool.model_validate(item); tool.target()
                if tool.name in self.tools: raise ValueError('duplicate upstream tool')
                self.tools[tool.name]=tool
            for tool in self.tools.values():
                if tool.compensates:
                    source=self.tools.get(tool.compensates)
                    if not source or source.compensates or tool.arguments!={'source_action_id':'string'} or any(
                        getattr(tool,k)!=getattr(source,k) for k in ('url','credential_env','resource')):
                        raise ValueError('compensation must bind a registered original resource and credential')

    def get(self,name,principal):
        tool=self.tools.get(name)
        if not tool or principal not in tool.principals: raise GateError('tool_not_authorized',403)
        return tool

    def discover(self,principal):
        return [{'name':t.name,'resource':t.resource,'arguments':t.arguments,
                 'description':'Controlled upstream. External review required; pending is not success.'}
                for t in self.tools.values() if principal in t.principals]


class RemoteActions:
    def __init__(self,gate): self.gate=gate

    def submit(self,call,principal):
        gate=self.gate; gate.expire()
        tool=gate.registry.get(call.tool,principal); tool.validate_arguments(call.arguments)
        if call.sql or call.parameters: raise GateError('tool_arguments_invalid',422)
        request_hash=digest({'principal':principal,'call':call.model_dump()})
        with gate.store.transaction() as conn:
            gate.policy.synchronize(conn)
            row=conn.execute('SELECT document FROM actions WHERE principal=? AND idem=?',(principal,call.idempotency_key)).fetchone()
            if row:
                action=json.loads(row[0])
                if action['request_hash']!=request_hash: raise GateError('idempotency_conflict')
                governance.duplicate_hit(conn)
                return action
            gate.admit(conn,principal)
            source_action=None
            if tool.compensates:
                source_row=conn.execute('SELECT document FROM actions WHERE id=? AND principal=?',
                    (call.arguments['source_action_id'],principal)).fetchone()
                if not source_row:raise GateError('compensation_source_unavailable',404)
                source_action=json.loads(source_row[0])
                if source_action['state']!='executed' or source_action['request']['tool']!=tool.compensates:
                    raise GateError('compensation_source_not_executed',409)
            action={'id':uuid.uuid4().hex,'principal':principal,'request':call.model_dump(),'request_hash':request_hash,
                'created_at':gate.clock(),'expires_at':gate.clock()+gate.settings.ttl_seconds,'version':1,
                'policy_version':gate.policy_version,'state':'blocked','decision':'block','reason_code':'upstream_preview_failed',
                'risk':'blocked','impact':None,'result':None,'review_digest':None,'confirmation_required':'','reviewer':None,
                'resource':tool.resource,'upstream_config_digest':digest(tool.model_dump()),'trace_id':uuid.uuid4().hex,
                'request_id':observability.request_id.get() or uuid.uuid4().hex,'template_version':'review-v2'}
            started=time.perf_counter()
            try:
                preview=Preview.model_validate(tool.request('POST','/preview',{'arguments':call.arguments}))
                impact={'certainty':'upstream_declared_exact','is_estimate':False,'source':'upstream_cas_preview',
                    'generated_at':gate.clock(),'target':tool.resource,'target_version':preview.target_version,
                    'changed_rows':preview.impact_units,'matched_rows':preview.impact_units,'before_count':None,'after_count':None,
                    'operations':['remote_write'],'sample':[],'sample_truncated':False,'preview':preview.model_dump(),
                    'backup_age_seconds':None,'recovery':'Only a separately registered and approved compensation can restore an upstream effect.'}
                compensators=[t.name for t in gate.registry.tools.values() if t.compensates==tool.name and principal in t.principals]
                impact['recovery_evidence']={
                    'technical_reversibility':'registered_cas_compensation' if compensators else 'unknown',
                    'restore_feasibility':'requires_new_preview_and_independent_approval' if compensators else 'unknown',
                    'business_authorization':'independent_approval_required','is_backup':False,
                    'registered_tools':compensators,'source_action_id':source_action['id'] if source_action else None,
                    'source_receipt_hash':digest(source_action['result']) if source_action else None}
                policy,hits=gate.policy.active.evaluate({'tool':call.tool,'resource':tool.resource,'principal':principal,
                    'operation':'remote_write','changed_rows':preview.impact_units,'matched_rows':preview.impact_units},True)
                action.update(impact=impact,rule_ids=hits,risk='critical' if preview.impact_units>=gate.settings.critical_rows else 'high')
                if policy!='block': action.update(state='pending',decision='need_approval',reason_code='write_requires_review')
                else: action['reason_code']='policy_block'
            except (GateError,ValueError,TypeError): pass
            action['evaluation_ms']=round((time.perf_counter()-started)*1000,3)
            gate.assess_semantics(action)
            action['evaluation_ms']=round((time.perf_counter()-started)*1000,3)
            action['reviewers']=gate.access.route(action)
            if action['state']=='pending':
                action['confirmation_required']=f"EXECUTE {action['impact']['changed_rows']}" if action['risk']=='critical' else ''
                if not action['reviewers']: action.update(state='blocked',decision='block',reason_code='review_route_missing')
                elif not governance.reserve(conn,action,gate.settings,gate.clock()): action.update(state='blocked',decision='block',reason_code='risk_budget_exhausted')
                else: action['review_digest']=gate.review_digest(action)
            conn.execute('INSERT INTO actions VALUES(?,?,?,?,?,?,?,?)',(action['id'],principal,call.idempotency_key,
                request_hash,action['state'],action['created_at'],action['expires_at'],canonical(action)))
            gate._event(conn,action,'action.evaluated',snapshot=action)
            return action

    def decide(self,action_id,decision,reviewer):
        gate=self.gate; gate.expire()
        with gate.store.transaction() as conn:
            gate.policy.synchronize(conn)
            action=json.loads(conn.execute('SELECT document FROM actions WHERE id=?',(action_id,)).fetchone()[0])
            gate.access.require(reviewer,action)
            if reviewer==action['principal']: raise GateError('self_approval_forbidden',403)
            if action['state']!='pending': raise GateError('action_not_pending')
            if decision.review_digest!=action['review_digest'] or decision.expected_version!=action['version']: raise GateError('review_binding_mismatch')
            human={'reviewer':reviewer,'decision':decision.decision,'reason':decision.reason,'review_digest':decision.review_digest,'visible_ms_untrusted':decision.visible_ms}
            action['reviewer']=reviewer
            action['batch_digest']=governance.batch_context.get();human['batch_digest']=action['batch_digest']
            if gate.clock()>=action['expires_at']: return gate._finish(conn,action,'expired','approval_expired',**human)
            if decision.decision=='reject': return gate._finish(conn,action,'rejected','human_rejected',**human)
            if decision.confirmation!=action['confirmation_required']: raise GateError('impact_confirmation_required',422)
            tool=gate.registry.get(action['request']['tool'],action['principal'])
            if action['policy_version']!=gate.policy_version or action['upstream_config_digest']!=digest(tool.model_dump()):
                return gate._finish(conn,action,'stale','configuration_changed',**human)
            if gate.review_digest(action)!=action['review_digest'] or digest({'principal':action['principal'],'call':action['request']})!=action['request_hash']:
                return gate._finish(conn,action,'failed','stored_review_mismatch',**human)
            action['execution_deadline']=gate.clock()+15
            gate._finish(conn,action,'executing','remote_execution_claimed',**human)
        try:
            execution_started=time.perf_counter()
            receipt=tool.request('POST','/execute',{'action_id':action['id'],'request_hash':action['request_hash'],
                'expected_version':action['impact']['target_version'],'arguments':action['request']['arguments']})
            action['execution_ms']=(time.perf_counter()-execution_started)*1000
            return self.finish(action,receipt)
        except (GateError,ValueError,TypeError):
            with gate.store.transaction() as conn:
                current=json.loads(conn.execute('SELECT document FROM actions WHERE id=?',(action['id'],)).fetchone()[0])
                if current['state'] not in {'executing','unknown'}: return current
                return gate._finish(conn,current,'unknown','remote_result_unknown')

    def finish(self,action,receipt):
        if not isinstance(receipt,dict) or set(receipt)!={'action_id','request_hash','state','result'} or receipt['action_id']!=action['id'] or receipt['request_hash']!=action['request_hash'] or receipt['state'] not in {'executed','stale','failed'}:
            raise ValueError('unbound upstream receipt')
        gate=self.gate
        with gate.store.transaction() as conn:
            current=json.loads(conn.execute('SELECT document FROM actions WHERE id=?',(action['id'],)).fetchone()[0])
            if current['state'] not in {'executing','unknown'}: return current
            current['result']=receipt['result']
            if 'execution_ms' in action: current['execution_ms']=action['execution_ms']
            return gate._finish(conn,current,receipt['state'],'upstream_receipt',receipt=receipt)

    def reconcile(self,action):
        if action['state'] not in {'executing','unknown'}: return action
        tool=self.gate.registry.get(action['request']['tool'],action['principal'])
        try: return self.finish(action,tool.request('GET','/receipts/'+action['id']))
        except (GateError,ValueError,TypeError): return action
