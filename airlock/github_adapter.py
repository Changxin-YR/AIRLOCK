"""Server-owned GitHub issue creation, with a durable at-most-one-send claim.

GitHub does not provide target CAS or atomicity with this SQLite journal. An
uncertain send stays unknown. There is no automatic mutation retry. Relay mode
is an explicitly trusted operator bridge, not agent-supplied proof of execution.
"""
from __future__ import annotations

import hmac
import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import network
from .models import GateError, canonical, digest
from .sqlite_runtime import enable_wal, require_safe_python_runtime

API_ORIGIN = 'https://api.github.com'
REPOSITORY_QUERY = '''query($id: ID!) { node(id: $id) { ... on Repository {
 id nameWithOwner isPrivate isArchived hasIssuesEnabled } } }'''
CREATE_MUTATION = '''mutation($input: CreateIssueInput!) { createIssue(input: $input) {
 clientMutationId issue { id number url title body repository { id nameWithOwner } } } }'''
ISSUE_QUERY = '''query($id: ID!) { node(id: $id) { ... on Issue {
 id number url title body repository { id nameWithOwner } } } }'''


class AdapterConfig(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    repository_node_id: str = Field(pattern=r'^[A-Za-z0-9_=-]{4,128}$')
    repository_full_name: str = Field(pattern=r'^[A-Za-z0-9-]{1,39}/[A-Za-z0-9_.-]{1,100}$')
    public_repository: bool
    mode: Literal['direct', 'relay'] = 'direct'
    gate_credential_env: str = Field(default='AIRLOCK_UPSTREAM_GITHUB_GATE_TOKEN', pattern=r'^AIRLOCK_UPSTREAM_[A-Z0-9_]+$')
    github_credential_env: str = Field(default='AIRLOCK_GITHUB_API_TOKEN', pattern=r'^AIRLOCK_GITHUB_[A-Z0-9_]+$')
    relay_credential_env: str = Field(default='AIRLOCK_GITHUB_RELAY_TOKEN', pattern=r'^AIRLOCK_GITHUB_[A-Z0-9_]+$')
    api_pinned_addresses: list[str] = Field(default_factory=list, max_length=16)
    relay_claim_ttl_seconds: int = Field(default=300, ge=30, le=600)
    max_claims: int = Field(default=10000, ge=1, le=10000)

    @model_validator(mode='after')
    def distinct_credentials(self):
        if len({self.gate_credential_env, self.github_credential_env, self.relay_credential_env}) != 3:
            raise ValueError('distinct service, GitHub and relay credentials required')
        if self.mode == 'direct':
            network.validate_origin(API_ORIGIN, self.api_pinned_addresses)
        return self


class IssueArguments(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(max_length=1000)

    @model_validator(mode='after')
    def valid_text(self):
        if not self.title.strip() or any(ord(c) < 32 for c in self.title):
            raise ValueError('nonempty single-line title required')
        if any(ord(c) < 32 and c not in '\n\r\t' for c in self.body):
            raise ValueError('invalid body control character')
        if '<!-- AIRLOCK ' in self.body:
            raise ValueError('reserved receipt marker')
        return self


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    arguments: IssueArguments


class ExecuteRequest(PreviewRequest):
    action_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    request_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    expected_version: str = Field(pattern=r'^[a-f0-9]{64}$')


class ObservedIssue(BaseModel):
    """Exact values read back from GitHub by the independently trusted operator."""
    model_config = ConfigDict(extra='forbid', strict=True)
    repository_node_id: str = Field(pattern=r'^[A-Za-z0-9_=-]{4,128}$')
    repository_full_name: str = Field(max_length=140)
    issue_node_id: str = Field(pattern=r'^[A-Za-z0-9_=-]{4,128}$')
    number: int = Field(ge=1, le=2147483647)
    url: str = Field(max_length=256)
    title: str = Field(max_length=200)
    body: str = Field(max_length=1300)


class RelayCompletion(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    claim_token: str = Field(min_length=32, max_length=128)
    binding_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    observed_issue: ObservedIssue
    observation_reference: str = Field(min_length=3, max_length=200)


class ReconcileRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    issue_node_id: str = Field(pattern=r'^[A-Za-z0-9_=-]{4,128}$')


def secret(name):
    value = os.environ.get(name, '')
    if len(value) < 32 or not value.isascii():
        raise ValueError('adapter credential unavailable: ' + name)
    return value


class GitHubAPI:
    def __init__(self, config):
        self.config = config

    def graphql(self, query, variables):
        token = secret(self.config.github_credential_env)
        deadline = time.monotonic() + 7
        with network.client(API_ORIGIN, pins=self.config.api_pinned_addresses,
                            timeout=httpx.Timeout(5, connect=2)) as client:
            with client.stream('POST', API_ORIGIN + '/graphql',
                               headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'},
                               json={'query': query, 'variables': variables}) as response:
                if response.status_code != 200:
                    raise ValueError('GitHub response unavailable')
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 16384 or time.monotonic() > deadline:
                        raise ValueError('GitHub response budget')
                result = json.loads(body)
        if not isinstance(result, dict) or result.get('errors') or not isinstance(result.get('data'), dict):
            raise ValueError('GitHub GraphQL result unavailable')
        return result['data']

    def repository(self):
        repository = self.graphql(REPOSITORY_QUERY, {'id': self.config.repository_node_id}).get('node')
        if not isinstance(repository, dict) or repository.get('id') != self.config.repository_node_id or repository.get('nameWithOwner') != self.config.repository_full_name or type(repository.get('isPrivate')) is not bool or repository['isPrivate'] == self.config.public_repository or repository.get('isArchived') is not False or repository.get('hasIssuesEnabled') is not True:
            raise ValueError('configured repository changed or unavailable')

    def create(self, claim):
        self.repository()  # Read-only preflight; no guarantee against later changes.
        payload = {'repositoryId': self.config.repository_node_id, 'title': claim['title'],
                   'body': claim['body'], 'clientMutationId': claim['action_id']}
        data = self.graphql(CREATE_MUTATION, {'input': payload})['createIssue']
        if data.get('clientMutationId') != claim['action_id']:
            raise ValueError('mutation correlation mismatch')
        return self.observed(data['issue'])

    def read_issue(self, issue_node_id):
        issue = self.graphql(ISSUE_QUERY, {'id': issue_node_id})['node']
        if not isinstance(issue, dict) or issue.get('id') != issue_node_id:
            raise ValueError('issue readback identity mismatch')
        return self.observed(issue)

    @staticmethod
    def observed(issue):
        return ObservedIssue(repository_node_id=issue['repository']['id'],
                             repository_full_name=issue['repository']['nameWithOwner'],
                             issue_node_id=issue['id'], number=issue['number'], url=issue['url'],
                             title=issue['title'], body=issue['body'])


class IssueAdapter:
    def __init__(self, config: AdapterConfig, database: Path):
        require_safe_python_runtime()
        self.config = config
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self.api = GitHubAPI(config)
        with self.connection() as conn:
            enable_wal(conn)
            conn.execute('CREATE TABLE IF NOT EXISTS github_claims (action_id TEXT PRIMARY KEY, document TEXT NOT NULL)')

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.database, timeout=5)
        conn.execute('PRAGMA synchronous=FULL')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def preview(self, arguments: IssueArguments):
        if self.config.mode == 'direct':
            self.api.repository()
        plan = {'repository_node_id': self.config.repository_node_id,
                'repository_full_name': self.config.repository_full_name,
                'arguments': arguments.model_dump(), 'config_digest': digest(self.config.model_dump())}
        return {'target_version': digest(plan), 'impact_units': 1,
                'summary': 'Create one GitHub issue; visibility and notifications may propagate. No target CAS; copies and notifications cannot be undone.',
                'before': {'new_issue': 'absent; issue number not yet allocated'},
                'after': {'repository': self.config.repository_full_name, **arguments.model_dump(),
                          'visibility': 'public' if self.config.public_repository else 'repository members and downstream integrations',
                          'tracking_marker_appended': '<!-- AIRLOCK action_id=<id> request_hash=<hash> -->',
                          'notification_count': 'unknown', 'restore': 'not fully reversible',
                          'external_conditions': 'Repository visibility, permissions and integrations may change; no CAS guards those changes.',
                          'plan_only': True, 'target_cas': False}}

    def _plan_digest(self, arguments):
        return digest({'repository_node_id': self.config.repository_node_id,
                       'repository_full_name': self.config.repository_full_name,
                       'arguments': arguments.model_dump(), 'config_digest': digest(self.config.model_dump())})

    def _load(self, conn, action_id):
        row = conn.execute('SELECT document FROM github_claims WHERE action_id=?', (action_id,)).fetchone()
        if not row:
            raise GateError('github_claim_not_found', 404)
        return json.loads(row[0])

    def _save(self, conn, row):
        conn.execute('UPDATE github_claims SET document=? WHERE action_id=?', (canonical(row), row['action_id']))

    def _receipt(self, row):
        return row.get('receipt') or {'action_id': row['action_id'], 'request_hash': row['request_hash'], 'state': 'unknown', 'result': None}

    def receipt(self, action_id):
        with self.connection() as conn:
            return self._receipt(self._load(conn, action_id))

    def execute(self, request: ExecuteRequest):
        binding = digest(request.model_dump())
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            existing = conn.execute('SELECT document FROM github_claims WHERE action_id=?', (request.action_id,)).fetchone()
            if existing:
                row = json.loads(existing[0])
                if row['binding_digest'] != binding or row['config_digest'] != digest(self.config.model_dump()):
                    raise GateError('github_claim_binding_mismatch')
                return self._receipt(row)
            if request.expected_version != self._plan_digest(request.arguments):
                return {'action_id': request.action_id, 'request_hash': request.request_hash,
                        'state': 'stale', 'result': {'reason': 'creation_plan_changed', 'execution_occurred': False}}
            if conn.execute('SELECT COUNT(*) FROM github_claims').fetchone()[0] >= self.config.max_claims:
                raise GateError('github_claim_capacity', 429)
            row = {'action_id': request.action_id, 'request_hash': request.request_hash, 'binding_digest': binding,
                   'config_digest': digest(self.config.model_dump()), 'created_at': time.time(),
                   'state': 'queued' if self.config.mode == 'relay' else 'claimed',
                   'title': request.arguments.title,
                   'body': request.arguments.body + '\n\n<!-- AIRLOCK action_id=' + request.action_id + ' request_hash=' + request.request_hash + ' -->'}
            conn.execute('INSERT INTO github_claims VALUES(?,?)', (request.action_id, canonical(row)))
        # The durable claim commits before any mutation. Never re-send an existing
        # row, even if a process died before actually reaching GitHub.
        if self.config.mode == 'direct':
            try:
                observed = self.api.create(row)
                return self._complete(row['action_id'], observed, 'github_response', None)
            except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError):
                pass
        return self._receipt(row)

    def claim(self, action_id):
        if self.config.mode != 'relay':
            raise GateError('github_relay_disabled', 403)
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = self._load(conn, action_id)
            if row['state'] != 'queued' or row['config_digest'] != digest(self.config.model_dump()):
                raise GateError('github_claim_unavailable')
            deadline = row['created_at'] + self.config.relay_claim_ttl_seconds
            if time.time() >= deadline:
                raise GateError('github_claim_expired')
            claim_token = secrets.token_urlsafe(32)
            row.update(state='claimed', claim_hash=digest(claim_token), claimed_at=time.time())
            self._save(conn, row)
            return {'action_id': row['action_id'], 'request_hash': row['request_hash'],
                    'binding_digest': row['binding_digest'], 'claim_token': claim_token,
                    'repository_node_id': self.config.repository_node_id,
                    'repository_full_name': self.config.repository_full_name,
                    'title': row['title'], 'body': row['body'], 'valid_until': deadline,
                    'execution_model': 'append_only_create', 'must_not_retry_mutation': True,
                    'receipt_verification': 'operator_attested'}

    def complete_relay(self, action_id, completion: RelayCompletion):
        if self.config.mode != 'relay':
            raise GateError('github_relay_disabled', 403)
        return self._complete(action_id, completion.observed_issue, 'operator_attested', completion)

    def reconcile_direct(self, action_id, issue_node_id):
        if self.config.mode != 'direct':
            raise GateError('github_direct_reconciliation_disabled', 403)
        with self.connection() as conn:
            row = self._load(conn, action_id)
            if row['state'] == 'executed':
                if row['receipt']['result']['issue_node_id'] != issue_node_id:
                    raise GateError('github_observation_mismatch')
                return row['receipt']
        # The operator chooses an issue to inspect, never a URL or mutation. The
        # server independently retrieves it and verifies all original bindings.
        observed = self.api.read_issue(issue_node_id)
        return self._complete(action_id, observed, 'github_readback', None)

    def _complete(self, action_id, observed, verification, completion):
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = self._load(conn, action_id)
            if row['state'] not in {'claimed', 'executed'} or row['config_digest'] != digest(self.config.model_dump()):
                raise GateError('github_claim_unavailable')
            if completion and (completion.binding_digest != row['binding_digest'] or not hmac.compare_digest(digest(completion.claim_token), row.get('claim_hash', ''))):
                raise GateError('github_relay_binding_mismatch')
            expected_url = 'https://github.com/' + self.config.repository_full_name + '/issues/' + str(observed.number)
            if observed.repository_node_id != self.config.repository_node_id or observed.repository_full_name != self.config.repository_full_name or observed.title != row['title'] or observed.body != row['body'] or observed.url != expected_url:
                raise GateError('github_observation_mismatch')
            result = {'repository_node_id': observed.repository_node_id, 'repository_full_name': observed.repository_full_name,
                      'issue_node_id': observed.issue_node_id, 'number': observed.number, 'url': observed.url,
                      'title_sha256': hashlib.sha256(observed.title.encode()).hexdigest(),
                      'body_sha256': hashlib.sha256(observed.body.encode()).hexdigest(),
                      'receipt_verification': verification, 'target_cas': False, 'fully_reversible': False}
            if completion:
                result['observation_reference'] = completion.observation_reference
            receipt = {'action_id': action_id, 'request_hash': row['request_hash'], 'state': 'executed', 'result': result}
            if row['state'] == 'executed':
                if row['receipt'] != receipt:
                    raise GateError('github_receipt_conflict')
                return row['receipt']
            row.update(state='executed', receipt=receipt, completed_at=time.time())
            self._save(conn, row)
            return receipt


def create_app(config: AdapterConfig, database: Path):
    gate_token = secret(config.gate_credential_env)
    relay_token = secret(config.relay_credential_env)
    api_token = secret(config.github_credential_env) if config.mode == 'direct' else None
    if len({v for v in (gate_token, relay_token, api_token) if v}) != (3 if api_token else 2):
        raise ValueError('adapter credentials must be distinct')
    adapter = IssueAdapter(config, database)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.adapter = adapter

    @app.middleware('http')
    async def boundary(request: Request, call_next):
        if request.headers.get('origin') is not None:
            return JSONResponse({'error': 'browser_origin_forbidden'}, status_code=403)
        if request.method == 'POST':
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 8192:
                    return JSONResponse({'error': 'request_too_large'}, status_code=413)
            request._body = bytes(body)
        result = await call_next(request)
        result.headers['Cache-Control'] = 'no-store'
        return result

    @app.exception_handler(GateError)
    async def gate_error(request, error):
        return JSONResponse({'error': error.code}, status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse({'error': 'invalid_adapter_request'}, status_code=422)

    def authorize(authorization, role):
        expected = relay_token if role == 'relay' else gate_token
        if not expected or not hmac.compare_digest((authorization or '').encode(), ('Bearer ' + expected).encode()):
            raise GateError('adapter_authentication_required', 403)

    @app.post('/preview')
    def preview(request: PreviewRequest, authorization: str | None = Header(default=None)):
        authorize(authorization, 'gate')
        try:
            return adapter.preview(request.arguments)
        except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError):
            raise GateError('github_preview_unavailable', 503) from None

    @app.post('/execute')
    def execute(request: ExecuteRequest, authorization: str | None = Header(default=None)):
        authorize(authorization, 'gate')
        return adapter.execute(request)

    @app.get('/receipts/{action_id}')
    def receipt(action_id: str, authorization: str | None = Header(default=None)):
        authorize(authorization, 'gate')
        return adapter.receipt(action_id)

    @app.post('/operator/claim/{action_id}')
    def claim(action_id: str, authorization: str | None = Header(default=None)):
        authorize(authorization, 'relay')
        return adapter.claim(action_id)

    @app.post('/operator/complete/{action_id}')
    def complete(action_id: str, request: RelayCompletion, authorization: str | None = Header(default=None)):
        authorize(authorization, 'relay')
        return adapter.complete_relay(action_id, request)

    @app.post('/operator/reconcile/{action_id}')
    def reconcile(action_id: str, request: ReconcileRequest, authorization: str | None = Header(default=None)):
        authorize(authorization, 'relay')
        try:
            return adapter.reconcile_direct(action_id, request.issue_node_id)
        except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError):
            raise GateError('github_readback_unavailable', 503) from None

    return app
