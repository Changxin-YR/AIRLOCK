"""Acyclic content binding. Hashes detect content mismatch, not human identity."""
from __future__ import annotations
from typing import Any
from .common import AirlockError, digest


def make_plan(operation_id: str, principal: dict, request: dict, facts: dict,
              policy_version: str, expires_at: float) -> dict[str, Any]:
    core = {"operation_id": operation_id, "requester": principal["id"], "scope": principal["scope"],
            "auth_version": principal["version"], "request": request, "request_digest": digest(request),
            "policy_version": policy_version, "adapter_version": "sqlite-structured-v1",
            "schema_digest": facts["schema_digest"], "state_digest": facts["state_digest"],
            "facts_digest": digest(facts), "facts": facts, "expires_at": expires_at,
            "view_schema_version": 1}
    core["plan_digest"] = digest(core)
    view = {"operation_id": operation_id, "request": request, "facts": facts,
            "plan_digest": core["plan_digest"], "expires_at": expires_at,
            "evidence_note": "在此快照与受支持 Schema 范围内精确；恢复未验证。"}
    core["view"] = view
    core["view_digest"] = digest(view)
    return core


def validate_plan(plan: dict) -> None:
    core = {k: v for k, v in plan.items() if k not in {"plan_digest", "view", "view_digest"}}
    try:
        valid = (digest(core) == plan["plan_digest"]
                 and digest(plan["request"]) == plan["request_digest"]
                 and digest(plan["facts"]) == plan["facts_digest"]
                 and digest(plan["view"]) == plan["view_digest"]
                 and plan["view"]["plan_digest"] == plan["plan_digest"]
                 and plan["view"]["facts"] == plan["facts"]
                 and plan["view"]["request"] == plan["request"])
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise AirlockError("PLAN_MISMATCH", "计划内容与摘要不一致，拒绝执行。")
