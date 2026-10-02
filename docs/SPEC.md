# 技术契约 v0.2

完整可运行接口/配置和状态图见 [OPERATIONS.md](OPERATIONS.md)。下列是不依赖界面的核心约束。

Invocation 严格拒绝额外字段和非有限数，允许 tool/sql/parameters/arguments/idempotency_key。身份从服务端 Bearer 解析；SQL ≤4000 字符、参数 ≤50、HTTP body ≤16 KiB，所有文本必须有效 UTF-8。上游参数 ≤16，不能与 SQL/parameters 混用。支持恢复的请求用 tool=restore 和原动作 ID。Agent 不能提供 approved、principal、impact 或 risk 取得权限。

Action 保存原请求/摘要、主体、resource、创建/有效期、策略版本、状态、原始影响、风险/确认、reviewer 路由、review_digest、trace_id、request_id、template_version、语义建议及执行收据。review_digest 绑定 action ID、版本、TTL、参数、影响、策略、路由、风险、模板及上游配置。不同角色返回范围不同；Agent 看不到完整审批摘要/审计/恢复快照。

本地 EXPLAIN 经 SQLite 编译器 authorizer 判定操作，禁系统/控制表、DDL/ATTACH/扩展/用户事务、主键更新和触发器写入；只允许固定 customers 和确定性函数。克隆前后 diff 独立于目标，匹配行/变化行/返回行分开。审批在 BEGIN IMMEDIATE 锁内校验 before_hash，效果后核验 after_hash。业务、恢复计划、终态与签名事件同库提交，异常回滚。

远端要求受信 adapter 的无副作用 preview、target_version CAS 和幂等收据。executing 已持久化才发执行请求；失联 unknown 保留预算；重启 GET 原收据对账，不重复发送副作用。HTTP tool 适配不等于任意 MCP server 代理，更不代表跨系统 exactly-once。

三态 pass/block/need_approval 与业务执行状态分开。硬拒绝和错误优先，受支持写入至少需审。pending 不是成功，批准事实保存在审核事件，本地成功为 executed，远端 executing/unknown 不能填成 execution_occurred=false。服务端 TTL/时钟高水位独立于浏览器计时。

SSE 为有权限的通知，不能批准。可见计时使用 IntersectionObserver、visibilitychange 和 performance.now，仅是 untrusted 遥测。审计绑定 seq/action_id/previous_hash/完整事件；回放读取原快照，不重新执行。支持 operator 触发的 key-id 原子轮换、独立导出签名检查点及截尾验证；部署方须把检查点放在服务端不能覆写的位置。检查点之后的截尾及全部密钥失陷仍不受保证，未部署外部 WORM。

量化边界及价格/预算口径见运行手册；新 schema 和状态需相应权限、实际效果、故障和证据门禁测试。原始目标并未因支持边界受限而自动完成。
