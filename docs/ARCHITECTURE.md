# Architecture / 实现基线

版本：0.1.0。仓库由用户授权重建，保留旧提交历史；旧对话的执行状态和本地路径不作为事实。实施者完成代码与验证，Codex 最后做独立检查。适用范围：单维护者、小型合成 SQLite 资源、结构化工具；不连接生产目标。

## 1. 运行边界

```text
受限 Agent / MCP stdio / 可选模型客户端
        | Agent bearer：仅提交、查看自己的结果、取消未领取请求
        v
FastAPI 网关 ─── SQLite 元数据（操作/任务/审批/视图/审计/会话）
        ^                       不保存目标数据库文件
        | 独立 cookie + CSRF + Origin + reviewer 权限
Vue 审批浏览器
        |
        | 私有 HTTP + 服务密钥 + 绑定计划的短期 HMAC 许可
        v
受控 SQLite 执行器 ─── 目标库（customers、customer_notes、execution_receipts）
```

HTTP/MCP 共用一个核心，不各写一套权限。MCP 只是请求和状态工具，待审批是应用层句柄；当前不实现 native Tasks。Agent 不传 SQL/路径/主机/数据库账号，也不能用 `approved=true`、工具描述或模型文本改变授权。

网关和执行器是同一代码库的两个运行角色，不称为大规模微服务。Docker agent 仅 edge 网络；runner 仅 internal control；gateway 跨两个网络。服务密钥和审批凭据不挂载给 Agent。宿主管理员、可信网关/执行器本身和审批浏览器被完全攻陷不在保证范围内。公网入口、TLS、备份、主机加固与独立审计仍是部署责任。

## 2. 请求、授权与策略

`contracts.py` 的 Pydantic strict/extra-forbid 模型限定工具、类型、条件数和输出长度。支持 `eq/lt/lte/gt/gte/in` 和 AND，值通过参数绑定进入 SQL。表/字段标识符来自固定白名单，不能从用户表达式拼入。

服务身份在服务端配置中注册，保存 bearer 的 SHA-256 摘要；权限限定资源、工具、可读字段与可写字段。读取筛选条件也不能使用未授权字段。业务邮箱不暴露。身份验证、参数与字段授权在预检之前完成。读取历史结果、幂等重提旧请求时也重新检查当前权限。

`policy.py` 的三态决定独立于操作状态。限量合法读取可 pass；小范围测试标签在明确规则下 pass；合法但需要确认的修改 ask；非测试记录删除、超影响上限等 block。审批没有覆盖 block 的“强制执行”入口。YAML 经严格模型和重复键校验，不使用 eval，不冒充 CEL/Envoy 兼容。

配置每次关键授权时重读；计划绑定整个策略内容摘要及身份权限摘要，改阈值但忘了改版本同样会失效。人工批准不修复权限撤销。执行授权的线性化点为任务从 READY 被事务性领取为 EXECUTING；已进入目标事务的执行不承诺可被后来撤权逆转。

## 3. 预检与一致性

`target.py` 使用 SQLite backup 取得一致性影子副本，只在影子上模拟。严格校验固定 Schema，未知触发器、视图、索引、表或扩展能力拒绝。固定表均有主键。对所有受管业务表做逻辑 before/after diff，直接变更与支持的 FK cascade 分列。email 在内部状态摘要中，但展示时脱敏。

`exact_on_snapshot` 仅表示当前受支持快照上的逻辑变化。行数、快照、数据摘要、回执与恢复状态均由后端生成；恢复未配置就明确显示未配置。模型不可填这些事实。行数/字节/时间超限则预检失败，不截断后声称完整。当前性能目标是演示级顺序任务；未实现资源级公平调度和请求速率预算，服务令牌持有者仍可能消耗队列资源，不宜直接用作公网服务。

计划是不可变载荷：操作 ID、请求者权限、规范化请求、策略 hash、适配器版本、预检事实、有效期。固定 JSON 排序且拒绝 NaN/重复键，先事实再计划再展示视图摘要，不存在自引用 hash。hash 是完整性标识，不是身份认证；身份和权限另查。

执行器验证短期许可与计划、策略，进入 `BEGIN IMMEDIATE`，再核对整个业务状态与 Schema；重新执行保存的原请求，核对实际 after/diff 摘要与批准内容一致，最后提交。等待人工时不持有目标锁。任何业务记录变化（包括无关行）均可使旧计划 STALE；保守而可解释，后续优化必须保留目标集合完整性。

## 4. 生命周期与失败语义

```text
RECEIVED -> PREVIEWING -> BLOCKED | READY | PENDING_APPROVAL
RECEIVED -> BLOCKED | CANCELLED | EXPIRED
PREVIEWING -> RECEIVED（仅失效预检租约恢复）| FAILED | EXPIRED
PENDING_APPROVAL -> READY | REJECTED | EXPIRED | CANCELLED
READY -> EXECUTING | STALE | EXPIRED | CANCELLED
EXECUTING -> SUCCEEDED | STALE | FAILED | EXPIRED | UNKNOWN
UNKNOWN -> SUCCEEDED（回执核实）| UNKNOWN（未核实）
```

以 `storage.py` TRANSITIONS 和测试为可执行真值。READY 记录 policy/human 来源，不等于成功。STALE 不能原地编辑后重新执行，需新操作+新幂等键并引用安全终结的旧操作；UNKNOWN 不是可替代的安全终态。

操作、任务领取、状态 CAS 和执行前审计在元数据库的短 `BEGIN IMMEDIATE` 内提交。每个操作唯一任务，领取使用租约和随机 token；旧工作者不能覆盖新工作者结果。预检崩溃可重做，因为不写目标；执行租约失效只能进入 UNKNOWN、查回执，不重新发出变更。

业务变更与 `execution_receipts` 在同一目标事务提交，唯一 `operation_id` + 匹配 `plan_digest`。同计划重试返回同回执；不同摘要冲突。两个数据库没有分布式事务，因此目标已提交、元数据未记成功时通过回执恢复。目标 I/O 异常不轻率判为“未提交”，保留 UNKNOWN。有限次数核实仍无回执时停留 UNKNOWN，人只能再次查询回执，不能按按钮盲目重放。

自动核实可能发生在旧执行仍在进行时；缺失回执不是未执行的充分证据。测试通过目标提交后 `os._exit(88)` 真杀进程、再启动新 Python 进程恢复，生产服务没有对应测试后门。

## 5. 人类审批与前端

预置单 reviewer，随机初始密码、Argon2id、登录尝试限速、服务端会话、HttpOnly/SameSiteStrict，公网配置要求 HTTPS/Secure cookie。审批修改要独立会话 + Origin + CSRF；人身份不从 JSON 得到。Agent bearer 无法调用人类接口。公共主机精确匹配；容器内部 Host 仅允许 Agent 操作路径。

人类 GET 审批详情时，服务端保存完整展示快照、view ID/hash、会话 hash。决定绑定该视图、计划 hash、预期版本、非空理由与决定幂等键。两个标签页竞争只有一个最终决定。历史视图从保存的 JSON 读取，回放只读，不重新预检、不执行。

Vue 不使用 v-html。数据库文本/Agent 意图/拒绝理由按文本显示；CSP 禁止非同源脚本。重要影响与关键变化前置，完整 diff 分页可查。SSE 仅推送资源过滤后的通知，持久状态以 HTTP/DB 为准；断线有重连和查询恢复。IntersectionObserver/visibility 只采集体验诊断，不作为人读懂的证明。单条高风险逐一审批，没有自学习降级。

## 6. 审计、局限与取舍

审计事件有操作内递增序号及 hash 链，保存服务端提供的视图与执行来源。它不能证明用户真的认真阅读，也不是防 root 改库或认证合规证明。为避免读日志泄密，不打印请求体/密码/授权 header，示例数据是 `.invalid` 域名合成记录。

不加入 MySQL、RAG、Redis、Celery、通用代理、组织系统：项目难点集中在边界和一致性；用固定 SQLite 引擎避免预演与真实执行方言不同。SQLite 元数据单写者和全库摘要的扩展性有限。开发锁文件按已测试 Python3.13/Linux 解析，提交精确版本但不是所有平台的可复现承诺。

真实模型是可选任务端，不是权限决策者；无 API key 时仅核心/协议可验收。合成 benchmark 与用户实验分别标识，不能用已有测试通过推导“没有任何漏洞”。

## 7. 参考依据（官方，核验于 2026-09-30）

- SQLite Backup API：https://www.sqlite.org/backup.html
- SQLite transactions：https://www.sqlite.org/lang_transaction.html
- SQLite changes 的辅助变化边界：https://www.sqlite.org/c3ref/changes.html
- OWASP Transaction Authorization：https://cheatsheetseries.owasp.org/cheatsheets/Transaction_Authorization_Cheat_Sheet.html
- MCP Python SDK：https://github.com/modelcontextprotocol/python-sdk
- DeepSeek Chat Completions / Tool Calls：https://api-docs.deepseek.com/api/create-chat-completion/ 、https://api-docs.deepseek.com/guides/tool_calls/
- Playwright CI：https://playwright.dev/docs/ci

这些资料支持设计原则；本项目是否实现由实际代码与对应测试证明。
