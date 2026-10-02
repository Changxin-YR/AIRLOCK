# AIRLOCK 执行记忆

更新：2026-10-02。本分支用于接续，不是验收证明。必须读实际 main 代码、退出码和产物；禁止再次清空仓库。

## 用户要求与冻结范围

个人 AI 全栈简历/面试项目；ChatGPT 实现，Codex 独立验收。使用 memory/progress 保存真实进度，保留历史，不 force-push。

定位为服务端 SQL 审批与受限执行实验室。固定 SQLite 合成 customers 表，初始1206行；并非通用工具透明代理或首个 HITL。前端为无需构建的原生 ES Modules，不是 Vue/Next.js。真实 LLM、真人 A/B、生产连接器、多人路由/SSO未完成，不能编造。

## 当前 main

525ea8fe2909230d41e15526bbc1e0652529c2b9
root tree: 699cceac667b3de99fcb8a9efde9a7d746909261

提交链：
- 1f5d33b：清空旧当前文件，保留历史。
- 67df890：将之前未提交的源码对象恢复并正式发布完整 MVP。
- 0433671：增加官方 MCP SDK 互通、真实 Docker smoke、证据清单及手机时延格式。
- 6544e63：修正 tee 管道掩盖失败；逐命令退出码收据、JUnit必需测试和产物门禁；失败前保留 Docker 日志。
- 525ea8f：日志证明容器健康但内部网络无宿主端口发布；服务器改为 ingress + protected，Agent仍只有protected。增加拓扑/端口边界检查，提交 PLAN/SPEC/THREAT_MODEL。

## 已知实际验证，不可只看 CI 图标

1. 67df890 / run 36962081780：原始日志 Python80通过、JS5通过、原生浏览器9项通过。先前本地 loopback 受限的缺口在该runner补测。
2. 0433671 / run 36963123248：原始日志 Python81通过（含官方SDK）、JS6通过、native9通过；但 Docker 启动检查失败、没有 docker-report。虽然GitHub标绿，原因是旧tee管道丢失退出码，不能算整体通过。
3. 6544e63 / run 36963919651：严格门禁正确标为failure；Python84通过（官方SDK+日志器回归）、native通过；Docker日志显示服务healthy但PORTS为空，compose port返回no port。这是部署网络配置问题，不是业务进程未启动。
4. 当前525ea8f已修正网络配置，尚未在本检查点读取新CI最终结果，不能提前写Docker通过。

证据artifacts：
- 67df890 artifact11208306871，sha256 8fc01d4045fa8644e46260efcfb37347b288a561d4aa130e81ef94ff54539f71。
- 0433671 artifact11208453501，sha256 e6d69a3c1bf3bd40aa3085a9aac31a834d1c8e4a5b977ce47300f66b4f13db74。
- 6544e63 artifact11208797786，sha256 fb44378eedf2466dc4952b8ee3c2ed5941ca6d94b3375853a814f39c85c81c25。

GitHub.download_workflow_artifact 返回的文件会自动挂载本轮 /mnt/data，可解包source.zip恢复源码。不要假定旧会话容器永远存在。当前容器 /mnt/data/AIRLOCK 可用，额外ci-*目录是对应运行的只读证据副本。

## 关键实现

三态策略；所有支持写入包括零变化都审批，预演失败阻断。SQLite编译authorizer限定表/函数/动作、资源预算，克隆预演区分命中与变化，保留样本和整表指纹。摘要绑定参数/策略/影响，执行前在BEGIN IMMEDIATE中校验TTL、版本和数据漂移；效果、终态、HMAC审计同库提交，不声称分布式exactly-once。Agent仅有agent token，不得获得服务器文件/数据库/reviewer/audit密钥/宿主管理权限。审计无外部锚点不能证明尾部完整。

MCP只sql_execute/action_status，pending不是成功；官方Python SDK已通过所测子集，不是完整规范认证或真实LLM行为证明。SSE仅通知。UI凭据只在内存，时间为不可信遥测。

合成回归200条/40族，dev120/test80按族拆分，固定SHA256 243854b51e7039324de4c31fa7a67af1a98ddc48b9c9edfbbac581a2c2f73af7。不能用合成100%写真实危险召回或假称独立标注/κ/人类提升。

## 下一步

1. 查询525ea8f新CI并下载原始产物，验证run_logged退出收据、verify_evidence、Docker报告；失败继续定点修复，不降低断言。
2. 补EVALUATION/INTERVIEW/RESEARCH、AGENTS.md、CODEX_REVIEW.md、LICENSE、最终README与验收记录。
3. 最终提交后读取真实CI结论、下载最终源码/证据，检查桌面/移动截图及文件哈希，生成可下载交付包。
4. 将本文件和可机读STATE.json更新为最终main SHA/证据/明确未完成项。不要把这些待办当已经完成。
