from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
import threading
import time
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .auth import Auth
from .common import AirlockError, canonical
from .config import Settings
from .contracts import ApprovalDecision, Login, ToolRequest, VisibilityTelemetry
from .demo import SCENARIOS, scenario_request
from .http_security import HttpSafety
from .runner import HttpRunner, Runner
from .service import Service
from .storage import Store, operations, principals

LOG = logging.getLogger("airlock.worker")
COOKIE = "airlock_session"


def create_app(settings: Settings | None = None, *, store: Store | None = None,
               runner: Runner | None = None, service: Service | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if store is None and not settings.meta_path.is_file():
        raise RuntimeError("Metadata is not initialized. Run python -m airlock.cli init first.")
    store = store or Store(settings.meta_path)
    store.verify_schema()
    runner = runner or HttpRunner(settings.runner_url, settings.runner_secret)
    service = service or Service(store, runner, settings)
    auth = Auth(store)
    stop = threading.Event()
    health = {"last_tick":None,"last_error":None}

    def worker_loop():
        while not stop.is_set():
            try:
                worked = service.step()
                health.update(last_tick=time.time(),last_error=None)
            except Exception as exc:
                worked = False
                health.update(last_tick=time.time(),last_error=type(exc).__name__)
                LOG.exception("Persistent worker iteration failed; leases remain recoverable")
            if not worked: stop.wait(settings.worker_interval)

    @asynccontextmanager
    async def lifespan(app):
        service.policy()  # Invalid configuration fails startup; no fallback policy.
        worker = threading.Thread(target=worker_loop, name="airlock-worker", daemon=True)
        if settings.worker_enabled: worker.start()
        yield
        stop.set()
        if worker.is_alive(): await asyncio.to_thread(worker.join, 12)
        if hasattr(runner,"close"): runner.close()

    app = FastAPI(title="AIRLOCK · Agent Change Review",version=__version__,lifespan=lifespan,
                  docs_url="/docs" if settings.demo_enabled else None,redoc_url=None)
    app.state.service, app.state.auth = service, auth
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=list(settings.allowed_hosts))
    app.add_middleware(HttpSafety,max_body=32*1024)

    @app.exception_handler(AirlockError)
    async def domain_error(_,exc): return JSONResponse({"error":exc.public()},status_code=exc.status)
    @app.exception_handler(RequestValidationError)
    async def validation_error(_,exc):
        return JSONResponse({"error":{"code":"VALIDATION_ERROR","safe_message":"参数不符合受支持契约。","retryable":False},
            "fields":[{"path":".".join(map(str,e['loc'])),"type":e['type']} for e in exc.errors()]},status_code=422)

    def check_origin(request: Request):
        if request.headers.get("origin") not in settings.origins:
            raise AirlockError("ORIGIN_REJECTED","此来源不能提交审批会话请求。",403)

    def human(request: Request):
        if request.headers.get("authorization"):
            raise AirlockError("HUMAN_REQUIRED","Agent 凭据不能用于人工审批。",403)
        unsafe = request.method not in {"GET","HEAD"}
        if unsafe: check_origin(request)
        return auth.session(request.cookies.get(COOKIE),csrf=request.headers.get("x-csrf-token"),require_csrf=unsafe)

    def agent(request: Request):
        principal = auth.agent(request.headers.get("authorization"))
        auth.rate_limit("agent-http:"+principal["id"],limit=180,window=60)
        return principal

    def actor(request: Request):
        return agent(request) if request.headers.get("authorization") else human(request)

    @app.get("/healthz")
    def healthz():
        return {"status":"ok","version":__version__,"worker_enabled":settings.worker_enabled,
                "worker_error":health["last_error"]}

    @app.post("/api/session")
    def login(body: Login, request: Request):
        check_origin(request)
        cookie, result = auth.login(body.username,body.password,request.client.host if request.client else "unknown")
        response = JSONResponse(result)
        response.set_cookie(COOKIE,cookie,httponly=True,secure=settings.secure_cookie,samesite="strict",
                            max_age=auth.session_ttl,path="/")
        return response

    @app.get("/api/session")
    def session(principal=Depends(human)):
        return {"username":principal["username"],"scope":principal["scope"],"csrf":principal["csrf"]}

    @app.post("/api/session/logout")
    def logout(request: Request,principal=Depends(human)):
        auth.logout(request.cookies[COOKIE])
        response=JSONResponse({"logged_out":True}); response.delete_cookie(COOKIE,path="/")
        return response

    @app.post("/api/operations",status_code=202)
    def submit(body: ToolRequest, principal=Depends(agent),idempotency_key: str = Header()):
        return service.submit(principal,body,idempotency_key)

    @app.get("/api/operations")
    @app.get("/api/reviews")
    def list_operations(principal=Depends(actor),state: str | None = Query(default=None,max_length=30),
                        offset: int=Query(default=0,ge=0,le=2000),limit: int=Query(default=30,ge=1,le=50)):
        return service.list(principal,state=state,offset=offset,limit=limit)

    @app.get("/api/operations/{op_id}")
    def get_operation(op_id: str,principal=Depends(actor)):
        return service.get(op_id,principal,provide_view=principal["kind"]=="human")

    @app.post("/api/reviews/{op_id}/decision")
    def decide(op_id: str,body: ApprovalDecision,principal=Depends(human)):
        return service.decide(op_id,principal,body)

    @app.post("/api/operations/{op_id}/cancel")
    def cancel(op_id: str,principal=Depends(actor)):
        return service.cancel(op_id,principal)

    @app.post("/api/operations/{op_id}/reconcile")
    def reconcile(op_id: str,principal=Depends(human)):
        return service.reconcile(op_id,principal)

    @app.get("/api/reviews/{op_id}/audit")
    def audit(op_id: str,principal=Depends(human)):
        return service.audit(op_id,principal)

    @app.post("/api/reviews/{op_id}/telemetry",status_code=202)
    def telemetry(op_id: str,body: VisibilityTelemetry,principal=Depends(human)):
        service.record_telemetry(op_id,principal,body.model_dump()); return {"accepted":True,"trusted_for_security":False}

    @app.get("/api/events/poll")
    def event_poll(principal=Depends(actor),after: int=Query(default=0,ge=0,le=2**63-1)):
        return {"items":service.events(principal,after)}

    @app.get("/api/events")
    async def event_stream(request: Request,principal=Depends(human),after: int=Query(default=0,ge=0,le=2**63-1)):
        raw=request.headers.get("last-event-id")
        if raw:
            if not raw.isdecimal() or len(raw)>19 or int(raw)>2**63-1:
                raise AirlockError("INVALID_CURSOR","事件恢复游标无效。",422)
            after=max(after,int(raw))
        cookie=request.cookies.get(COOKIE)
        async def stream():
            cursor=after
            yield 'event: ready\ndata: {"connected":true}\n\n'
            while not await request.is_disconnected():
                try:
                    current=await asyncio.to_thread(auth.session,cookie)
                except AirlockError:
                    yield 'event: auth_expired\ndata: {}\n\n'; return
                events=await asyncio.to_thread(service.events,current,cursor)
                for item in events:
                    cursor=item['seq']
                    yield f"id: {cursor}\nevent: change\ndata: {canonical(item)}\n\n"
                if not events: yield ': heartbeat\n\n'
                await asyncio.sleep(1)
        return StreamingResponse(stream(),media_type="text/event-stream",headers={"X-Accel-Buffering":"no"})

    @app.get("/api/overview")
    def overview(principal=Depends(human)):
        with store.engine.connect() as conn:
            counts=conn.execute(select(operations.c.state,func.count()).where(
                operations.c.scope==principal['scope']).group_by(operations.c.state)).all()
        return {"states":dict(counts),"demo_enabled":settings.demo_enabled,
                "capabilities":{"adapter":"sqlite-structured-v1","resource":"demo-crm","max_business_rows":10000,
                    "coverage":"exact_on_snapshot","raw_sql":False,"automatic_rollback":False,
                    "model_agent":"external_client_not_verified_here","mcp_transport":"stdio / application-level pending"},
                "worker":health}

    @app.get("/api/policy")
    def policy(principal=Depends(human)):
        current=service.policy(); return {"policy":current.model_dump(),"version":current.version,"editable":False}

    @app.get("/api/demo/scenarios")
    def scenarios(principal=Depends(human)):
        return {"enabled":settings.demo_enabled,"source":"synthetic_scripted_agent","items":[
            {"id":key,"title":item['title'],"description":item['description'],"expected":item['expected']}
            for key,item in SCENARIOS.items()]}

    @app.post("/api/demo/scenarios/{name}",status_code=202)
    def demo(name: str,principal=Depends(human),idempotency_key: str=Header()):
        if not settings.demo_enabled or name not in SCENARIOS:
            raise AirlockError("NOT_FOUND","演示入口未启用或场景不存在。",404)
        with store.engine.connect() as conn:
            demo_agent=store.row(conn,principals,principals.c.id=='agent')
        if not demo_agent or demo_agent['scope']!=principal['scope']:
            raise AirlockError("NOT_FOUND","此账号没有可用的演示身份。",404)
        return service.submit(demo_agent,scenario_request(name),idempotency_key)

    dist=settings.dist_path.resolve()
    if (dist/'assets').is_dir(): app.mount('/assets',StaticFiles(directory=dist/'assets'),name='assets')
    @app.get("/")
    def index():
        if (dist/'index.html').is_file(): return FileResponse(dist/'index.html')
        return JSONResponse({"message":"前端尚未构建；在 apps/web 运行 npm ci && npm run build。","api":"/healthz"},status_code=503)
    return app
