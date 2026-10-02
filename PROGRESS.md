# AIRLOCK 执行记忆

更新时间：2026-10-02。本分支是任务接续记录，不是验收证明；以 main 对应提交、代码和实际运行结果为准。禁止再次清空仓库。

## 用户要求

个人项目，用于 AI 全栈实习简历和面试；ChatGPT 实现，Codex 独立验收。另建 memory/progress 保存真实进度、问题、证据和下一步。保留 Git 历史，不 force-push。

## 远端已固定的进度

- 旧实现清空提交：1f5d33b767d504a20473e80a154dcd424ddad1a0。其父提交 d9499abc515af9a69e47035f50f841ed05717690 仍在历史中。
- 当前实现提交：67df890db01c73416e8e9965387b6858c5ff4650（main），tree 75715d86ec9382dd9b088b444925341d27b3a45b。
- 已提交：Python 审批核心、FastAPI、最小 stdio MCP、中文原生 JS 审批台、脚本模拟 Agent、80 项 Python 测试、5 项 JS 测试、原生/桥接浏览器验收脚本、200 条合成策略集生成与评测、运行配置与 CI。
- 本次环境已重置，之前容器文件不再存在；已从 GitHub 中先前写入但未提交的对象恢复代码，并正式提交 main。不要再依赖旧 /mnt/data 路径。

## 校验的内容哈希

airlock: 89acf53f0dc918e52683248ec8178781de3f47da
scripts: 5466725775cc0bee60241d0916f89b8e84163b2a
tests: f8e07b06cf2e5b4629720930fa60312a3a774959
tests-js: 134bfe38ba022af2b07ee7d0269484c098b4c5fe
benchmark: 40d0dda64dbea8aa9c977bc88fc275aa9261b54c

审批台 app.js 已按上次原文件哈希恢复：3161d9ab8acbe5924f5c9c537eea340147e506cc，并在本次执行 node --check 通过。不要用先前未挂到 main 的其他树替代这个文件。

## 测试：历史记录与当前结果分开

上次实际工具输出：Python 80 passed；JS 5 passed；桥接 DOM 与真实 HTTP 交互 9 项通过。原生 Chromium 访问 loopback 被管理员策略阻断，因此没有原生 E2E 通过结论。Docker/真实 LLM/官方 MCP host/真人 A/B 没有运行。

上述结果是上次会话记录，不是本次 CI 结果。当前已配置 GitHub Actions，需查询真实 run 和 conclusion；不能写 CI 绿或生产就绪，直到证据成立。

## 冻结设计

- 协议无关核心，固定 SQLite synthetic customers 表，初始 1206 行。不是任意 SQL/任意工具透明代理。
- pass / block / need_approval；所有支持写入包括零变化操作都需审批，预演失败阻断。
- 独立 agent/reviewer 身份；客户端不能传 approved/risk/principal 来取得权限。
- 参数、策略、影响快照与版本绑定；执行前在 BEGIN IMMEDIATE 中再次校验指纹/TTL；写入、终态与 HMAC 审计同库提交。不是分布式 exactly-once。
- Agent 必须没有服务器文件、数据库、reviewer/audit 密钥及宿主管理权限，否则不可宣传不可绕过。
- HMAC 无外部锚定，不能检测尾部截断或服务器全失陷。
- MCP 仅 sql_execute/action_status，pending 回执不代表执行；SSE 只通知，不授权。
- 前端为无需构建的原生 ES Modules，不是 Vue/Next.js；不得隐瞒技术栈变化。
- benchmark 为作者构造的 200 条/40 族合成回归；dev 120/test 80 按族切分。无人类专家金标、κ 或真实用户实验，不能编造效率提升。

## 当前下一步

1. 查询 67df890 的 GitHub Actions 结果，修复实际失败并保留日志；不能把历史测试当本次验收。
2. 补齐设计、威胁模型、面试标准问答、Codex 独立验收与证据索引。
3. 记录新的 main SHA 和明确的 PASS/FAIL/NOT RUN/ENVIRONMENT BLOCKED；交付可下载文件须确认实际生成。
4. 更新本分支。开始任何新会话先 fetch main + memory/progress，核对 SHA，不再次重建或清空。
