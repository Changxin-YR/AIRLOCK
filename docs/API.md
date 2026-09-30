# API contract

HTTP 公共 API 位于同源 `/api`。JSON strict、禁止额外字段和重复键。公开请求体上限 64 KiB；private runner 16 MiB。未知字段返回 422；重复 JSON/NaN 返回 400。输出验证错误不回显密码。非幂等写请求不是靠 SSE 保持。

## Agent

`Authorization: Bearer <仅Agent凭据>`。`POST /api/operations` 还需 `Idempotency-Key`：16–128 ASCII 字符。相同身份/键/规范参数返回原操作；同键不同参数409；旧结果也受当前授权检查。

```json
{
  "tool": "db.update_rows",
  "resource_id": "demo",
  "table": "customers",
  "intent": "为已核验的测试客户标记标签",
  "run_id": "review-demo",
  "where": [
    {"field": "is_test", "op": "eq", "value": true},
    {"field": "id", "op": "lte", "value": 6}
  ],
  "changes": {"tag": "已核验"}
}
```

返回202操作句柄：`id/state/version/decision/plan_digest/request/result/error/feedback/poll_after_ms` 等。查询 `GET /api/operations/{id}`；取消 `POST /api/operations/{id}/cancel`，JSON `{}`。不得用 Cookie 代替 Agent 身份。操作ID不是权限。只能取消未被领取执行的请求，不可撤销已提交事务。

字段类型、数量与枚举以 `airlock/contracts.py` / OpenAPI 为准；不存在任意 SQL、连接串、readOnly、approved、approver_id 参数。`db.query_rows` 使用白名单 `columns` 和 `limit`；`update_rows` 仅 status/tag；删除测试数据仍有策略与人工审批。邮箱字段既不能输出，也不能用来筛选。

## Human session

`POST /api/session/login {username,password}`，必须带匹配 `Origin`；设置 HttpOnly Cookie，返回 `csrf_token`。`GET /api/session` 取当前会话，`POST /api/session/logout {}` 撤销。所有人类修改同时需要正确 Cookie、Origin、`X-CSRF-Token`。密码轮换/撤销会话后旧 Cookie 失效。

`GET /api/reviews?state=PENDING_APPROVAL&limit=30&offset=0`；每个请求仍检查 reviewer 的资源范围。

`GET /api/reviews/{id}` 返回 operation、当前 view/hash、view_id；可审批视图保存到数据库。`?read_only=true` 不签发新审批视图。

```json
{
  "decision": "approve",
  "plan_digest": "服务器返回的完整计划摘要",
  "expected_version": 3,
  "view_id": "同一会话刚取得的视图ID",
  "idempotency_key": "一个16位以上唯一决定键",
  "reason": "已核对变化及影响范围"
}
```

发送到 `POST /api/reviews/{id}/decision`。decision 仅approve/reject，版本/视图/计划/期限不匹配返回409，身份不足401/403。block无强制批准入口。批准进入READY，不代表SUCCEEDED。

`GET /api/reviews/{id}/audit` 只读时间线及链完整性；`GET /api/reviews/{id}/views/{view_id}` 读取保存的历史展示快照。`POST /api/reviews/{id}/reconcile {}` 只重新查UNKNOWN回执；不是重发执行。`POST /api/reviews/{id}/cancel {}` 取消尚可取消的请求。

`GET /api/events` 为Cookie认证的SSE，支持`Last-Event-ID`游标及资源过滤；`GET /api/metrics` 是实际状态计数；`GET /api/resource` 是受控演示资源概况。`POST /api/demo` 仅在配置显式开启且人类认证后创建固定场景，仍经过完整规则，不能传自定义SQL或bypass。

## 错误和恢复

格式：`{"error":{"code":"...","safe_message":"...","retryable":false}}`，请求有X-Request-ID。常见状态：401身份缺失；403权限/CSRF；404结果不存在或当前无权；409幂等/版本/过期/状态冲突；422类型/字段；429登录尝试过多；503必需能力暂不可用。

STALE：批准快照或当前授权变化，需新提案。EXPIRED：原计划过期。BLOCKED：不能由审批覆盖。REJECTED：人类拒绝理由作为反馈返回Agent（界面提醒不要写密钥）。UNKNOWN：执行结果不确定，只核实旧回执，不能生成同变更新操作。HTTP成功不是业务执行成功，必须检查state和receipt。

Private runner API 不供Agent或浏览器使用。其preview/execute/receipt接口需要私有服务密钥，execute还需与不可变计划绑定的短期签名许可。不要把私有地址/密钥放入MCP客户端配置。
