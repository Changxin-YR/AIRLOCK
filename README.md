# AIRLOCK · Agent 工具调用审批与影响预演

AIRLOCK 在 Agent 的操作生效前计算影响、请求独立审批，并在执行时重新检查授权与数据状态。它适用于需要人工确认的受控工具调用：查看具体变化、批准或拒绝、查询执行结果，并核对完整审计链路。

服务端持有执行权。Agent 只有调用身份，不能用模型建议、预算或可逆性声明替代审核权限。当前支持有界 SQLite 合成环境、注册的 HTTP/MCP CAS 上游，以及固定仓库的 GitHub Issue 创建适配器。

## 工作流程

```text
Agent 提交操作
  → HTTP / stdio MCP / Streamable HTTP MCP
  → CEL/YAML 三态策略：pass / block / need_approval
  → 影响预演：数量、字段 diff、数据指纹和恢复依据
  → 独立 reviewer 查看原始快照并批准或拒绝
  → 服务端复核范围、参数、版本、TTL、策略与数据
  → 执行结果、动作状态和审计收据
```

本地写入的业务效果、终态与审计在同一数据库事务提交。远端操作使用适配器的 CAS/幂等契约；发送后结果不确定时保留 `unknown`，通过原 action 与原收据对账。

## 核心能力

- **受控接入：** HTTP 与官方 MCP SDK 互通；注册工具限制操作、资源和目标地址，域名 DNS pin 与 TLS 校验约束上游连接。
- **影响与审批：** SQLite 克隆预演区分命中行与变化行；审批台呈现字段 diff、恢复限制和到期时间，服务端按审核范围过滤待办和审计。
- **一致性与故障处理：** 请求/策略/快照绑定、幂等冲突、并发决定、TTL、重启恢复、执行前漂移检查；本地独立补偿审批及远端未知结果对账。
- **治理：** 明确成员的批量决策、累计风险权限复核、预算预占与结算、由操作者管理的 shadow 分组建议。所有支持写入仍需独立批准。
- **审计与观测：** 原始审批快照、HMAC 审计、签名检查点、可选 S3 Object Lock 连接器，以及 trace、阶段延迟、token、缓存和健康指标。

技术栈：Python、FastAPI、Pydantic、SQLite、cel-python；Next.js / React 静态导出审批台，由 FastAPI 同源提供。依赖版本见 `requirements*.txt`、`package-lock.json`，构建要求 Node.js 22。

## 本地运行

推荐 Python 3.13，要求 Python ≥3.11 和经确认修复 WAL-reset 的 SQLite。CI/Docker 固定 SQLite 3.53.1 并校验实际加载的 source ID；不满足要求时会在打开持久库前拒绝。参见[运行时要求](docs/OPERATIONS.md#sqlite-运行时要求)。

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

`serve --config path/to/config.json` 显式选择的文件必须存在、可读且为 UTF-8 JSON 对象，否则在启动服务前退出 2。省略 `--config` 时读取默认 `var/local.json`（如存在），也支持纯环境配置；已设置的环境变量保持优先。

打开 `http://127.0.0.1:8000`。操作者本人在本机查看 `var/local.json`，将 reviewer token 输入审批台。Agent 进程只配置 agent token；数据库、审核凭据和审计密钥留在服务端。

用现有确定性客户端提交一个合成操作：

```bash
python scripts/demo_agent.py --scenario update
```

该请求调整合成表中 `id=1` 的余额，首先返回 `pending`；在审批台核对影响并明确批准后才生效。客户端同时支持 `read`、`delete` 和 `blocked` 场景。**批准 `delete` 会删除当前合成库的 1206 条记录。** 拒绝后客户端可改用只读查询；它是确定性模拟器，无需模型密钥。

本地运行适合可信开发机检查功能；Agent 与服务端处于同一高权限目录时不构成部署隔离。每次需要新数据时，使用新的 `AIRLOCK_DB` 路径，保留旧库与审计，不自动重置现有数据。完整配置见[运行手册](docs/OPERATIONS.md)。

## MCP 与工具接入

MCP host 启动 `python -m airlock.mcp`，配置 `AIRLOCK_URL` 和仅 agent token。工具包括 `sql_execute`、`action_status` 及当前身份可发现的注册上游工具。收到 pending 后使用 action ID 查询；超时或未知结果时查询原动作或复用原幂等键，不直接创建另一笔写入。

服务端 `/mcp` 提供所测的无会话 Streamable HTTP JSON 子集；注册上游可使用 JSON 或会话/SSE。上游工具需要明确的影响、CAS、幂等和收据契约。OIDC access token 验证 issuer、audience、签名、有效期和主体路由，不从 token 中接受任意扩权角色。

GitHub 适配器固定仓库和 Issue 创建动作，通过受控中转或配置的服务身份执行。接入与故障处理见[闭环运行手册](docs/CLOSURE_RUNBOOK.md)和[技术契约](docs/SPEC.md)。

## 隔离部署

可信操作者配置三个独立随机密钥后运行 `docker compose up --build airlock`。服务端独享数据卷、连接入口及内部网络；Agent 仅在内部网络，发布端口限 loopback。凭据不提交 Git。

```bash
python scripts/docker_smoke.py
python scripts/upstream_isolation.py
```

这些检查自行创建唯一临时项目和合成测试资源，验证权限、网络、服务端卷/凭据隔离、重启及审批效果，仅清理自己的资源。生产身份平台、长期独立保管和通知渠道仍需对应环境验证。

## 测试与证据

```bash
python -m pytest -q
npm run check
npm test
python -m benchmark.generate
python -m benchmark.evaluate --split test --output evidence/benchmark-test.json
python -m playwright install chromium
python scripts/browser_smoke.py
python scripts/browser_edges.py
```

完整命令、官方 MCP SDK、容器集成、故障注入与产物门禁见 [CODEX_REVIEW.md](CODEX_REVIEW.md)。CI 保存真实子进程退出码、JUnit、源码 ZIP、逐例结果、截图和哈希清单。曾出现的 tee 掩盖 Docker 失败记录继续保留；每个结果都以对应源码和原始收据为依据。

已核验源码 `533726a` 及交付 `699adbd` 的完整流水线各通过 687 项 Python、6 项 JavaScript、31 项原生浏览器检查。当前范围、原始目标和未完成验证见[验收报告](docs/acceptance/FINAL_REPORT.md)及[逐项矩阵](docs/acceptance/COMPLETION_MATRIX.md)。工程快照见[项目归档](evidence/project-checkpoint-20261004/README.md)。

200 条 / 40 模板族的 benchmark 为作者构造的合成策略回归，按族划分 dev/test。真实模型合成实验、协议互通、部署隔离和真人业务效果分别记账；合成一致率不代表真实危险召回率。

## 使用边界

当前 SQLite 适配器限制 schema、表、函数和操作，未知或无法预演的操作阻断。任意第三方工具、多租户列权限、通用生产灾备和任意 GitHub 修改操作尚未提供。

如果 Agent 可直接读写目标、取得审核凭据或控制服务端/宿主，就超出保护前提。HMAC 与检查点只能在声明的密钥和外部锚定前提下验证审计；检查点之后的尾部与所有密钥失陷有明确限制。模型、恢复与治理建议始终不能自动授权写入。

## 项目文档

| 文档 | 内容 |
|---|---|
| [开发计划](docs/PLAN.md) | 场景、架构和交付顺序 |
| [运行手册](docs/OPERATIONS.md) | 配置、启动、API、测试和故障处理 |
| [技术契约](docs/SPEC.md) | 状态、权限、请求与执行语义 |
| [威胁模型](docs/THREAT_MODEL.md) | 信任边界、攻击面和防护前提 |
| [评测方法](docs/EVALUATION.md) | 指标、数据来源、实验与限制 |
| [接入与运维](docs/CLOSURE_RUNBOOK.md) | 身份、工具、归档、通知和追踪 |

维护者接续时先核对真实分支、HEAD、工作区和 `origin/memory/progress`，再检查源码与原始证据。保留用户改动及历史验证，不重写历史。
