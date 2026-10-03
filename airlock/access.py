"""Operator-owned reviewer routing. Config and revocation are checked server-side."""
import json
import os
import secrets
from pathlib import Path
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from .models import GateError
from . import governance


class Reviewer(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    id: str=Field(pattern=r'^reviewer:[a-zA-Z0-9_-]{1,48}$')
    credential_env: str | None=Field(default=None,pattern=r'^AIRLOCK_REVIEWER_[A-Z0-9_]+$')
    tools: list[str]=Field(min_length=1,max_length=16)
    resources: list[str]=Field(min_length=1,max_length=16)
    risks: list[Literal['low','high','critical','blocked']]=Field(min_length=1,max_length=4)
    active: bool=True


class Reviewers(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    reviewers: list[Reviewer]=Field(max_length=32)


class AccessControl:
    def __init__(self,settings): self.settings=settings

    def accounts(self):
        if not self.settings.reviewer_file: return None
        try:
            text=Path(self.settings.reviewer_file).read_text(encoding='utf-8')
            if len(text.encode())>32768: raise ValueError('configuration size')
            rows=Reviewers.model_validate_json(text).reviewers
            if len({r.id for r in rows})!=len(rows) or any(r.id=='reviewer:owner' for r in rows): raise ValueError('duplicate or reserved reviewer')
            active=[r for r in rows if r.active]
            if any(r.credential_env is None for r in active) and not self.settings.oidc_file:
                raise ValueError('OIDC-only reviewer requires configured issuer')
            tokens=[os.environ.get(r.credential_env,'') for r in active if r.credential_env]
            if any(len(t)<32 or not t.isascii() for t in tokens): raise ValueError('invalid reviewer credential')
            if len(set(tokens))!=len(tokens) or any(t in {self.settings.agent_token,self.settings.audit_key,self.settings.reviewer_token} for t in tokens):
                raise ValueError('credential separation')
            return active
        except (OSError,ValueError,TypeError):
            raise GateError('reviewer_configuration_unavailable',503) from None

    def identify(self,token):
        accounts=self.accounts()
        from .oidc import identify
        who=identify(token,self.settings.oidc_file)
        if who:
            if who=='agent:demo':return who
            return who if accounts is not None and any(r.id==who for r in accounts) else None
        if accounts is None:
            return 'reviewer:owner' if secrets.compare_digest(token.encode(),self.settings.reviewer_token.encode()) else None
        for row in accounts:
            if row.credential_env and secrets.compare_digest(token.encode(),os.environ[row.credential_env].encode()): return row.id
        return None

    def route(self,action):
        return self._route(action,self.accounts())

    @staticmethod
    def _route(action,accounts):
        if accounts is None: return ['reviewer:owner']
        return sorted(r.id for r in accounts if action['request']['tool'] in r.tools
            and action.get('resource','customers') in r.resources and action['risk'] in r.risks)

    def can_review(self,who,action):
        return who in action.get('reviewers',['reviewer:owner']) and who in self.route(action)

    def require(self,who,action):
        # Read one current account snapshot at each member's transaction boundary.
        # A batch's cumulative critical requirement must survive this same check;
        # individually high-risk members cannot continue after critical revocation.
        accounts=self.accounts()
        if who not in action.get('reviewers',['reviewer:owner']) or who not in self._route(action,accounts):
            raise GateError('review_scope_forbidden',403)
        if governance.batch_risk.get()=='critical' and who not in self._route(dict(action,risk='critical'),accounts):
            raise GateError('group_risk_route_forbidden',403)
