# AIRLOCK 执行记忆

更新时间：2026-10-02。此分支用于接续任务，不是已验收证明；以 main 对应提交、实际代码及原始测试输出为准。

## 用户目标与范围
- 个人原创工程项目，用于 AI 全栈实习简历和面试；由 ChatGPT 实现，Codex 独立验收。
- 从零重建，不沿用仓库原代码；保留 Git 历史，不 force-push。
- 定位：协议无关的服务端审批核心 + SQL 影响快照 + 知情审批界面。不得宣传“首个 HITL / 所有开源只会阻断”。
- 写操作必须由独立 reviewer 身份审批；Agent 不持有 reviewer 密钥或目标数据库权限。
- MVP 限定 SQLite synthetic customers 表；不支持任意 Shell、任意 SQL 数据库、自动学习后绕过审批。

## 已完成并核实
1. main 旧实现已清空（仅空 .gitkeep），提交 1f5d33b767d504a20473e80a154dcd424ddad1a0；前一提交 d9499abc515af9a69e47035f50f841ed05717690 仍在历史中。
2. 新建 memory/progress 分支。
3. 当前会话工作目录 /mnt/data/AIRLOCK 已编写首批新代码：models、SQLite 限制执行与克隆预演、审批状态机、FastAPI、stdio MCP 适配器，以及 58 项测试。
4. 2026-10-02 本地执行 python -m pytest -q，实际输出：58 passed in 1.16s。

注意：上述新代码此刻仍在当前会话容器，尚未提交 main；文件路径不是下个会话必定可用的永久存储。不得根据此记录谎称远端代码已完成。

## 冻结的关键设计
- pass / block / need_approval 三态；写入无自动放行。
- 审批绑定 request_hash、impact snapshot、policy_version、review_digest；提交前重校验数据指纹，过期或变化则失效。
- BEGIN IMMEDIATE + 本地单库事务把目标变更、审批终态及审计绑定；不声称分布式 exactly-once。
- 独立角色 token；服务端权限判定；SSE 只通知、不能授权。
- 精确是“当前受限数据快照内精确”，不是任意生产环境预测；无验证备份时不编造备份时间。
- HMAC 审计链无外部锚定，不能检测尾部截断或服务器全失陷。
- MCP 采用异步回执 + 状态查询，不伪称透明代理或依赖无限挂起。
- benchmark 与人类 A/B 实验不伪造；未执行项目标为未执行。

## 当前下一步
1. 审查首版安全边界并补回归测试；保留原始日志。
2. 完成可用审批台，真实调用 API，桌面/移动端浏览器测试。
3. 添加可复现模拟 Agent、MCP 端到端验证、合成 benchmark（明确 provenance / split / 局限）。
4. 完成运行配置、CI、README、设计说明、威胁模型、面试问答、Codex 独立验收文档。
5. 逐步提交 main；记录确切 commit SHA、通过/失败/未运行项与证据路径。

## 接续协议
开始工作前先读本文件、main 的 AGENTS.md 和 CODEX_REVIEW.md（存在时），查询 main 的真实 SHA。不要再次清空仓库，不要把计划当完成。每个阶段结束更新本分支；未完成任务、环境限制、事实与假设必须分开。绝不提交密钥、真实用户数据或本地配置文件。
