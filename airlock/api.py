from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from sqlalchemy import func, select
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.staticfiles import StaticFiles

from airlock.auth import COOKIE, Auth
from airlock.common import DomainError, canonical, now_ms
from airlock.config import ConfigSource, gateway_source
from airlock.contracts import (
    DecisionRequest,
    DemoRequest,
    LoginRequest,
    OperationRequest,
    TelemetryRequest,
)
from airlock.http_security import SafetyMiddleware, install_handlers
from airlock.runner import HTTPRunner, Runner
from airlock.service import ReviewService
from airlock.storage import Store, audit_events, operations, telemetry, views

log = logging.getLogger("airlock.worker")


def demo_request(scenario: str) -> OperationRequest:
    base = {
        "tool": "db.update_rows",
        "intent": "为已过期测试客户更新标签",
        "run_id": "演示 · 数据清理",
        "where": [
            {"field": "is_test", "op": "eq", "value": True},
            {"field": "id", "op": "lte", "value": 6},
        ],
        "changes": {"tag": "已核验"},
    }
    if scenario == "read":
        base.update(tool="db.query_rows", changes={}, intent="查询演示客户，只返回授权字段")
    elif scenario == "tag":
        base.update(
            where=[{"field": "id", "op": "eq", "value": 12}],
            changes={"tag": "已核验"},
            intent="更新单条测试记录标签",
        )
    elif scenario == "delete":
        base.update(tool="db.delete_rows", changes={}, intent="删除过期测试客户及其关联备注")
    elif scenario == "blocked":
        base.update(
            tool="db.delete_rows",
            changes={},
            where=[],
            intent="模拟错误提议：清空全部客户（应被阻止）",
        )
    return OperationRequest.model_validate(base)


def create_app(config_path: str | None = None, runner: Runner | None = None) -> FastAPI:
    source = ConfigSource(config_path) if config_path else gateway_source()
    config = source.read()
    store = Store(config.meta_path)
    store.migrate()
    service = ReviewService(store, source, runner or HTTPRunner(source))
    auth = Auth(store, source)
    stop = threading.Event()

    def work():
        while not stop.is_set():
            try:
                processed = service.tick()
            except Exception as exc:
                # Do not log request bodies, passwords, credentials or internal exception text.
                log.error("worker tick failed: %s", type(exc).__name__)
                processed = False
            stop.wait(0.02 if processed else 0.2)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        thread = None
        if source.read().worker_enabled:
            thread = threading.Thread(target=work, name="airlock-durable-worker", daemon=True)
            thread.start()
        yield
        stop.set()
        if thread:
            await asyncio.to_thread(thread.join, 10)
        store.engine.dispose()

    app = FastAPI(
        title="AIRLOCK · Agent Change Review",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.store, app.state.service, app.state.source, app.state.auth = (
        store,
        service,
        source,
        auth,
    )
    app.add_middleware(SafetyMiddleware, source=source)
    install_handlers(app)

    def human(request: Request):
        return auth.human(request.cookies.get(COOKIE))

    def human_write(request: Request, session: dict = Depends(human)):
        auth.csrf(session, request.headers.get("x-csrf-token"))
        return session

    def agent(authorization: str = Header(default="")):
        prefix, _, token = authorization.partition(" ")
        if prefix != "Bearer" or not token or len(token) > 256:
            raise DomainError("UNAUTHENTICATED", "缺少服务身份凭据。", 401)
        return source.authenticate_agent(token)

    def session_payload(session):
        return {
            "username": session["username"],
            "csrf_token": session["csrf"],
            "expires_at": session["expires_at"],
            "demo_enabled": source.read().demo_enabled,
        }

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "0.1.0"}

    @app.post("/api/session/login")
    def login(body: LoginRequest, request: Request, response: Response):
        token, session = auth.login(
            body.username, body.password, request.client.host if request.client else "unknown"
        )
        response.set_cookie(
            COOKIE,
            token,
            max_age=source.read().session_seconds,
            httponly=True,
            secure=source.read().secure_cookie,
            samesite="strict",
            path="/",
        )
        return session_payload(session)

    @app.get("/api/session")
    def session_current(session=Depends(human)):
        return session_payload(session)

    @app.post("/api/session/logout")
    def logout(response: Response, session=Depends(human_write)):
        auth.logout(session)
        response.delete_cookie(
            COOKIE, path="/", secure=source.read().secure_cookie, httponly=True, samesite="strict"
        )
        return {"logged_out": True}

    @app.post("/api/operations", status_code=202)
    def submit(
        body: OperationRequest, principal=Depends(agent), idempotency_key: str = Header(default="")
    ):
        return service.submit(principal, body, idempotency_key)

    @app.get("/api/operations/{operation_id}")
    def operation_get(operation_id: str, principal=Depends(agent)):
        return service.get_for_agent(principal, operation_id)

    @app.post("/api/operations/{operation_id}/cancel")
    def operation_cancel(operation_id: str, principal=Depends(agent)):
        return service.cancel(operation_id, principal.id)

    @app.get("/api/reviews")
    def reviews(
        state: str | None = Query(default=None, max_length=32),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        session=Depends(human),
    ):
        return service.list_reviews(state, limit, offset)

    @app.get("/api/reviews/{operation_id}")
    def review(operation_id: str, read_only: bool = False, session=Depends(human)):
        return service.get_review(operation_id, session, read_only)

    @app.get("/api/reviews/{operation_id}/views/{view_id}")
    def historical_view(operation_id: str, view_id: str, session=Depends(human)):
        return service.historical_view(operation_id, view_id)

    @app.post("/api/reviews/{operation_id}/decision")
    def decision(operation_id: str, body: DecisionRequest, session=Depends(human_write)):
        return service.decide_review(operation_id, body, session)

    @app.post("/api/reviews/{operation_id}/cancel")
    def review_cancel(operation_id: str, session=Depends(human_write)):
        return service.cancel(operation_id)

    @app.post("/api/reviews/{operation_id}/reconcile")
    def reconcile(operation_id: str, session=Depends(human_write)):
        return service.request_reconciliation(operation_id)

    @app.get("/api/reviews/{operation_id}/audit")
    def audit(operation_id: str, session=Depends(human)):
        service.human_operation(operation_id)
        return store.audit_log(operation_id)

    @app.post("/api/reviews/{operation_id}/telemetry", status_code=202)
    def measure(operation_id: str, body: TelemetryRequest, session=Depends(human_write)):
        service.human_operation(operation_id)
        with store.transaction() as conn:
            view = (
                conn.execute(
                    select(views).where(
                        views.c.id == body.view_id,
                        views.c.operation_id == operation_id,
                        views.c.session_hash == session["token_hash"],
                    )
                )
                .mappings()
                .first()
            )
            if not view:
                raise DomainError("VIEW_MISMATCH", "此展示会话不存在。", 409)
            count = conn.execute(
                select(func.count())
                .select_from(telemetry)
                .where(telemetry.c.view_id == body.view_id)
            ).scalar_one()
            if count >= 100:
                raise DomainError("TELEMETRY_LIMIT", "此展示会话的记录已达上限。", 429)
            conn.execute(
                telemetry.insert().values(
                    operation_id=operation_id, **body.model_dump(), created_at=now_ms()
                )
            )
        return {"accepted": True, "trusted_for_security": False}

    @app.get("/api/metrics")
    def metrics(session=Depends(human)):
        return service.metrics()

    @app.get("/api/resource")
    def resource(session=Depends(human)):
        if "demo" not in source.read().reviewer.resources:
            raise DomainError("FORBIDDEN", "此资源不可访问。", 403)
        return service.runner.inspect()

    @app.post("/api/demo", status_code=202)
    def demo(
        body: DemoRequest, session=Depends(human_write), idempotency_key: str = Header(default="")
    ):
        if not source.read().demo_enabled:
            raise DomainError("DEMO_DISABLED", "当前部署未启用合成演示。", 403)
        if "demo" not in source.read().reviewer.resources:
            raise DomainError("FORBIDDEN", "此资源不可访问。", 403)
        return service.submit(
            source.principal("agent-demo"), demo_request(body.scenario), idempotency_key
        )

    @app.get("/api/events")
    async def events(
        request: Request, last_event_id: str | None = Header(default=None), session=Depends(human)
    ):
        if last_event_id is not None and (not last_event_id.isdigit() or len(last_event_id) > 18):
            raise DomainError("INVALID_CURSOR", "事件游标无效。")
        cursor = int(last_event_id or "0")
        token = request.cookies.get(COOKIE)

        def batch(after):
            current = auth.human(token)
            with store.read() as conn:
                rows = (
                    conn.execute(
                        select(
                            audit_events.c.id,
                            audit_events.c.operation_id,
                            audit_events.c.kind,
                            operations.c.version,
                            operations.c.state,
                        )
                        .join(operations, audit_events.c.operation_id == operations.c.id)
                        .where(
                            audit_events.c.id > after,
                            operations.c.resource_id.in_(source.read().reviewer.resources),
                        )
                        .order_by(audit_events.c.id)
                        .limit(100)
                    )
                    .mappings()
                    .all()
                )
            return current, [dict(r) for r in rows]

        async def stream():
            nonlocal cursor
            yield "retry: 2000\n\n"
            while not await request.is_disconnected():
                try:
                    _, rows = await asyncio.to_thread(batch, cursor)
                except DomainError:
                    yield "event: session_expired\ndata: {}\n\n"
                    break
                for row in rows:
                    cursor = row["id"]
                    yield f"id: {cursor}\nevent: change\ndata: {canonical(row)}\n\n"
                if not rows:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    dist = Path(config.web_dist).resolve()
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/")
    def index():
        if (dist / "index.html").is_file():
            return FileResponse(dist / "index.html")
        return JSONResponse(
            {"message": "前端尚未构建；执行 npm ci && npm run build（apps/web）。"}, status_code=503
        )

    return app
