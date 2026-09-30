"""Bounded JSON ingress and response security headers, shared by both services."""
from __future__ import annotations
import uuid
from starlette.responses import JSONResponse
from .common import canonical, strict_json


class HttpSafety:
    def __init__(self, app, *, max_body: int = 32*1024):
        self.app, self.max_body = app, max_body

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = scope.get("headers", [])
        sensitive = {b"authorization", b"cookie", b"origin", b"content-length", b"idempotency-key", b"x-csrf-token"}
        seen = set()
        request_id = str(uuid.uuid4())

        async def secured_send(message):
            if message["type"] == "http.response.start":
                extra = [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"), (b"x-request-id", request_id.encode()),
                    (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()")]
                if scope["path"].startswith(("/api", "/internal")):
                    extra.append((b"cache-control", b"no-store"))
                message = message | {"headers": list(message.get("headers", [])) + extra}
            await send(message)

        async def reject(code, status, text):
            await JSONResponse({"error": {"code": code, "safe_message": text, "retryable": False}}, status_code=status)(scope, receive, secured_send)

        for name, _ in headers:
            name = name.lower()
            if name in sensitive:
                if name in seen:
                    return await reject("AMBIGUOUS_HEADERS", 400, "拒绝重复的安全相关请求头。")
                seen.add(name)
        if scope["method"] in {"POST", "PUT", "PATCH"}:
            chunks, size = [], 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect": return
                chunk = message.get("body", b"")
                size += len(chunk)
                if size > self.max_body:
                    return await reject("BODY_TOO_LARGE", 413, "请求超过大小限制。")
                chunks.append(chunk)
                if not message.get("more_body", False): break
            data = b"".join(chunks)
            if data:
                content_type = dict(headers).get(b"content-type", b"").split(b";")[0].strip().lower()
                if content_type != b"application/json":
                    return await reject("JSON_REQUIRED", 415, "此入口只接收 JSON。")
                try:
                    parsed = strict_json(data)
                    canonical(parsed).encode("utf-8")
                except (ValueError, UnicodeError, RecursionError, TypeError):
                    return await reject("INVALID_JSON", 400, "JSON 存在重复键、无效编码或不支持的值。")
            consumed = False
            original_receive = receive
            async def replay():
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {"type": "http.request", "body": data, "more_body": False}
                return await original_receive()
            receive = replay
        await self.app(scope, receive, secured_send)
