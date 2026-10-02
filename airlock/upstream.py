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
            row=conn.execute('SELECT document FROM actions WHERE principal=? AND idem=?',(principal,call.idempotency_key)).fetchone()
            if row:
                action=json.loads(row[0])
                if action['request_hash']!=request_hash: raise GateError('idempotency_conflict')
                governance.duplicate_hit(conn)
                return action
            gate.admit(conn,principal)
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
                    'backup_age_seconds':None,'recovery':'Remote compensation unavailable; reconcile the original receipt.'}
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
