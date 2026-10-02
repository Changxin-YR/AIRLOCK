# 技术契约 v0.1

## 输入与身份

Invocation 仅接受 tool、sql、parameters、idempotency_key，严格类型并禁止额外字段。sql 最多4000字符，参数数组最多50项；HTTP 请求总量最多16KiB。身份从服务端配置的 bearer token 解析，不能由客户端 principal、approved、risk 或 impact 取得权限。

固定主体 agent:demo 和 reviewer:owner。角色凭据分开不等于已验证两位真实人，更不等于 SSO/MFA。调用者必须没有服务器文件系统、数据库、审核密钥或宿主管理权限。

## Action 与状态

保存原始请求、主体、请求摘要、创建/过期时间、策略版本、初始决策、执行状态、影响快照、review_digest、版本、确认文字、结果和审批人。原始 SQL 不擅自重写；参数单独绑定。

```text
提交 -> blocked
     -> executed（支持只读 pass）
     -> pending（支持写入 need_approval）
          -> rejected / expired / stale / failed / executed
```

终态不能再审批。pending 在进程重启后仍可保留，但不会自动执行；按服务器时钟检查持久化 TTL。数据或策略漂移为 stale，新的意图需要新请求与新审阅。

## SQLite 预演与事务

使用 EXPLAIN 触发真实 SQLite 编译器 authorizer，禁用语句缓存以便每次授权。只允许 main.customers 和限定确定性函数。拒绝系统表、控制表、DDL、ATTACH、PRAGMA、扩展函数、递归查询、用户事务、主键更新及触发器来源写入。authorizer 不是操作系统沙箱。

固定 STRICT 表；最多5000行目标数据；私有内存克隆执行后比较前后数据。matched_rows 是命中数，changed_rows 是实际值变化数。预览最多5行样本，不是完整变更清单。整表指纹绑定所有支持记录与模式。结果最多100行/64KB；拒绝二进制、非有限数值和重复列名，大整数转文本避免浏览器损失精度。

审批摘要绑定 request_hash + impact + policy_version。服务端在 BEGIN IMMEDIATE 取得写事务后，校验身份、pending、expected_version、review_digest、TTL、策略与 before_hash；再重算存储的请求/审批摘要。实际执行置于 savepoint，after_hash 必须匹配预演。

目标数据、终态与 HMAC 审计在同库事务提交。审计失败或提交前进程退出会一起回滚。这里没有远端副作用，所以不能把这项保证外推为分布式 exactly-once。更换策略实现需更新版本常量；更换数据库模式或审计密钥需显式迁移，不能静默重置。

## HTTP 接口

| 方法/路径 | 身份 | 行为 |
|---|---|---|
| GET /healthz | 无 | 存活，不泄露配置 |
| GET /v1/me | 两角色 | 返回服务端身份 |
| POST /v1/actions | agent | 三态回执，pending 用202 |
| GET /v1/actions/{id} | 所属 agent / reviewer | 前者为脱敏回执，后者为完整快照 |
| GET /v1/actions | reviewer | limit最多100，before+before_id复合游标 |
| POST /v1/actions/{id}/decision | reviewer | approve/reject，版本、摘要、理由、范围确认与可选遥测 |
| GET /v1/audit | reviewer | after事件游标与原始证据 |
| GET /v1/audit/verify | reviewer | HMAC校验和限制 |
| GET /v1/metrics | reviewer | 最近1000条的内部评估p95及状态/目标行数 |
| GET /v1/events | reviewer | SSE通知，after游标、心跳、30秒连接租约 |

不确定的错误/冲突返回 execution_occurred=null。超时不是“肯定没执行”；客户端先查 action ID 或以同键同内容重试。不同负载复用同键会冲突；重新生成键可能造成新的真实操作。

## MCP

最小 stdio JSON-RPC 工具子集，协商2025-11-25/2025-06-18。支持 initialize、initialized、ping、tools/list、tools/call。只有 sql_execute、action_status；适配器通过 HTTP 使用 agent token，不读数据库，不暴露审批工具。单行输入有16KiB限制，stdout只输出协议 JSON。

官方 MCP Python SDK 的互通测试覆盖初始化、工具发现、pending、独立 reviewer 批准、状态与数据读回；不代表全部规范认证。没有通用上游转发、resources/prompts、MCP Streamable HTTP 服务、OAuth 或任意工具发现。

## UI、审计与测量

UI 用同源静态模块、文本节点和内存凭据；bearer通过header，SSE不携带URL密钥。Origin与Host检查、CSP/no-inline、nosniff是额外边界，不替代服务端授权。

HMAC envelope 绑定 seq、action_id、previous_hash 和完整事件。初次 evaluated 事件保留审批时看到的快照，回放不得事后重算。没有外部锚点不能发现合法尾部整体删除，也不能抵御服务器及密钥一起失陷。

IntersectionObserver与页面可见性记录客户端可见时长，明确为 untrusted，不参与权限或“真人理解证明”。内部评估p95不含最终持久化/提交、HTTP往返和人等待；静态分类/预演另有计时。命令日志必须保留真实退出码；验收器同时核对必需测试、原生浏览器、部署报告与评测产物。
