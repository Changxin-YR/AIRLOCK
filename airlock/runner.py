"""Transport to the private executor. Agent adapters do not import target.py."""
from __future__ import annotations

from typing import Protocol
import httpx
from .common import AirlockError
from .target import TargetStore


class Runner(Protocol):
    def preview(self, request: dict, scope: str) -> dict: ...
    def execute_once(self, envelope: dict) -> dict: ...
    def lookup_receipt(self, operation_id: str, plan_digest: str) -> dict | None: ...


class LocalRunner:
    """Explicit in-process integration fixture; never selected by production settings."""
    def __init__(self, target: TargetStore): self.target = target
    def preview(self, request, scope): return self.target.preview(request, scope)
    def execute_once(self, envelope): return self.target.execute_once(envelope)
    def lookup_receipt(self, operation_id, plan_digest): return self.target.lookup_receipt(operation_id, plan_digest)


class HttpRunner:
    def __init__(self, url: str, secret: str):
        self.client = httpx.Client(base_url=url, headers={"Authorization": f"Bearer {secret}"},
                                   timeout=10, follow_redirects=False, trust_env=False)

    def call(self, path: str, payload: dict) -> dict:
        response = self.client.post(path, json=payload)
        if response.status_code >= 400:
            try:
                error = response.json()["error"]
                code, message = error["code"], error["safe_message"]
            except (ValueError, KeyError, TypeError):
                code, message = "RUNNER_UNAVAILABLE", "受控执行器暂时无法返回有效结果。"
            raise AirlockError(code, message, response.status_code)
        return response.json()

    def preview(self, request: dict, scope: str) -> dict:
        return self.call("/internal/preview", {"request": request, "scope": scope})

    def execute_once(self, envelope: dict) -> dict:
        return self.call("/internal/execute", envelope)

    def lookup_receipt(self, operation_id: str, plan_digest: str) -> dict | None:
        return self.call("/internal/receipt", {"operation_id": operation_id, "plan_digest": plan_digest})["receipt"]

    def close(self):
        self.client.close()
