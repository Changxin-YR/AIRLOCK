# AIRLOCK · Agent Change Review

**智能体变更预检与审批工作台。** 先展示实际数据差异，再由独立的人类会话批准；执行时核对批准的计划和目标状态，用事务回执回答“到底执行过没有”。

个人开源工程作品，用于学习与 AI 全栈求职。不是通用安全网关，不宣称首创人工审批，与其他同名项目无关联。

## 可以实际做什么

- **三态决策**：授权读取和明确的单记录标签变更可以放行；范围过宽的变更阻断；其余受支持写入等待审批。审批不能覆盖禁止规则。
- **影子预检**：SQLite Backup API 获取一致性副本；在副本执行；按主键比较全部受管业务表，包含已知外键级联。没有完整证据就不写目标。
- **证据绑定**：请求、身份、策略、Schema、业务快照和到期时间组成不可变计划；审批人必须先取得相应视图。执行前在短写事务中复核，变化后返回 STALE。
- **事务回执**：业务修改与回执同事务提交；响应丢失、重复请求和进程退出后，通过原回执恢复，不盲目再执行。
- **Vue 工作台**：真实请求队列、直接/级联影响、字段 diff、审批/拒绝、只读审计、SSE 重连和轮询恢复、移动布局。审批状态不等于执行成功。
- **Agent 接入**：独立凭据的 HTTP 客户端、真实官方 MCP SDK stdio 服务、脚本演示。另实现带持久检查点的 DeepSeek 工具调用客户端，但本次没有外部模型凭据，真实模型推理尚未验收。

## 快速运行

环境：Python **3.13**、Node **22**。从本仓库根目录执行；Windows 推荐 WSL2，Python 虚拟环境激活命令按自己的系统调整。

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
npm ci --ignore-scripts --prefix apps/web
npm run build --prefix apps/web
python -m airlock.cli init --data-dir runtime
python -m airlock.cli serve --data-dir runtime
```

打开 **http://127.0.0.1:8080**。审批账号和随机密码保存在本机 `runtime/human/credentials.json`；不要发给 Agent。初始化只允许新空目录，重复执行不会覆盖数据库。换端口时初始化和 serve 都传同样的 `--port`、`--runner-port`。

登录后点击“发起演示请求”，可以提交读取、单条标签修改、三条客户归档、包含备注的删除和过宽删除。所有按钮发起真实受控请求，没有绕过或在线清库接口。数据是合成 CRM 夹具，不是真实客户资料。

独立脚本 Agent：

```sh
python -m airlock.cli demo review --env-file runtime/agent/.env
```

只提供 `runtime/agent/.env`。它不包含审批、元数据库或执行器秘密。**本地同账号进程不是强隔离**，需要验证受限 Agent 边界时使用下方 Compose。

## Docker Compose

```sh
python -m airlock.cli init --data-dir runtime
sudo "$(which python)" scripts/prepare_compose.py  # Linux：将两个服务数据目录交给容器 UID 10001
# 保留 agent、human 凭据目录仅归本机用户所有
docker compose up --build -d --wait
python scripts/compose_check.py
```

执行器只连私有网络并挂载目标库；网关挂载元数据库；Agent 不挂载任何数据或凭据卷，不接入执行器网络，不持有共享服务密钥。默认只向本机发布 8080。不要将 HTTP 演示直接公开到公网；正式公开需 HTTPS、Secure Cookie 和相应配置及独立审查。首次初始化使用空目录；不要与另一套本地运行实例共用正在写入的目标。

## MCP 与模型

```sh
python -m airlock.mcp_server --env-file runtime/agent/.env
```

在支持 stdio MCP 的客户端配置上面的命令和绝对路径。工具为 `db.query_rows`、`db.update_rows`、`db.delete_rows`、`airlock.operation_status`，没有审批工具。等待审批返回应用层 operation 句柄，不冒充原生 MCP Tasks，也不保证未经适配的客户端自动等待。

真实模型客户端（需要自己明确提供 API Key 和可用模型 ID；会消耗该账号 API 额度）：

```sh
export DEEPSEEK_API_KEY='通过安全方式设置，不提交到 Git'
python -m airlock.model_agent --help
python -m airlock.model_agent --model deepseek-chat '先查出前三条测试客户，再提出归档变更' --env-file runtime/agent/.env --checkpoint runtime/agent/run.json
# 人工审批后按原检查点恢复；不要重新创建同一任务
python -m airlock.model_agent --model deepseek-chat --resume --env-file runtime/agent/.env --checkpoint runtime/agent/run.json
```

不设置凭据会明确退出并报告 NOT_TESTABLE。检查点包含模型对话和工具结果，权限为 0600，不能上传到公共仓库。模型输出不构成授权，替代建议仍需经过新的服务端流程。

## 验证

```sh
python -m pytest -q
npm run build --prefix apps/web
python scripts/evaluate.py --out Evidence/evaluation.json
python -m playwright install chromium
python scripts/browser_check.py --out Evidence/browser
```

当前本地 **74 项测试通过**，包括真实子进程重启、目标提交后 `os._exit(73)` 恢复，以及官方 SDK 的实际 MCP stdio 往返。测试计数不是安全保证。浏览器、容器与依赖审查的最终状态查看 Actions 的对应 commit 和 `airlock-verification-<sha>` 产物，不把旧提交的绿色结果移植到新提交。

评测是 **28 个公开、开发者可见的合成契约回归案例**，不是盲测。19 个可完整预检并通过独立 Python 参考结果核对，9 个按不支持或无效请求处理，仍计入覆盖率分母。不能用这些结果宣称真实世界危险召回率、用户决策改善或竞品领先。真实模型实验和真人 A/B 实验均未开展。

## 范围与限制

只有注册的 `demo-crm` SQLite 资源、`customers` 结构化工具及受管备注级联；不收任意 SQL、Shell、连接字符串、MCP 上游或 URL。上限 10,000 条受管业务记录、16 MiB、有限条件与返回条数。拒绝未知 Schema、触发器、视图和外部能力。

使用全业务状态摘要，因此无关行变化也可能令旧计划失效。SQLite 单写者、单后台工作线程、有限任务容量适合个人演示，不是高并发生产架构。审计链能发现本地事件变化，不能防止掌握全部数据的管理员整体改写。没有自动回滚、累计风险预算、自动学习放行或“所有攻击都能防住”的承诺。

## 阅读入口

- [架构、安全边界与执行语义](docs/ARCHITECTURE.md)
- [实施状态及验证口径](docs/STATUS.md)
- [面试讲解与代码定位](docs/INTERVIEW.md)
- [Codex 最终独立检查任务](CODEX_REVIEW.md)

实现由本次对话中的 AI 辅助工程过程完成。个人贡献应如实说明范围定义、关键机制理解、测试复核与维护，不假称全部手写。历史保留；2026-09-30 按维护者要求从新的文件树重建。
