# AIRLOCK · Agent Change Review

**先看清变更，再独立审批，最后只执行获批的那一份计划。**

这是一个用于学习与面试展示的个人全栈项目，不是通用安全产品，也不是已有同名开源项目的分支。Vue 3 审批台连接 FastAPI 控制面和独立 SQLite 执行器，验证智能体数据变更中的三个问题：影响证据、审批与执行一致性、提交后故障恢复。

## 可以实际做什么

Agent 通过 HTTP 或官方 MCP SDK 的 stdio 适配器提出结构化读取、更新、删除。影子快照计算完整受管数据 diff（包含已支持的外键级联）；策略给出 `pass / block / need_approval`。人类用独立账号查看证据、批准或拒绝。执行器在短事务内复核获批数据状态，并将业务修改和幂等回执一同提交。进程重启或响应丢失后，以回执核实结果，不把超时当作“没有执行”。

界面包含待审批队列、字段前后对比、证据范围、只读历史审批视图、事件时间线、可重复的合成演示和未知结果的重新核实。没有审批绕过按钮，没有将模型解释当权限的路径。

## 启动：本地演示

已验证开发组合为 Python 3.13、Node 22.16.0；其他 Python/OS 组合没有完整验收。先在仓库根目录执行：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.lock
npm ci --prefix apps/web
npm run build --prefix apps/web
python -m airlock.cli init
python -m airlock.cli serve
```

打开 `http://127.0.0.1:8080`，账号为 `reviewer`，**随机密码只保存在本机 `.airlock/reviewer.txt`**。初始化拒绝覆盖已有目录。Windows PowerShell 激活虚拟环境使用 `.venv\Scripts\Activate.ps1`；系统运行验证以 Linux 为准。端口冲突可用 `init --directory .airlock-new --origin http://127.0.0.1:8780`，随后 `serve --directory .airlock-new`；私有执行器使用 8081。

本地两个进程同属一个 OS 用户，适合开发，**不等于不可信 Agent 的隔离环境**。不要把真实生产库放进演示配置。

## 启动：容器隔离演示

需要 Docker Engine 与 Compose v2。准备配置需要上面的 Python 依赖，不需要本机安装 Node：

```bash
python scripts/prepare_compose.py
# 生成随机凭据和 .env；已有 .env 时拒绝覆盖

docker compose build
docker compose up -d --wait gateway runner
# 审批密码：.airlock-compose/reviewer.txt
# 网页：http://127.0.0.1:8080

docker compose run --rm -T agent
```

Agent 容器只挂载自己的服务凭据；没有目标库、审批密码、执行器凭据或 Docker socket，只加入 edge 网络。执行器仅在 internal control 网络中，网关跨两个网络。容器只读根文件系统、移除 capabilities、启用 no-new-privileges。完整威胁模型见 `docs/ARCHITECTURE.md`。请勿把 `docker compose config` 的完整输出或 `.airlock*` 目录公开。

## Agent 与 MCP

本地可信开发会话可以装载 **仅 Agent 专用** 的环境文件：

```bash
set -a; source .airlock/agent/client.env; set +a
python -m airlock.mcp_server
```

为 MCP 客户端配置该 Python 命令和上述两个环境变量即可。生产隔离方式优先使用 Compose agent 容器。实际工具为 `db.query_rows`、`db.update_rows`、`db.delete_rows`、`operation.status`、`operation.cancel`。调用返回持久操作句柄；客户端按建议间隔查询，人在工作台独立审批。**这不是原生 MCP Tasks，也不承诺所有客户端零改造。**

真实 stdio MCP → HTTP 网关 → 私有执行器已经有自动化测试。所测 SDK 为 `mcp==1.30.0`，协商协议 `2025-11-25`。其他版本需重测，不把“协议已经接通”说成“大模型已经调用成功”。

## 可选真实模型

`airlock/model_agent.py` 实现 DeepSeek Chat Completions 的非思考模式工具循环、待审批停驻、稳定幂等键与磁盘 checkpoint。只需要 Agent 凭据，不需要人类密码。模型输出始终经过后端参数与权限校验。

```bash
# 在只持有 Agent 身份的会话/容器中设置；不要把密钥提交 Git
export AIRLOCK_MODEL_API_KEY='你的真实服务密钥'
export AIRLOCK_MODEL='你的账号实际可用的模型 ID'
python -m airlock.model_agent '查询 2 条测试客户，然后提出合理的标签修改' --checkpoint /tmp/airlock-agent-run.json
# 批准后使用同一 checkpoint 恢复，不能换幂等键重新提交
python -m airlock.model_agent --resume --checkpoint /tmp/airlock-agent-run.json
```

当前交付没有真实服务密钥，因此 **live model 为 NOT_TESTABLE**；单测中的模拟 provider 响应明确标为 fixture，不计入真实模型接入成绩。Checkpoint 可能含业务文本，也不应公开。没有开展真实用户实验，不存在宣称的“三秒审批收益”。

## 检验与证据

```bash
python scripts/verify.py
# 另行安装浏览器后做完整页面验收
cd apps/web && npx playwright install --with-deps chromium && cd ../..
python scripts/verify.py --output Evidence/ci --browser
```

脚本保存实际命令、退出码、原始日志、JUnit、覆盖率、源码摘要和合成评测。GitHub Actions 另外验证 Docker 网络/卷隔离并上传截图和日志。**具体完成状态以对应提交的 Actions 结果与 `docs/VERIFICATION.md` 为准，不以此功能列表代替测试证据。**

200 个案例是 20 类、单作者标注的合成策略一致性检查；按家族划分 dev/test，完整数据公开。它们不是独立红队、真实事故日志、真实用户数据或通用危险召回率。详见 `benchmark/README.md`。

## 边界

仅支持注册的 `demo/customers` 资源、固定字段/过滤器、小数据集和准确的已知 SQLite Schema。只读也做字段授权。未知表、触发器、DDL、外部函数、任意 SQL、任意路径/连接串、Shell 均不支持。无恢复证据时显示“未配置”，不自动回滚。全库业务摘要较保守，无关行变化也会使旧计划 STALE。

元数据库与目标库并非一个分布式事务；回执保证限定在受控目标事务内，不能声称全局 exactly-once。审计摘要链可检测链内不一致，但不能抵抗能重写整库的管理员。账号与部署是单维护者演示级，不是多租户企业认证系统。公网部署还需要独立 TLS、日志运维、备份恢复验证、入口防护及外部安全审计。

## 阅读入口

`docs/ARCHITECTURE.md`：架构、不变量、状态机与取舍。  
`docs/API.md`：接口、错误与审批契约。  
`docs/DEMO.md`：可复现实验和关键源码。  
`docs/INTERVIEW.md`：按实际实现写的面试问题及答案。  
`docs/CODEX_REVIEW.md`：**Codex 最后复核任务**，不要求重写整个项目。

AI 协作声明：项目由维护者提出目标和约束，使用 ChatGPT 辅助设计、实现与测试；Codex 用于独立复核。不要把辅助生成代码描述为全部手写，也不要把未做的外部实验写入简历。
