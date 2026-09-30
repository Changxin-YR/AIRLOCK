from __future__ import annotations

import hmac
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, Query

from airlock.common import DomainError, strict_json
from airlock.config import RunnerConfig, read_policy
from airlock.contracts import ExecuteEnvelope, PreviewRequest
from airlock.http_security import SafetyMiddleware, install_handlers
from airlock.target import SQLiteTarget


def create_runner_app(config_path: str | None = None) -> FastAPI:
    path = Path(
        config_path or os.environ.get("AIRLOCK_RUNNER_CONFIG", ".airlock/runner/config.json")
    )

    def config():
        return RunnerConfig.model_validate(strict_json(path.read_bytes()))

    initial = config()
    target = SQLiteTarget(initial.target_path, initial.runner_secret)

    def service_identity(authorization: str = Header(default="")):
        prefix, _, token = authorization.partition(" ")
        if prefix != "Bearer" or not hmac.compare_digest(
            token.encode(), config().runner_secret.encode()
        ):
            raise DomainError("UNAUTHENTICATED", "执行器仅接受受信网关。", 401)

    app = FastAPI(
        title="AIRLOCK private runner",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        dependencies=[Depends(service_identity)],
    )
    app.add_middleware(SafetyMiddleware, max_body=16_000_000)
    install_handlers(app)

    @app.post("/internal/preview")
    def preview(body: PreviewRequest):
        return target.preview(body.request, body.principal, read_policy(config().policy_path))

    @app.post("/internal/execute")
    def execute(body: ExecuteEnvelope):
        return target.execute(
            body.plan, body.permit, body.signature, read_policy(config().policy_path)
        )

    @app.get("/internal/receipts/{operation_id}")
    def receipt(operation_id: str, plan_digest: str = Query(pattern=r"^[0-9a-f]{64}$")):
        if len(operation_id) != 32:
            raise DomainError("INVALID_OPERATION", "无效操作编号。")
        return {"receipt": target.lookup_receipt(operation_id, plan_digest)}

    @app.get("/internal/resource")
    def resource():
        return target.inspect(read_policy(config().policy_path))

    return app
