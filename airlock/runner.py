from __future__ import annotations

from typing import Protocol

import httpx

from airlock.common import DomainError
from airlock.config import ConfigSource, read_policy
from airlock.contracts import AgentPrincipal, OperationRequest, Policy
from airlock.plans import execution_envelope
from airlock.target import SQLiteTarget


class UncertainExecution(Exception):
    """A lost or malformed response is not evidence that an operation did not commit."""


class Runner(Protocol):
    def preview(
        self, request: OperationRequest, principal: AgentPrincipal, policy: Policy
    ) -> dict: ...
    def execute(self, plan: dict) -> dict: ...
    def receipt(self, operation_id: str, plan_digest: str) -> dict | None: ...
    def inspect(self) -> dict: ...


class LocalRunner:
    """For isolated tests and CLI checks only. Production gateway uses HTTPRunner."""

    def __init__(self, target: SQLiteTarget, policy_path: str):
        self.target, self.policy_path = target, policy_path

    def preview(self, request, principal, policy):
        return self.target.preview(request, principal, policy)

    def execute(self, plan):
        return self.target.execute(
            **execution_envelope(plan, self.target.secret), policy=read_policy(self.policy_path)
        )

    def receipt(self, operation_id, plan_digest):
        return self.target.lookup_receipt(operation_id, plan_digest)

    def inspect(self):
        return self.target.inspect(read_policy(self.policy_path))


class HTTPRunner:
    def __init__(self, source: ConfigSource):
        self.source = source

    def _call(self, method: str, path: str, *, body=None, params=None, uncertain=False):
        config = self.source.read()
        try:
            with httpx.Client(
                base_url=config.runner_url, timeout=8, trust_env=False, follow_redirects=False
            ) as client:
                response = client.request(
                    method,
                    path,
                    json=body,
                    params=params,
                    headers={"Authorization": f"Bearer {config.runner_secret}"},
                )
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            if uncertain:
                raise UncertainExecution("runner response unavailable") from exc
            raise DomainError("RUNNER_UNAVAILABLE", "执行器暂不可用。", 503, True) from exc
        if response.is_error:
            error = data.get("error", {}) if isinstance(data, dict) else {}
            known = {
                "TARGET_BUSY",
                "TARGET_UNAVAILABLE",
                "TARGET_STALE",
                "PLAN_EXPIRED",
                "POLICY_CHANGED",
                "SCHEMA_UNSUPPORTED",
                "INVALID_PLAN",
                "INVALID_PERMIT",
                "EFFECT_MISMATCH",
                "EXECUTION_BLOCKED",
            }
            if uncertain and error.get("code") not in known:
                raise UncertainExecution("runner execution outcome unknown")
            raise DomainError(
                error.get("code", "RUNNER_UNAVAILABLE"),
                error.get("safe_message", "执行器暂不可用。"),
                response.status_code,
                error.get("retryable", False),
            )
        if not isinstance(data, dict):
            if uncertain:
                raise UncertainExecution("invalid receipt shape")
            raise DomainError("RUNNER_UNAVAILABLE", "执行器响应无效。", 503)
        return data

    def preview(self, request, principal, policy):
        return self._call(
            "POST",
            "/internal/preview",
            body={"request": request.model_dump(), "principal": principal.model_dump()},
        )

    def execute(self, plan):
        return self._call(
            "POST",
            "/internal/execute",
            uncertain=True,
            body=execution_envelope(plan, self.source.read().runner_secret),
        )

    def receipt(self, operation_id, plan_digest):
        return self._call(
            "GET", f"/internal/receipts/{operation_id}", params={"plan_digest": plan_digest}
        )["receipt"]

    def inspect(self):
        return self._call("GET", "/internal/resource")
