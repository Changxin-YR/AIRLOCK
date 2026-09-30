from __future__ import annotations

import os
import time
from urllib.parse import urlsplit

import httpx

from airlock.common import DomainError
from airlock.contracts import OperationRequest
from airlock.storage import TERMINAL


class AgentClient:
    """Only Agent capabilities; never loads gateway config or reviewer credentials."""

    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or os.environ.get("AIRLOCK_URL", "http://127.0.0.1:8080")).rstrip(
            "/"
        )
        self.token = token or os.environ.get("AIRLOCK_AGENT_TOKEN", "")
        parsed = urlsplit(self.base_url)
        if not self.token:
            raise ValueError("AIRLOCK_AGENT_TOKEN is required")
        if parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "gateway")
        ):
            raise ValueError("Remote Agent API requires HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
            raise ValueError("AIRLOCK_URL must be a bare origin")

    def _request(self, method: str, path: str, body=None, key: str | None = None) -> dict:
        headers = {"Authorization": "Bearer " + self.token}
        if key:
            headers["Idempotency-Key"] = key
        with httpx.Client(
            base_url=self.base_url, timeout=15, follow_redirects=False, trust_env=False
        ) as client:
            response = client.request(method, path, json=body, headers=headers)
        data = response.json()
        if response.is_error:
            error = data.get("error", {})
            raise DomainError(
                error.get("code", "API_ERROR"),
                error.get("safe_message", "Agent API 请求失败。"),
                response.status_code,
            )
        return data

    def submit(self, request: OperationRequest, idempotency_key: str) -> dict:
        return self._request("POST", "/api/operations", request.model_dump(), idempotency_key)

    @staticmethod
    def validate_id(operation_id: str):
        import re

        if not re.fullmatch(r"[a-f0-9]{32}", operation_id):
            raise DomainError("INVALID_OPERATION", "操作编号无效。")

    def status(self, operation_id: str) -> dict:
        self.validate_id(operation_id)
        return self._request("GET", f"/api/operations/{operation_id}")

    def cancel(self, operation_id: str) -> dict:
        self.validate_id(operation_id)
        return self._request("POST", f"/api/operations/{operation_id}/cancel", {})

    def wait(self, operation_id: str, timeout: int = 310) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.status(operation_id)
            if result["state"] in TERMINAL or result["state"] == "UNKNOWN":
                return result
            time.sleep(min(max(result.get("poll_after_ms", 1000) / 1000, 0.25), 5))
        # Leave the server operation intact; never turn local timeout into permission to retry a new change.
        return self.status(operation_id)
