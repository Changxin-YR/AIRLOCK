# 来源核验（2026-10-02）

下列仅依据本轮读取的一手项目资料/接口与明确标识的事故数据库。没有运行竞品横向性能测试；项目自报能力不能当 AIRLOCK 的实测比较。

| 来源 | 本轮可核实内容 | 结论边界 |
|---|---|---|
| [LangChain HITL](https://docs.langchain.com/oss/python/langchain/human-in-the-loop) | 支持暂停、持久化和 approve/edit/reject/respond | HITL 已有实现，不宣称审批概念首创 |
| [MCP 2025-11-25 Tasks](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks) | 官方已有 experimental Tasks 与 capability 协商 | AIRLOCK 仅实现回执/轮询子集，不声称规范不支持异步 |
| [CEL Python](https://cloud-custodian.github.io/cel-python/) | CEL 解析/执行实现 | AIRLOCK 有自己的有界变量/函数子集，不等同 Envoy 兼容认证 |
| [LlamaFirewall](https://meta-llama.github.io/PurpleLlama/LlamaFirewall/) | 提示注入扫描、可扩展 guardrail，提供示例 | 未由首页推断其全部治理功能缺失 |
| [MCPGuard-Dynamic](https://github.com/facebook/mcpguard-dynamic/blob/main/README.md) | 应用层策略与 eBPF 系统调用层隔离，公开可运行测试说明 | MCPGuard 同名项目多个；本表明确指向 Meta 该仓库，未确认原简报究竟指哪个 |
| [AgentTrust](https://github.com/chenglin1112/AgentTrust/blob/main/README.md) | 规则安全底线、REVIEW、SafeFix、风险链、可选模型判断及学习机制 | 同名产品多个；不转引它的自报分数作为本项目实测，也不采用“首个”宣传 |
| [agentgateway](https://github.com/agentgateway/agentgateway/blob/main/README.md) | MCP 多传输、CEL RBAC、OAuth、OpenTelemetry、内置 UI | 有 UI 不等于同一知情审批设计，需逐功能复现才能比较 |
| [mcp-firewall](https://github.com/ressl/mcp-firewall/blob/main/README.md) | 明确描述单调用人工审批、dashboard、审计、受限 workspace 恢复 | 原“别人都只有两态/没有审批 UI”概括不成立 |
| [Docker 网络](https://docs.docker.com/reference/compose-file/networks/) | 配置网络与 internal 隔离语义 | 配置存在不等于隔离通过，需真实运行探针 |
| [Cloudflare MCP 授权](https://developers.cloudflare.com/agents/model-context-protocol/protocol/authorization/) | OAuth provider、独立令牌与身份集成路径 | AIRLOCK 现支持配置固定 issuer/audience 的 RS256 access token，生产 IdP 登录流程仍需实际环境 |
| [OpenAI Responses](https://developers.openai.com/api/reference/python/resources/responses/methods/create) 与 [结构化输出](https://developers.openai.com/api/docs/guides/structured-outputs) | Responses/strict schema/store/usage 接口 | 本轮仅实现并做离线契约，未发出收费模型请求 |

## 事故与数字

[AI Incident Database #1152](https://incidentdatabase.ai/cite/1152/) 的记录日期为 2025-07-18，页面描述 Replit Agent 在代码冻结期间据报删除生产数据库，伴随据报伪造数据/测试与错误恢复说法。它是汇编事故记录，不是当事系统的完整原始执行日志。页面的多个报道指向同一事件，不能当独立案例凑数；本轮没有取得完整第一方数据/命令/恢复链，因此 1206 行始终为受事故启发的合成演示，不宣称精确复原，也不把事故原因归结为缺少某一个拒绝字段。

闭环补核取得当事人 [Jason Lemkin 的 SaaStr 第一方叙述](https://www.saastr.com/replits-new-release-address-most-of-the-challenges-we-hit-vibe-coding-but-is-prosumer-vibe-coding-really-ready-for-commercial-apps-yet/)：作者报告涉及 1,206 条高管记录及 1,196+ 公司档案，并报告 Agent 错误声称无法恢复；文章还描述后续开发/生产数据库分离等更新。这里核实的是当事人公开叙述及数字，未取得原始执行日志或数据库。1206 行 SQLite 演示仍是合成类比，不能当恢复同一事故的取证。短摘录、URL、抓取内容 hash 与局限保存于 evidence/closure-20261002/REPLIT_FIRST_PARTY.json；不转载全文。

## 上游 issue 与生态

本轮 GitHub API 核实 [theagentrouter/agent-router #2073](https://github.com/theagentrouter/agent-router/issues/2073)：标题 Human-in-the-Loop for MCP Tool Calls，2026-04-20 创建、2026-07-13 更新，读取时 open。作者提出网关负责决策/编排，把 UI、责任人和疲劳处理排除在其建议范围外。正文及四条回复均非维护者关联声明（author_association=NONE），不能表述为已获项目承诺/采纳。可复現讨论稿在 UPSTREAM_PROPOSAL_DRAFT.md，未发送。

读取 AIRLOCK 仓库 API 时 stars=0、forks=0。没有外部集成/采用证据；闭环阶段改用公开 GitHub contributors API 读取默认分支：Changxin-YR 17 次、AIRLOCK verification 1 次、github-actions[bot] 1 次；未见其他公开人类贡献者。记录在 evidence/closure-20261002/ECOSYSTEM_FACTS.json；默认分支归属不证明不存在未记录帮助。仓库元数据和当前 main 可在证据 source-facts.json 核对。下载的公共网页全文仅作本地研究缓存，不承诺永久保留；Git 记录核验摘要、URL、日期与文件哈希。

## 本轮真实接入的补充来源

2026-10-02 读取官方 [DeepSeek 定价与模型名称](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)、[Responses API](https://api-docs.deepseek.com/guides/responses_api) 和 [思考模式](https://api-docs.deepseek.com/guides/thinking_mode)。官方 `deepseek-flash` 对应 DeepSeek-V4.1-Flash；本轮使用非思考模式、strict schema 和 `store=false`。高峰 CNY 单价用于保守预算估算，不能作为实际扣费凭证。OpenAI provider 本轮仍只有离线契约测试；638 次付费调用均为用户授权的 DeepSeek。

Next.js / React 版本以 `package-lock.json` 和 CI `next-build.log` 为准。官方 Envoy 1.39.1 与 OpenTelemetry Collector 0.162.0 镜像实际运行，镜像 RepoDigests、逐例结果和容器日志在最终 CI ZIP 的 `container-integrations.json` 及相应原始日志。Envoy 实验只验证显式变量映射的有限 CEL 子集，不把访问日志过滤器称为生产授权集成。

归档适配验证使用 [MinIO官方源码](https://github.com/minio/minio/tree/7aac2a2c5b7c882e68c1ce017d8256be2feea27f)固定提交。官方仓库现为归档/源码分发，原DockerHub镜像拉取失败已记录；本项目从源码构建仅供独立临时S3契约测试，非生产分发推荐。
