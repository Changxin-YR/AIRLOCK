from __future__ import annotations

from typing import Any

from airlock.contracts import OperationRequest, Policy


def decide(request: OperationRequest, preview: dict[str, Any], policy: Policy) -> tuple[str, str]:
    """Deterministic and monotone: a human approval cannot override a block."""
    if request.tool == "db.query_rows":
        return "pass", "AUTHORIZED_READ"
    if preview["coverage"] != "exact_on_snapshot":
        return "block", "PREVIEW_REQUIRED"
    if preview["total_changes"] > policy.max_total_changes:
        return "block", "IMPACT_LIMIT"
    if request.tool == "db.delete_rows":
        if preview["non_test_matches"] or preview["matched_records"] > policy.max_delete_records:
            return "block", "PROTECTED_DELETE"
        return "need_approval", "DELETE_REQUIRES_REVIEW"
    if (
        set(request.changes) == {"tag"}
        and not preview["non_test_matches"]
        and preview["matched_records"] <= policy.auto_tag_max
    ):
        return "pass", "SMALL_TEST_TAG"
    return "need_approval", "CHANGE_REQUIRES_REVIEW"


REASONS = {
    "AUTHORIZED_READ": "授权范围内的限量读取。",
    "SMALL_TEST_TAG": "小范围测试数据标签变更，符合自动放行规则。",
    "IMPACT_LIMIT": "影响范围超过当前策略允许的范围。请缩小请求。",
    "PROTECTED_DELETE": "删除涉及受保护数据或范围过大，不能通过人工审批覆盖。",
    "DELETE_REQUIRES_REVIEW": "删除允许范围内的测试数据，需要独立人工确认。",
    "CHANGE_REQUIRES_REVIEW": "此变更需要独立人工确认。",
    "PREVIEW_REQUIRED": "缺少完整的影响证据，不能继续执行。",
}
