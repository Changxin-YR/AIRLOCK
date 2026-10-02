# AIRLOCK · Agent 操作审批与影响预演

**个人工程作品：Agent提交意图，人看清影响，服务端持有执行权。**

人批准的参数、策略和数据快照，必须与服务端最终执行所依据的对象一致。当前支持有界 SQLite 合成数据和配置注册的 HTTP / MCP CAS 上游；完整范围、配置、状态机和实验工具见 [运行手册](docs/OPERATIONS.md)。126 项原始目标与结论见 [验收矩阵](docs/acceptance/COMPLETION_MATRIX.md)，部分外部验证仍受阻。

```text
Agent（只有agent token）
  -> HTTP / stdio 与 Streamable HTTP MCP
  -> 三态策略：pass / block / need_approval
  -> 固定表克隆预演，保存数量、diff和指纹
  -> 独立reviewer：核验范围与恢复限制
  -> 写事务内校验参数、版本、TTL、策略与数据
  -> 业务效果 + 终态 + HMAC审计，同库提交
```

## 已实现的主线

支持只读有界执行并留痕；所有支持写入包括零变化操作都持久化等待审批；未知、越界或预演失败默认阻断。SQLite编译器authorizer而非关键词决定可接受的表/函数/动作，克隆快照区分命中行与实际变化行。

参数/策略/数据快照绑定、幂等键、并发审批冲突、到期/重启、执行前漂移检测、提交前进程退出和审计失败回滚。HMAC保留原始审批快照，可回放/验证，不声称没有外部锚定也能检测尾部删除。

中文审批台显示影响数量、字段diff、SQL/参数、恢复未知、到期时间与高影响范围确认；支持服务端pending筛选、稳定分页、原生SSE、审计和移动布局。凭据只在内存，文字按文本渲染。历史只读超过100条也不会挤掉待审批请求。

补齐 CEL/YAML 三态策略、多人范围路由、提交后独立补偿审批、预算预占/结算、显式批量决策与 shadow 分组建议、真实 provider 的可选语义评估路径、关联 ID、阶段延迟/token/缓存看板，以及双人标注、四组消融和真人 A/B 工具。离线工具通过不代表真实模型或真人指标已达成。

技术栈：Python / FastAPI / Pydantic / SQLite / cel-python，Next.js 16.3.8 / React 19.3.0 静态导出审批台。React 管理登录、导航、数据和连接生命周期，影响与审计视图沿用项目的转义渲染组件。生产由 FastAPI 同源提供静态文件；构建需要 Node.js 22 和 npm ci，浏览器脚本以 CSP 内容哈希授权。

## 本地演示

推荐Python3.13；要求Python≥3.11、SQLite≥3.37。下列方式只供可信开发机体验，不等于将高权限Agent放在同一目录中的隔离部署。

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
npm ci
npm run build
python -m airlock init
python -m airlock serve
```

打开 http://127.0.0.1:8000。操作者本机查看var/local.json，仅把AIRLOCK_REVIEWER_TOKEN输入审批台。另开终端只设置AIRLOCK_AGENT_TOKEN，再运行：

```bash
python scripts/demo_agent.py --scenario delete
python scripts/demo_agent.py --scenario update
```

第一条请求删除全部1206条合成记录，建议首次在审批台拒绝：原数据保持，脚本转为SELECT。**批准后会真正删除这个演示库的数据。** update只调整id=1的余额。模拟器不是LLM；无模型key也能复现闭环。

没有自动重置API。需要另一份演示数据时，停止服务，设置新的AIRLOCK_DB路径后启动，保留旧库与审计。不要连接真实客户资料或生产库，不要把完整配置交给Agent。

## MCP接入

MCP host 启动 `python -m airlock.mcp`，配置 AIRLOCK_URL 和仅 agent token。提供 sql_execute/action_status 及当前身份可发现的注册上游工具；pending 使用收据 ID 查询。适配器通过 HTTP 访问闸门，不持有数据库或审核凭据。

官方MCP Python SDK互通测试覆盖初始化、发现工具、写入pending、独立审核和结果读回；只声明所测子集，不是完整规范认证，也不等于真实LLM已跑通。协商版本为2025-11-25/2025-06-18，支持 `/mcp` 的无会话 Streamable HTTP JSON；注册上游可选 MCP JSON discovery/call 和固定 CAS 契约。没有任意上游代理或 OAuth。

## Docker演示与隔离检查

可信操作者设置三个不同的随机长密钥（不要提交.env）后，`docker compose up --build airlock`；模拟Agent使用 `docker compose --profile demo run --rm agent`。AIRLOCK_PORT默认8000。服务器连接ingress+protected网络，Agent只在internal protected网络，服务器独享数据卷，端口仅发布到loopback。

独立可复现的隔离验收：

```bash
python scripts/docker_smoke.py
```

脚本自行创建唯一临时项目、随机密钥和测试卷，检验权限、数据/凭据隔离、网络/端口、独立审批与重启持久性，仅清理自己的资源。它不是容器逃逸或生产渗透测试。

## 验收

```bash
python -m pytest -q
npm run check
npm test
python -m benchmark.generate
python -m benchmark.evaluate --split test --output evidence/benchmark-test.json
python -m playwright install chromium
python scripts/browser_smoke.py
python scripts/browser_edges.py
python scripts/container_integrations.py
```

完整命令、逐命令退出码收据、JUnit和产物门禁见 [CODEX_REVIEW.md](CODEX_REVIEW.md)。GitHub Actions会上传source.zip、原始日志、合成数据、逐例评测、原生截图、Docker报告和哈希清单。看实际提交对应的run，不只看图标。

开发中曾发现tee掩盖Docker失败的假绿，并保留修复历史。严格门禁与Docker网络修复后的基线525ea8f已验证Python84项（含官方SDK）、JS6项、原生浏览器9项及真实Docker检查。当前代码还增加了pending分页与异常输入回归；最终数量与结论以当前commit的CI证据和memory/progress为准。

200条/40模板族的benchmark全为作者构造的合成策略回归，dev120/test80按族划分，不是事故金标或真人数据。合成100%不能写成真实危险召回100%。内部评估p95不含最终持久化/提交、HTTP与人等待。

## 保证边界

Agent 若可直接读写数据库、拿到审核密钥或控制服务器/宿主，就超出保护前提。真实模型行为、真实日志金标和真人 A/B 尚缺外部验证。当前未实现生产 SSO、多租户、任意第三方连接器或 OAuth。已提供轮换 key-id、签名检查点与独立保存工具；外部 WORM 仍需部署方提供。补偿和模型建议均不能自动授权。

[执行方案](docs/PLAN.md) · [技术契约](docs/SPEC.md) · [威胁模型](docs/THREAT_MODEL.md) · [评测方法](docs/EVALUATION.md) · [来源核验](docs/RESEARCH.md) · [面试问答](docs/INTERVIEW.md)

## 跨会话接续

```bash
git fetch origin main memory/progress
git show origin/memory/progress:PROGRESS.md
git show origin/memory/progress:STATE.json
```

先核对main SHA，再看代码和证据。记忆、文档和manifest不是授权或验收结果。不要再次清空仓库。独立验收后更新进度与剩余问题。
