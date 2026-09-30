"""Synthetic, deterministic proposals. All go through ordinary authorization."""
from __future__ import annotations
from .contracts import ToolRequest

SCENARIOS = {
    "read": {"title":"读取测试客户", "description":"有限只读请求，验证真实数据与自动放行。", "expected":"pass",
        "request":{"tool":"db.query_rows","filters":[{"field":"is_test","op":"eq","value":1}],"limit":5}},
    "tag": {"title":"标记一条记录", "description":"显式的小范围标签规则；不会代替其他写操作的审批。", "expected":"pass",
        "request":{"tool":"db.update_rows","filters":[{"field":"id","op":"eq","value":10}],"values":{"tag":"reviewed"}}},
    "review": {"title":"归档三条测试客户", "description":"预检字段差异，等待独立的人类账号确认。", "expected":"need_approval",
        "request":{"tool":"db.update_rows","filters":[{"field":"id","op":"in","value":[1,2,3]}],"values":{"status":"archived"}}},
    "cascade": {"title":"删除测试客户及备注", "description":"展示两条客户与四条级联备注；不是只看 rowcount。", "expected":"need_approval",
        "request":{"tool":"db.delete_rows","filters":[{"field":"id","op":"in","value":[4,5]}]}},
    "block": {"title":"阻止过宽删除", "description":"合成初始库中有 1,206 条本项目客户，过宽变更会被阻止。", "expected":"block",
        "request":{"tool":"db.delete_rows","filters":[{"field":"id","op":"gte","value":1}]}},
}


def scenario_request(name: str) -> ToolRequest:
    item = SCENARIOS[name]
    return ToolRequest(**(item["request"] | {"task":item["title"],"run_id":"scripted-demo"}))
