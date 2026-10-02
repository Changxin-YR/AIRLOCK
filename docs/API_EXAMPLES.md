# HTTP回执与队列用法

以下请求仅面向本项目合成数据库。凭据通过Authorization header提供，不出现在URL；不要把reviewer token提供给Agent。

## Agent提交

POST /v1/actions，agent token，JSON：

```json
{"tool":"sql","sql":"UPDATE customers SET balance=balance+1 WHERE id=?","parameters":[1],"idempotency_key":"my-demo-update-0001"}
```

支持写入返回202和id/state=pending/decision=need_approval/execution_occurred=false；这不是执行成功。Agent随后GET /v1/actions/{id}或调用MCP action_status。重复发送必须使用同键同负载；修改意图须创建新动作，不能让批准覆盖新参数。

## Reviewer查看与决定

GET /v1/actions?state=pending 是服务器先筛选状态再分页，避免大量已完成的只读历史遮蔽待审批请求。state可为pending/executed/blocked/rejected/expired/stale/failed；未知状态拒绝。limit最大100，next_cursor包含before和before_id，下一页两者必须一起带上。before须为有限非负数。

Reviewer GET /v1/actions/{id}取得完整快照、review_digest、version、confirmation_required，再POST /v1/actions/{id}/decision：

```json
{"decision":"approve","review_digest":"这里替换为本次服务端返回的64位摘要","expected_version":1,"reason":"已经核实该单行调整的业务授权","confirmation":""}
```

示例摘要是说明文字，不是可用授权值。高影响时confirmation必须与服务端返回的文字完全一致；单行变更通常为空。reject仍需真实理由，但不会执行SQL。

服务端在事务内重验身份、状态、版本、TTL、参数、策略和数据。stale说明原快照已失效，不能重放原批准。执行失败/网络超时也不能推断先前一定没执行，先查收据。

## 错误与遥测

JSON中的approved/risk/principal/impact不会被接受；NaN/Infinity及非法游标以可序列化错误响应拒绝，不回显原始输入。visible_ms可选且不可信，只作遥测。SSE after游标只控制通知重放，不具有审批权限。
