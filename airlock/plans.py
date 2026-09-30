from __future__ import annotations

import hmac
from typing import Any

from airlock.common import DomainError, digest, now_ms, sign
from airlock.config import policy_hash
from airlock.contracts import AgentPrincipal, OperationRequest, Policy
from airlock.target import ADAPTER_VERSION

PAYLOAD_FIELDS = {
    "operation_id",
    "principal",
    "principal_hash",
    "request",
    "policy_hash",
    "adapter_version",
    "preview",
    "expires_at",
    "view_schema_version",
}


def make_plan(
    operation_id: str,
    principal: AgentPrincipal,
    request: OperationRequest,
    preview: dict,
    policy: Policy,
    expires_at: int,
) -> dict[str, Any]:
    payload = {
        "operation_id": operation_id,
        "principal": principal.permissions(),
        "principal_hash": digest(principal.permissions()),
        "request": request.normalized(),
        "policy_hash": policy_hash(policy),
        "adapter_version": ADAPTER_VERSION,
        "preview": preview,
        "expires_at": expires_at,
        "view_schema_version": "review-v1",
    }
    return {"payload": payload, "plan_digest": digest(payload)}


def validate_plan(plan: dict) -> dict:
    if set(plan) != {"payload", "plan_digest"} or not isinstance(plan["payload"], dict):
        raise DomainError("INVALID_PLAN", "计划格式无效。", 409)
    payload = plan["payload"]
    if set(payload) != PAYLOAD_FIELDS or type(payload["expires_at"]) is not int:
        raise DomainError("INVALID_PLAN", "计划内容无效。", 409)
    if not isinstance(plan["plan_digest"], str) or not hmac.compare_digest(
        digest(payload), plan["plan_digest"]
    ):
        raise DomainError("INVALID_PLAN", "计划内容与摘要不一致。", 409)
    if digest(payload["principal"]) != payload["principal_hash"]:
        raise DomainError("INVALID_PLAN", "身份范围与摘要不一致。", 409)
    return payload


def review_view(plan: dict, reason_code: str) -> dict:
    payload = validate_plan(plan)
    return {
        "schema": "review-v1",
        "plan_digest": plan["plan_digest"],
        "request": payload["request"],
        "preview": payload["preview"],
        "expires_at": payload["expires_at"],
        "principal_id": payload["principal"]["id"],
        "reason_code": reason_code,
    }


def execution_envelope(plan: dict, secret: str) -> dict:
    payload = validate_plan(plan)
    permit = {
        "operation_id": payload["operation_id"],
        "plan_digest": plan["plan_digest"],
        "issued_at": now_ms(),
        "expires_at": min(now_ms() + 30000, payload["expires_at"]),
    }
    return {"plan": plan, "permit": permit, "signature": sign(permit, secret)}
