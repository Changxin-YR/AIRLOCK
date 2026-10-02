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
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .models import Decision, GateError, Invocation, Settings
from .service import Gate, agent_view

STATIC = Path(__file__).parent / "static"


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
    gate = Gate(settings)
    app = FastAPI(title="Airlock", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.gate = gate
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlparse(settings.origin).hostname] + ([settings.internal_host] if settings.internal_host else []))

    @app.middleware("http")
    async def boundary(request: Request, call_next):
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
            "X-Request-ID": uuid.uuid4().hex, "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; "
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
        if secrets.compare_digest(token.encode(), settings.reviewer_token.encode()):
            return "reviewer:owner"
        if secrets.compare_digest(token.encode(), settings.agent_token.encode()):
            return "agent:demo"
        raise GateError("authentication_required", 401)

    def reviewer(who: Annotated[str, Depends(identity)]) -> str:
        if who != "reviewer:owner":
            raise GateError("reviewer_required", 403)
        return who

    def agent(who: Annotated[str, Depends(identity)]) -> str:
        if who != "agent:demo":
            raise GateError("agent_credential_required", 403)
        return who

    @app.get("/healthz")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.get("/v1/me")
    def me(who: Annotated[str, Depends(identity)]):
        return {"principal": who}

    @app.post("/v1/actions")
    def invoke(body: Invocation, who: Annotated[str, Depends(agent)]):
        action = gate.submit(body, who)
        return JSONResponse(agent_view(action), status_code=202 if action["state"] == "pending" else 200)

    @app.get("/v1/actions")
    def listing(who: Annotated[str, Depends(reviewer)], limit: int = Query(100, ge=1, le=100),
                before: float | None = Query(None, ge=0, allow_inf_nan=False),
                before_id: str | None = Query(None, pattern=r"^[a-f0-9]{32}$"),
                state_filter: Literal["pending", "executed", "blocked", "rejected", "expired", "stale", "failed"] | None = Query(None, alias="state")):
        if (before is None) != (before_id is None):
            raise GateError("cursor_requires_time_and_id", 422)
        items = gate.list_actions(limit, before, before_id, state_filter)
        cursor = {"before": items[-1]["created_at"], "before_id": items[-1]["id"]} if len(items) == limit else None
        return {"items": items, "next_cursor": cursor}

    @app.get("/v1/actions/{action_id}")
    def detail(action_id: str, who: Annotated[str, Depends(identity)]):
        item = gate.get(action_id, None if who == "reviewer:owner" else who)
        return item if who == "reviewer:owner" else agent_view(item)

    @app.post("/v1/actions/{action_id}/decision")
    def decide(action_id: str, body: Decision, who: Annotated[str, Depends(reviewer)]):
        return gate.decide(action_id, body, who)

    @app.get("/v1/audit")
    def audit(who: Annotated[str, Depends(reviewer)], action_id: str | None = None,
              after: int = Query(0, ge=0)):
        items = gate.store.audit_events(action_id, after)
        return {"items": items, "next_after": items[-1]["seq"] if items else after}

    @app.get("/v1/audit/verify")
    def verify(who: Annotated[str, Depends(reviewer)]):
        return gate.store.verify_audit()

    @app.get("/v1/metrics")
    def metrics(who: Annotated[str, Depends(reviewer)]):
        return gate.metrics()

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
                items = await asyncio.to_thread(gate.store.audit_events, None, cursor, 100)
                for item in items:
                    cursor = item["seq"]
                    yield f"id: {cursor}\nevent: action\ndata: {json.dumps({'action_id': item['action_id']})}\n\n"
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    @app.get("/")
    def index():
        if not (STATIC / "index.html").exists():
            return JSONResponse({"error": "console_assets_missing", "next_step": "Reinstall the package with bundled static assets."}, status_code=503)
        return FileResponse(STATIC / "index.html")

    app.mount("/assets", ConsoleAssets(directory=STATIC, check_dir=False), name="assets")
    return app
