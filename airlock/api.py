"""Bearer-authenticated HTTP adapter and same-origin reviewer console."""
import asyncio
import json
import secrets
import sqlite3
import uuid
from pathlib import Path
from urllib.parse import urlparse
from typing import Annotated, Literal
from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse,Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .models import BatchDecision, Decision, GateError, GovernanceChange, Invocation, Settings
from .service import Gate, agent_view
from . import observability

STATIC = Path(__file__).parent / "static"
CONSOLE = Path(__file__).parent / "console"


class ConsoleAssets(StaticFiles):
    """Module MIME types must not depend on the Windows registry."""
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        media = {'.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html'}.get(Path(path).suffix)
        if media and response.status_code == 200:
            response.headers['content-type'] = media + '; charset=utf-8'
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    # A partially built console must fail before Gate can initialize a new
    # database or recover an existing WAL. API-only startup remains supported
    # when neither console entry point nor CSP manifest is installed.
    from .diagnostics import ConsoleValidationError, validate_console
    console_hashes = []
    try:
        if any(path.exists() or path.is_symlink() for path in (CONSOLE/'index.html', CONSOLE/'csp.json')):
            console_hashes = validate_console(CONSOLE)
    except (ConsoleValidationError, OSError):
        raise ValueError('console build is incomplete or invalid; run npm ci and npm run build') from None
    gate = Gate(settings)
    app = FastAPI(title="Airlock", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.gate = gate
    # Hashes come from the validated local build, never a request header.
    script_policy = "script-src 'self' " + ' '.join(console_hashes)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlparse(settings.origin).hostname] + ([settings.internal_host] if settings.internal_host else []))

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        request_identifier=uuid.uuid4().hex
        observability.request_id.set(request_identifier)
        if request.method not in ("GET", "HEAD") and request.headers.get("origin") not in (None, settings.origin):
            return JSONResponse({"error": "origin_forbidden"}, status_code=403)
        length = request.headers.get("content-length", "0")
        if not length.isdigit() or int(length) > 16384:
            return JSONResponse({"error": "request_too_large"}, status_code=413)
        # Also bound chunked/lengthless bodies before Pydantic parses them.
        if request.method == "POST":
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 16384:
                    return JSONResponse({"error": "request_too_large"}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers.update({
            "X-Request-ID": request_identifier, "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self'; " + script_policy + "; style-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        })
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        # Do not echo raw inputs: non-finite JSON can otherwise break error serialization.
        return JSONResponse({"error": "validation_error", "execution_occurred": False,
                             "detail": [{"loc": list(item["loc"]), "type": item["type"]}
                                        for item in exc.errors()]}, status_code=422)

    @app.exception_handler(GateError)
    async def gate_error(request, exc):
        return JSONResponse({"error": exc.code, "execution_occurred": False if exc.status in (401, 403, 422) else None,
                             "next_step": "Query action status; retry submissions only with the original idempotency key."},
                            status_code=exc.status)

    @app.exception_handler(sqlite3.Error)
    async def storage_error(request, exc):
        return JSONResponse({"error": "storage_unavailable", "execution_occurred": None, "next_step": "Query action status before retrying."}, status_code=503)

    def identity(authorization: Annotated[str | None, Header()] = None) -> str:
        token = (authorization or "").removeprefix("Bearer ")
        if not (authorization or "").startswith("Bearer "):
            raise GateError("authentication_required", 401)
        review_identity=gate.access.identify(token)
        if review_identity: return review_identity
        if secrets.compare_digest(token.encode(), settings.agent_token.encode()):
            return "agent:demo"
        raise GateError("authentication_required", 401)

    def reviewer(who: Annotated[str, Depends(identity)]) -> str:
        if not who.startswith('reviewer:'):
            raise GateError("reviewer_required", 403)
        return who

    def agent(who: Annotated[str, Depends(identity)]) -> str:
        if who != "agent:demo":
            raise GateError("agent_credential_required", 403)
        return who

    def operator(authorization: Annotated[str | None,Header()]=None):
        token=(authorization or '').removeprefix('Bearer ')
        if not (authorization or '').startswith('Bearer ') or not secrets.compare_digest(token.encode(),settings.reviewer_token.encode()):
            raise GateError('operator_required',403)
        return 'operator:owner'

    @app.get('/v1/governance/suggestions')
    def suggestions(who: Annotated[str,Depends(operator)]):
        return {'items':gate.suggestions(),'active':gate.governance_preference()}

    @app.get('/v1/operations/health')
    def operations_health(who: Annotated[str,Depends(operator)]):
        from .operations import health
        return health(gate)

    @app.get('/v1/operations/prometheus')
    def operations_metrics(who: Annotated[str,Depends(operator)]):
        from .operations import health,prometheus
        return Response(prometheus(health(gate)),media_type='text/plain; version=0.0.4')

    @app.post('/v1/policy/reload')
    def reload_policy(who: Annotated[str,Depends(operator)]):
        return gate.reload_policy()

    @app.post('/v1/semantic/cache/invalidate')
    def invalidate_semantic(who: Annotated[str,Depends(operator)]):
        with gate.store.transaction() as conn:
            gate.store.audit(conn,'governance:cache',{'kind':'governance.changed','at':gate.clock(),
                'state':'requested','detail':{'kind':'semantic_cache_invalidation','operator':who}})
        return gate.semantic.invalidate_cache()

    @app.post('/v1/observability/export')
    def export_telemetry(who:Annotated[str,Depends(operator)]):
        from .telemetry import export
        return export(gate.store)

    @app.post('/v1/governance/activate')
    def activate(body: GovernanceChange,who: Annotated[str,Depends(operator)]):
        return gate.change_governance(body)

    @app.post('/v1/governance/revoke')
    def revoke(body: GovernanceChange,who: Annotated[str,Depends(operator)]):
        return gate.change_governance(body,True)

    @app.get("/healthz")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/v1/me")
    def me(who: Annotated[str, Depends(identity)]):
        return {"principal": who, "role": 'reviewer' if who.startswith('reviewer:') else 'agent'}

    @app.get('/v1/groups')
    def groups(who: Annotated[str,Depends(reviewer)]):
        return {'items':gate.groups(who)}

    @app.get('/v1/tools')
    def tools(who: Annotated[str,Depends(agent)]):
        return {'items':gate.registry.discover(who)}

    @app.post('/mcp')
    async def streamable_mcp(request: Request,who: Annotated[str,Depends(agent)]):
        from .mcp_http import dispatch,VERSIONS
        if request.headers.get('mcp-protocol-version','2025-11-25') not in VERSIONS:
            return JSONResponse({'error':'unsupported_mcp_protocol_version'},status_code=400)
        accept=request.headers.get('accept','')
        if 'application/json' not in accept or 'text/event-stream' not in accept:
            return JSONResponse({'error':'mcp_accept_types_required'},status_code=406)
        if not request.headers.get('content-type','').split(';')[0].strip()=='application/json':
            return JSONResponse({'error':'json_content_type_required'},status_code=415)
        try:body=await request.json()
        except ValueError:return JSONResponse({'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Parse error'}},status_code=400)
        result=await asyncio.to_thread(dispatch,gate,who,body)
        return Response(status_code=202) if result is None else JSONResponse(result)

    @app.api_route('/mcp',methods=['GET','DELETE'])
    def no_stream_session(request:Request,who:Annotated[str,Depends(agent)]):
        if request.headers.get('origin') not in (None,settings.origin):raise GateError('origin_forbidden',403)
        return Response(status_code=405,headers={'Allow':'POST'})

    @app.post('/v1/actions/{action_id}/reconcile')
    def reconcile(action_id: str,who: Annotated[str,Depends(agent)]):
        action=gate.get(action_id,who)
        return agent_view(gate.remote.reconcile(action))

    @app.post('/v1/groups/decision')
    def group_decision(body: BatchDecision,who: Annotated[str,Depends(reviewer)]):
        return gate.decide_group(body,who)

    @app.post("/v1/actions")
    def invoke(body: Invocation, who: Annotated[str, Depends(agent)]):
        action = gate.submit(body, who)
        return JSONResponse(agent_view(action), status_code=202 if action["state"] == "pending" else 200)

    @app.get("/v1/actions")
    def listing(who: Annotated[str, Depends(reviewer)], limit: int = Query(100, ge=1, le=100),
                before: float | None = Query(None, ge=0, allow_inf_nan=False),
                before_id: str | None = Query(None, pattern=r"^[a-f0-9]{32}$"),
                state_filter: Literal["pending", "executed", "blocked", "rejected", "expired", "stale", "failed", "executing", "unknown"] | None = Query(None, alias="state")):
        if (before is None) != (before_id is None):
            raise GateError("cursor_requires_time_and_id", 422)
        items = gate.list_actions(limit, before, before_id, state_filter, who)
        cursor = {"before": items[-1]["created_at"], "before_id": items[-1]["id"]} if len(items) == limit else None
        return {"items": items, "next_cursor": cursor}

    @app.get("/v1/actions/{action_id}")
    def detail(action_id: str, who: Annotated[str, Depends(identity)]):
        is_reviewer=who.startswith('reviewer:')
        item = gate.get(action_id, None if is_reviewer else who)
        if is_reviewer: gate.access.require(who,item)
        return item if is_reviewer else agent_view(item)

    @app.post("/v1/actions/{action_id}/decision")
    def decide(action_id: str, body: Decision, who: Annotated[str, Depends(reviewer)]):
        return gate.decide(action_id, body, who)

    @app.get("/v1/audit")
    def audit(who: Annotated[str, Depends(reviewer)], action_id: str | None = None,
              after: int = Query(0, ge=0)):
        items = gate.audit_events(who,action_id,after)
        return {"items": items, "next_after": items[-1]["seq"] if items else after}

    @app.get("/v1/audit/verify")
    def verify(who: Annotated[str, Depends(reviewer)]):
        if settings.reviewer_file: raise GateError('operator_audit_verification_required',403)
        return gate.store.verify_audit()

    @app.get('/v1/audit/export')
    def export_audit(who: Annotated[str, Depends(reviewer)], after: int = Query(0, ge=0)):
        from .export import redacted_export
        items=gate.audit_events(who,None,after)
        return {**redacted_export(items),'next_after':items[-1]['seq'] if items else after}

    @app.get('/v1/audit/checkpoint')
    def checkpoint(who: Annotated[str,Depends(operator)]):
        return gate.store.checkpoint()

    @app.get('/v1/audit/completeness')
    def audit_completeness(who:Annotated[str,Depends(operator)]):
        from .audit_schema import completeness
        return completeness(gate.store.audit_events(limit=100000))

    @app.post('/v1/audit/keys/{key_id}/rotate')
    def rotate_key(key_id: str,who: Annotated[str,Depends(operator)]):
        try:return gate.store.rotate_key(key_id,gate.clock())
        except (ValueError,OSError,KeyError):raise GateError('audit_key_rotation_failed',422) from None

    @app.get("/v1/metrics")
    def metrics(who: Annotated[str, Depends(reviewer)]):
        return gate.metrics(who)

    @app.get("/v1/events")
    async def events(request: Request, who: Annotated[str, Depends(reviewer)],
                     after: int = Query(0, ge=0)):
        async def stream():
            cursor = after
            # A bounded connection lease; the client reconnects with its durable cursor.
            for _ in range(30):
                if await request.is_disconnected():
                    return
                await asyncio.to_thread(gate.expire)
                try:
                    active=gate.access.identify((request.headers.get('authorization') or '').removeprefix('Bearer '))
                except GateError:
                    return
                if active != who:
                    return
                items = await asyncio.to_thread(gate.audit_events, who, None, cursor, 100)
                for item in items:
                    cursor = item["seq"]
                    yield f"id: {cursor}\nevent: action\ndata: {json.dumps({'action_id': item['action_id']})}\n\n"
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    @app.get("/")
    def index():
        if not (CONSOLE / "index.html").exists():
            return JSONResponse({"error": "console_assets_missing", "next_step": "Run npm ci and npm run build before starting AIRLOCK."}, status_code=503)
        return FileResponse(CONSOLE / "index.html")

    app.mount("/_next", ConsoleAssets(directory=CONSOLE/'_next', check_dir=False), name="next-assets")
    app.mount("/assets", ConsoleAssets(directory=STATIC, check_dir=False), name="assets")
    return app
