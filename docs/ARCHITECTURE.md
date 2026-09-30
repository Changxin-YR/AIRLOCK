# 架构与安全边界

## 一条请求经过哪里

Agent → HTTP 或 MCP 适配 → 网关认证/工具权限/项目范围 → 持久 operation+job → 执行器影子预检 → 固定策略 → 独立会话审批 → 持久执行许可 → 执行器短事务复核/写入/回执 → 状态及审计回传。

网关和执行器是同代码库的两个运行边界，不以微服务数量作为亮点。元数据库保存操作、任务、审批、视图、身份、会话、审计和限速；目标库保存合成业务数据与 execution_receipts。两库之间没有分布式原子事务。恢复依靠目标事务中的回执，不承诺任意外部工具 exactly-once。

## 信任模型

保护受限 Agent 发出的不可信请求；Agent 可以乱填参数、重复请求、声称已获准，但没有审批凭据、执行器秘密和目标文件。服务端注入 scope，不相信客户端的角色、只读、环境或批准声明。Compose 限制网络、卷、权限；本地同用户进程没有等价的文件隔离。

人类浏览器和宿主机完全失陷不在保证范围；管理员能够修改磁盘及配置。攻击者得到网关执行秘密相当于突破可信边界。审计不是合规认证，也不是防 root 篡改产品。

## 契约与预检

`contracts.py` 严格 Pydantic，拒绝额外字段和类型强制转换。内部 SQL 只由白名单标识符及参数绑定生成。所有业务操作强制项目 scope。仅 customers 的 name/status/tag 可以被修改，版本由执行器更新，notes 只能经受支持的外键级联改变。

`target.py` 使用只读目标连接的 Backup API，在内存副本执行操作。快照 Schema 必须与冻结定义一致，拒绝未知对象；字节、行数、耗时和查询返回量有上限。比较全部受管表的主键、记录和字段差异，不用 rowcount 代替级联统计。读取也检查 Schema、范围、列和返回限额。

精确表示“当前受支持快照上的逻辑数据差异”，不表示未来环境及业务后果全部可预测。预检失败关闭该请求；不改为让 LLM 猜测。不声明已验证备份或自动恢复。

## 三态不是生命周期

`decision`: pass / block / need_approval。

`state`: RECEIVED → PREVIEWING → BLOCKED / READY / PENDING_APPROVAL；PENDING_APPROVAL → READY / REJECTED / EXPIRED / CANCELLED；READY → EXECUTING 或取消/过期；EXECUTING → SUCCEEDED / STALE / FAILED / UNKNOWN。UNKNOWN 保留待核实状态，不当作普通失败自动新建请求。任务通过租约、条件更新和 fencing version 防止迟到工作者覆盖新状态。

## 所见、所批、所执行

规范化请求 → 事实摘要 → plan_digest → view_digest，摘要无自引用。计划冻结身份版本、scope、请求、策略、适配器、schema、全部受管业务状态、预检事实与到期时间。摘要不替代身份认证。

审批页面获取视图时保存 VIEW_PROVIDED。批准提交预期版本、计划/视图摘要、幂等键及决定；会话里的身份才是审批人。未取得对应视图、过期、版本变化、已被决定或已禁止均不可批准。记录提供过的证据并不证明用户真正阅读或理解。

审批与任务领取通过元数据库短事务串行化。等待人时目标无锁。领取执行时再次核对 Agent 授权、策略、期限，然后持久化签名许可；执行器 `BEGIN IMMEDIATE` 后先查回执，无回执再核对 Schema 与业务快照、执行原请求、核对实际差异、写回执并提交。

取消只在任务未领取前有效；领取是授权开始执行的边界，之后撤权不能回溯阻止已经进入目标事务的动作。许可短时有效；不提供“批准后随意编辑”。任意内容变化创建新操作。

## 故障与重放

提交以 principal+idempotency_key 唯一；同键不同请求冲突。批准与拒绝并发只有一个结果。目标 execution_receipts 以 operation_id 唯一并绑定 plan_digest。相同调用先返回原回执，不再次写入。

目标已提交但响应或元数据库成功事件丢失时，执行记录已先持久化。重启/租约超时通过回执核实；重复传输继续使用原许可和操作 ID。没有回执且许可失效不补发更宽松许可。多次无法核实的结果保留 UNKNOWN，人工触发核实也不能编辑操作。真实测试通过 os._exit 在目标提交之后终止进程。

## Web 安全与体验

独立人类会话、Argon2、随机凭据、会话撤销/版本、CSRF、Origin/Host 校验、限速、JSON 重复键拒绝、请求体上限、安全头。模型和数据库内容按不可信文本转义，无 v-html。公开部署必须 HTTPS 和 Secure Cookie，默认仅 localhost HTTP。

SSE 从数据库事件 ID 恢复并持续复核会话；轮询是通知失败后的补偿，不决定审批结果。前端拦截迟到详情与列表响应，避免旧版本覆盖新状态。IntersectionObserver 与页面可见性仅用于体验记录，不作为授权或用户理解证据。

## AI 与协议

`mcp_server.py` 是官方 SDK v1 维护线真实 stdio 服务，不是手写 JSON 假 MCP。测试实际 list/call/状态查询。应用层 pending 不是 MCP 原生 Tasks。

模型端 `model_agent.py` 的工具循环与检查点可调用 DeepSeek，但无外部凭据时不伪造运行。模型不触达目标库和审批接口；持久化工具请求的幂等键后才发网络请求，恢复不重复创建已有操作。未知工具如 approve 一律拒绝。

## 容量和产品取舍

单资源、单 scope 演示，不做组织管理、任意代理、多数据库、Redis、RAG。全受管状态摘要会把无关变更也判为 STALE，是明确的保守取舍。单记录标签自动放行不等于总风险预算；连续小操作的累计治理未实现。没有真实用户研究，不声称“三秒决策”。

代码事实优先于本文件。核心入口：target.py、service.py、plans.py、auth.py、storage.py；独立测试：test_target、test_service、test_http、test_process_mcp。
