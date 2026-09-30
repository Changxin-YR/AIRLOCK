from __future__ import annotations

import uuid
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from airlock.common import DomainError, strict_json


class SafetyMiddleware:
    """Bound JSON before parsing; reject ambiguous encodings and add response guards."""

    def __init__(self, app, source=None, max_body: int = 65536):
        self.app, self.source, self.max_body = app, source, max_body

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid.uuid4().hex
        headers = {k.lower(): v for k, v in scope["headers"]}
        secure = False
        try:
            if self.source:
                config = self.source.read()
                secure = config.secure_cookie
                host = headers.get(b"host", b"").decode("ascii", errors="replace")
                public_host = host.lower() == urlsplit(config.public_origin).netloc.lower()
                agent_path = scope["path"] == "/api/operations" or scope["path"].startswith(
                    "/api/operations/"
                )
                internal_host = (
                    config.internal_agent_host is not None
                    and host.lower() == config.internal_agent_host.lower()
                )
                if not public_host and not (internal_host and agent_path):
                    raise DomainError("INVALID_HOST", "请求主机不匹配。", 400)
                if scope["method"] not in ("GET", "HEAD", "OPTIONS") and scope["path"].startswith(
                    "/api/"
                ):
                    # Agent-only endpoints use bearer credentials, never browser cookies.
                    agent_route = scope["path"] == "/api/operations" or scope["path"].startswith(
                        "/api/operations/"
                    )
                    if (
                        not agent_route
                        and headers.get(b"origin", b"").decode() != config.public_origin
                    ):
                        raise DomainError("INVALID_ORIGIN", "请求来源不匹配。", 403)
            if scope["method"] in ("POST", "PUT", "PATCH"):
                content_type = (
                    headers.get(b"content-type", b"").decode().split(";", 1)[0].strip().lower()
                )
                if content_type != "application/json":
                    raise DomainError("JSON_REQUIRED", "仅接受 application/json 请求。", 415)
                chunks, size = [], 0
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    size += len(chunk)
                    if size > self.max_body:
                        raise DomainError("BODY_TOO_LARGE", "请求超过大小限制。", 413)
                    chunks.append(chunk)
                    if not message.get("more_body", False):
                        break
                body = b"".join(chunks)
                strict_json(body)
                consumed = False

                async def replacement_receive():
                    nonlocal consumed
                    if not consumed:
                        consumed = True
                        return {"type": "http.request", "body": body, "more_body": False}
                    return await receive()

                receiver = replacement_receive
            else:
                receiver = receive
        except DomainError as exc:
            response = JSONResponse(
                {"error": exc.public(), "request_id": request_id}, status_code=exc.status
            )
            return await response(scope, receive, send)

        async def guarded_send(message):
            if message["type"] == "http.response.start":
                extra = [
                    (b"x-request-id", request_id.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                    (
                        b"content-security-policy",
                        b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                    ),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                ]
                if scope["path"].startswith(("/api", "/internal")):
                    extra.append((b"cache-control", b"no-store"))
                if secure:
                    extra.append((b"strict-transport-security", b"max-age=31536000"))
                message["headers"] = list(message.get("headers", [])) + extra
            await send(message)

        return await self.app(scope, receiver, guarded_send)


def install_handlers(app):
    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        return JSONResponse({"error": exc.public()}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Do not echo input values: login failures must never reflect passwords.
        return JSONResponse(
            {
                "error": {
                    "code": "INVALID_REQUEST",
                    "safe_message": "请求字段或类型不符合接口契约。",
                    "retryable": False,
                },
                "fields": [".".join(str(p) for p in item["loc"]) for item in exc.errors()],
            },
            status_code=422,
        )
