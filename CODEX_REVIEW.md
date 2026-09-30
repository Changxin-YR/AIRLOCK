# Codex 最终独立审查

你接手的是已实现的 AIRLOCK 个人项目，不是要求从头开发。不要相信 README 的 PASS 标签；从代码、当前 Git HEAD、原始测试和目标数据库独立核对。先记录 HEAD 和工作区状态，保留用户未提交文件。

## 执行

1. 阅读 README、docs/ARCHITECTURE.md、AGENTS.md。审查 target.py、plans.py、service.py、auth.py、storage.py、HTTP/MCP 边界和 Compose。
2. 全新 Python3.13 + Node22 环境，`pip install -r requirements.lock`、`pip install --no-deps -e .`、`npm ci --ignore-scripts --prefix apps/web`。运行 `python -m pytest -q`、`npm run build --prefix apps/web`、`python scripts/evaluate.py`。
3. 安装实际 Chromium，执行 `python scripts/browser_check.py --out Evidence/codex/browser`，亲自查看桌面和窄屏截图，核对真实 UI/后端状态而非 mock。
4. 在新空 runtime 初始化并按 README 部署 Compose；运行 `python scripts/compose_check.py`。不得接触真实业务数据库或使用原库作破坏测试。
5. 查看当前 HEAD 对应的 GitHub Actions artifact，复核依赖审计和失败日志。没有模型凭据就保留 NOT_TESTABLE，不用 mock 冒充真实模型。没有真实用户不写 A/B 数据。

## 必须尝试破坏的不变量

- Agent token 不能登录人类会话或调用审批；伪造 role/approved/scope/未知字段失败。
- 人类批准不能覆盖 block、越权、过期或未知能力。未提供的视图不能批准。
- 预检不修改真实目标；级联影响不能漏报；Schema/触发器变化与超限关闭请求。
- 同参数不等于同目标；修改无关业务行也应使本版旧计划 STALE。执行期间检查与写入同事务。
- 参数/身份/资源/策略/摘要/视图被换不能复用审批。批准后不得从客户端重新取执行参数。
- 重复点击、并发 approve/reject、取消和领取有唯一明确结果。
- 目标提交后进程退出、响应丢失、元数据库成功事件失败，回执恢复不重复业务效果。过期许可不能重新执行无回执动作。
- Agent 容器无数据卷/审批秘密/执行器网络/Docker socket。普通本地进程不冒充强隔离。
- SSE 断线/刷新/会话失效不能变更授权；列表和详情范围一致。迟到前端请求不能覆盖新版本。
- diff、拒绝理由和模型文本不能执行 HTML。数据和 key 不进入公开日志/截图/检查点。

## 输出

按严重性给 Findings，包含复现命令、原因、影响、文件行号、最小修复和新增回归；无证据不要宣称漏洞。不要删除失败测试、放宽策略、改预期掩盖缺陷。修改后重跑相关路径及全套回归，保存命令、退出码、原始日志和截图。

最终报告 PASS/FAIL/NOT_TESTABLE 分开；代码已实现但外部未运行不等于验收成功。不得声称通用安全网关、全局 exactly-once、行业首创、生产可用或用户实验改善。用户希望你最终检查，而不是重新设计或增加范围外模块。
