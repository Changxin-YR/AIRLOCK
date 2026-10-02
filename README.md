# AIRLOCK · Agent 操作审批与影响预演

**个人工程作品：Agent提交意图，人看清影响，服务端持有执行权。**

核心不是再做一个确认按钮，而是：人批准的参数、策略和数据快照，必须与服务端最终执行所依据的对象一致。当前为有界SQLite合成场景，不是首个HITL、任意工具透明代理或生产安全认证产品。

```text
Agent（只有agent token）
  -> HTTP / 最小stdio MCP
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

技术栈：Python / FastAPI / Pydantic / SQLite，模块化原生JavaScript / CSS，最小stdio MCP。没有npm运行依赖，不需构建。不是Vue/Next.js版本：最初执行环境无法访问npm，因此选择实际可运行、可验证的原生模块交付。

## 本地演示

推荐Python3.13；要求Python≥3.11、SQLite≥3.37。下列方式只供可信开发机体验，不等于将高权限Agent放在同一目录中的隔离部署。

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
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

MCP host启动 `python -m airlock.mcp`，配置AIRLOCK_URL和仅agent token。只提供sql_execute/action_status，pending不是执行成功；使用收据ID查询。适配器通过HTTP访问闸门，不持有数据库或审核凭据。

官方MCP Python SDK互通测试覆盖初始化、发现工具、写入pending、独立审核和结果读回；只声明所测子集，不是完整规范认证，也不等于真实LLM已跑通。协商版本为2025-11-25/2025-06-18，无任意上游代理、OAuth或MCP Streamable HTTP服务。

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
```

完整命令、逐命令退出码收据、JUnit和产物门禁见 [CODEX_REVIEW.md](CODEX_REVIEW.md)。GitHub Actions会上传source.zip、原始日志、合成数据、逐例评测、原生截图、Docker报告和哈希清单。看实际提交对应的run，不只看图标。

开发中曾发现tee掩盖Docker失败的假绿，并保留修复历史。严格门禁与Docker网络修复后的基线525ea8f已验证Python84项（含官方SDK）、JS6项、原生浏览器9项及真实Docker检查。当前代码还增加了pending分页与异常输入回归；最终数量与结论以当前commit的CI证据和memory/progress为准。

200条/40模板族的benchmark全为作者构造的合成策略回归，dev120/test80按族划分，不是事故金标或真人数据。合成100%不能写成真实危险召回100%。内部评估p95不含最终持久化/提交、HTTP与人等待。

## 保证边界

Agent若可直接读写数据库、拿到审核密钥或控制服务器/宿主，代理无法保证控制。当前没有真实模型行为/语义评分、人类A/B、SSO、多租户、多人路由、生产连接器、学习型降级、外部审计锚定或提交后自动恢复。不把这些计划写成已实现。

[执行方案](docs/PLAN.md) · [技术契约](docs/SPEC.md) · [威胁模型](docs/THREAT_MODEL.md) · [评测方法](docs/EVALUATION.md) · [来源核验](docs/RESEARCH.md) · [面试问答](docs/INTERVIEW.md)

## 跨会话接续

```bash
git fetch origin main memory/progress
git show origin/memory/progress:PROGRESS.md
git show origin/memory/progress:STATE.json
```

先核对main SHA，再看代码和证据。记忆、文档和manifest不是授权或验收结果。不要再次清空仓库。独立验收后更新进度与剩余问题。
