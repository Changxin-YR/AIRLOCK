from __future__ import annotations
import hmac
import os
from pathlib import Path
from typing import Annotated, Any
from fastapi import Depends, FastAPI, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field, StrictStr
from .common import AirlockError
from .config import required_secret
from .contracts import StrictModel, ToolRequest
from .http_security import HttpSafety
from .target import TargetStore

class PreviewCall(StrictModel):
    request: ToolRequest
    scope: Annotated[StrictStr, Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")]

class ExecutionCall(StrictModel):
    plan: dict[str, Any]
    permit: dict[str, Any]
    signature: Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{64}$")]

class ReceiptCall(StrictModel):
    operation_id: Annotated[StrictStr, Field(min_length=1,max_length=80)]
    plan_digest: Annotated[StrictStr, Field(pattern=r"^[a-f0-9]{64}$")]


def create_app(target: TargetStore | None = None, runner_secret: str | None = None) -> FastAPI:
    target = target or TargetStore(Path(os.environ.get("AIRLOCK_TARGET_DB", "runtime/runner/target.db")),
                                   required_secret("AIRLOCK_EXECUTION_SECRET"))
    secret = runner_secret or required_secret("AIRLOCK_RUNNER_SECRET")
    app = FastAPI(title="AIRLOCK private executor", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(HttpSafety, max_body=32*1024*1024)

    def private(authorization: str | None = Header(default=None)):
        if not authorization or not hmac.compare_digest(authorization.encode("utf-8"), ("Bearer "+secret).encode("utf-8")):
            raise AirlockError("RUNNER_AUTH_REQUIRED", "私有执行入口拒绝此身份。", 401)

    @app.exception_handler(AirlockError)
    async def known(_, exc): return JSONResponse({"error": exc.public()}, status_code=exc.status)
    @app.exception_handler(RequestValidationError)
    async def invalid(_, exc): return JSONResponse({"error":{"code":"VALIDATION_ERROR","safe_message":"执行参数不符合契约。"}},status_code=422)
    @app.get("/healthz")
    def health(): return {"status":"ok","role":"executor"}
    @app.post("/internal/preview",dependencies=[Depends(private)])
    def preview(body: PreviewCall): return target.preview(body.request.model_dump(mode="json"), body.scope)
    @app.post("/internal/execute",dependencies=[Depends(private)])
    def execute(body: ExecutionCall): return target.execute_once(body.model_dump(mode="json"))
    @app.post("/internal/receipt",dependencies=[Depends(private)])
    def receipt(body: ReceiptCall): return {"receipt":target.lookup_receipt(body.operation_id,body.plan_digest)}
    return app
