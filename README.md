# AIRLOCK · Agent 操作审批台

个人工程作品：Agent 提交意图，独立审批人看清影响，服务端决定是否执行。

当前是有界 SQLite 审批实验室，而不是任意工具的透明代理或首创 HITL。核心是把一次审批绑定到参数、策略和数据快照，并在执行事务中重新校验。

## 已实现

Python / FastAPI / Pydantic / SQLite 后端；模块化原生 JavaScript 中文审批台；HTTP 与最小 stdio MCP 工具接入。

支持的只读调用 pass；支持的写入持久化为 need_approval；未知、越界或无法预演的动作 block。克隆内存库计算变化行数和样本 diff；真实库在批准前不写入。所有写入包括零变化操作都需审批，高影响要求准确范围确认。

独立 agent/reviewer 凭据、请求幂等、版本/TTL/数据与策略再校验、同库原子执行和 HMAC 审计，配套真实 HTTP/stdio 子进程与崩溃回滚测试。前端有队列、影响预览、批准/拒绝、历史/审计和 SSE 通知。

## 运行

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m airlock init
python -m airlock serve
```

访问 http://127.0.0.1:8000。操作者本机查看 var/local.json，仅将 AIRLOCK_REVIEWER_TOKEN 输入审批台。另开终端只设置 AIRLOCK_AGENT_TOKEN 后运行：

```bash
python scripts/demo_agent.py --scenario delete
python scripts/demo_agent.py --scenario update
```

第一条模拟器请求全表删除，建议先在审批台拒绝并观察 1,206 行保持不变以及 SELECT 替代路径。批准会真正删除这个演示库的合成数据；没有自动重置接口。不要使用生产数据，也不要将服务器目录、数据库或 reviewer/audit 密钥交给有 shell 的 Agent。

## 验证

```bash
python -m pytest -q
npm run check
npm test
python -m benchmark.generate
python -m benchmark.evaluate --split test --output evidence/benchmark-test.json
python -m playwright install chromium
python scripts/browser_smoke.py
```

没有 npm 运行依赖，也不需要构建前端。因上次执行环境无法访问 npm 源，选择了能实际运行的原生模块；不是 Vue/Next.js 成品。

上次会话实际运行记录为 Python 80 passed、前端辅助测试 5 passed、桥接 DOM 检查 9 项通过；这些是历史本地结果，不代表本次远端 CI 已通过。原生浏览器因管理员策略禁止 loopback 未通过环境门禁，--bridge 不可充当原生 E2E。当前 CI 会独立运行并上传证据，必须查看实际结论。

benchmark 是 200 条/40 模板族的合成策略回归，按族拆为 dev 120/test 80，不是真实事故、双人金标或真人 A/B。纯 LLM/混合语义评估、官方 SDK host 互通、真实模型与 Docker 隔离均不能依据这些测试宣称完成。

MCP 命令为 python -m airlock.mcp，只提供 sql_execute/action_status。pending 不是成功，工具需处理回执并查询；适配器不持有 reviewer token，也不读取目标数据库。

## 安全边界

所有保护都以前提为基础：Agent 无数据库文件/服务器配置/宿主管理权限。仅有代理不能约束另一个直达数据库通道。Compose 配置服务端独享卷、非 root、只读根和独立 Agent 凭据，但尚需独立部署验证。

快照精确只限当前白名单表/模式/函数；不支持任意 shell、远端业务副作用、SSO、多租户、多人路由、自动降级或提交后恢复。HMAC 无外部锚定，不能检测尾部截断或服务器全失陷。内部评估延迟不含最终持久化/提交、HTTP 和人的等待。

## 接续

进度放在 memory/progress 分支。先 git fetch，再读取 git show origin/memory/progress:PROGRESS.md 并核对 main SHA；不要再次清空仓库。设计与独立验收文档继续随当前交付补齐。
