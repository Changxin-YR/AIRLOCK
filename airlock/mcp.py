"""Minimal stdio MCP tools adapter; asynchronous receipts, NOT a transparent proxy.

The adapter only knows the agent token. It never opens the target database.
Approval is exclusively performed over the separately authenticated reviewer API.
"""
from __future__ import annotations
import json
import os
import re
import sys
from urllib.parse import urlparse
import httpx
from pydantic import ValidationError
from .models import Invocation, canonical

VERSIONS = {"2025-11-25", "2025-06-18"}
TOOLS = [
    {"name": "sql_execute", "description": "Submit bounded SQL to Airlock. pending is NOT execution. "
     "Poll action_status after external human review. Never attempt to approve a request.",
     "inputSchema": {"type": "object", "properties": {
         "sql": {"type": "string", "maxLength": 4000},
         "parameters": {"type": "array", "items": {"type": ["string", "number", "null"]}, "maxItems": 50},
         "idempotency_key": {"type": "string", "minLength": 8, "maxLength": 128}},
         "required": ["sql", "idempotency_key"], "additionalProperties": False}},
    {"name": "action_status", "description": "Check the status of a previously submitted action.",
     "inputSchema": {"type": "object", "properties": {"action_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}},
                     "required": ["action_id"], "additionalProperties": False}},
]


class Bridge:
    def __init__(self, client, token: str):
        self.client, self.token = client, token
        self.initialized, self.ready = False, False

    @staticmethod
    def error(identifier, code: int, message: str):
        return {"jsonrpc": "2.0", "id": identifier, "error": {"code": code, "message": message}}

    def handle(self, request):
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
            return self.error(None, -32600, "Invalid request")
        identifier, method = request.get("id"), request["method"]
        if "id" not in request:
            if method == "notifications/initialized" and self.initialized:
                self.ready = True
            return None
        if type(identifier) not in (int, str):
            return self.error(None, -32600, "Invalid request id")
        params = request.get("params", {})
        if not isinstance(params, dict):
            return self.error(identifier, -32602, "Invalid parameters")
        if method == "initialize":
            version = params.get("protocolVersion")
            if not isinstance(version, str) or not isinstance(params.get("capabilities"), dict) or not isinstance(params.get("clientInfo"), dict):
                return self.error(identifier, -32602, "Invalid initialization")
            self.initialized = True
            result = {"protocolVersion": version if version in VERSIONS else "2025-11-25",
                      "serverInfo": {"name": "airlock", "version": "0.1.0"},
                      "capabilities": {"tools": {"listChanged": False}},
                      "instructions": "External review is required for writes. pending means NOT executed."}
        elif method == "ping":
            result = {}
        elif not self.ready:
            return self.error(identifier, -32002, "Initialize first")
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            try:
                args = params.get("arguments", {})
                headers = {"Authorization": "Bearer " + self.token}
                if params.get("name") == "sql_execute":
                    if not isinstance(args, dict) or set(args) - {"sql", "parameters", "idempotency_key"}:
                        raise ValueError("invalid tool arguments")
                    call = Invocation.model_validate(args)
                    response = self.client.post("/v1/actions", json=call.model_dump(), headers=headers)
                elif params.get("name") == "action_status":
                    if not isinstance(args, dict) or set(args) != {"action_id"} or not isinstance(args["action_id"], str) or not re.fullmatch(r"[a-f0-9]{32}", args["action_id"]):
                        raise ValueError("invalid action id")
                    response = self.client.get("/v1/actions/" + args["action_id"], headers=headers)
                else:
                    return self.error(identifier, -32602, "Unknown tool")
                payload = response.json()
                failed = response.status_code >= 400 or payload.get("state") in {"blocked", "failed", "rejected", "expired", "stale"}
                result = {"content": [{"type": "text", "text": canonical(payload)}],
                          "structuredContent": payload, "isError": failed}
            except (ValueError, ValidationError):
                return self.error(identifier, -32602, "Invalid tool arguments")
            except httpx.HTTPError:
                result = {"content": [{"type": "text", "text": "Airlock unavailable. Do not assume execution. "
                           "Retry ONLY with the SAME idempotency key or query action status."}], "isError": True}
        else:
            return self.error(identifier, -32601, "Method not found")
        return {"jsonrpc": "2.0", "id": identifier, "result": result}


def main():
    url = os.getenv("AIRLOCK_URL", "http://127.0.0.1:8000")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}):
        raise SystemExit("Use HTTPS, except for localhost demonstration.")
    with httpx.Client(base_url=url, timeout=10, trust_env=False, follow_redirects=False) as client:
        bridge = Bridge(client, os.environ["AIRLOCK_AGENT_TOKEN"])
        while True:
            line = sys.stdin.readline(16385)
            if not line:
                break
            if len(line.encode("utf-8")) > 16384:
                print(canonical(bridge.error(None, -32700, "Message too large; closing transport")), flush=True)
                break
            try:
                result = bridge.handle(json.loads(line))
            except (ValueError, json.JSONDecodeError):
                result = bridge.error(None, -32700, "Parse error or oversized message")
            if result is not None:
                print(canonical(result), flush=True)


if __name__ == "__main__":
    main()
