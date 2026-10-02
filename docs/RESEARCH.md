# 来源核验与不采用的宣传（2026-10-02）

## HITL已有实现

LangChain官方文档描述暂停、持久化和approve/edit/reject/respond，因此“开源方案只有放行/阻断”不成立。本项目讨论独立的服务端执行边界，不将已有HITL概念包装为首创。

来源：https://docs.langchain.com/oss/python/langchain/human-in-the-loop

## MCP工具与等待

官方工具规范说明工具发现、调用和结构化结果；本项目采用快速pending回执+状态查询是实现取舍，不证明规范不能处理长任务。官方Python SDK的通过仅覆盖测试所用接口，不是完整认证。

来源：https://modelcontextprotocol.io/specification/2025-11-25/server/tools
SDK：https://pypi.org/project/mcp/1.26.0/

## SQLite不是任意代码沙箱

authorizer在语句编译期间控制访问。本实现还限制表、函数、语句/数据/返回量与执行时间，禁用任意schema和外部访问。BEGIN IMMEDIATE的写事务用于本机同库再校验，不能外推分布式副作用保证。

来源：https://sqlite.org/c3ref/set_authorizer.html
事务：https://sqlite.org/lang_transaction.html
STRICT表：https://sqlite.org/stricttables.html

## 网络边界不能只看配置名称

Compose可以显式分配每个服务的网络，internal网络面向外部隔离。本项目实际诊断发现仅内部网络的容器健康但没有宿主端口发布；修正为服务器双网络、Agent仅内部网络，并用运行时检查限制发布地址为loopback。不能把网络命名或YAML存在当隔离验收。

来源：https://docs.docker.com/reference/compose-file/networks/
端口：https://docs.docker.com/engine/network/port-publishing/

## 对原始素材的保留意见

原envoyproxy/ai-gateway对应仓库在此前查询中迁移到theagentrouter/agent-router；#2073中的审批UI/责任与疲劳范围属于提案作者的建议，不是整个行业或维护团队的正式保证。没有据此宣称CNCF认可、外部采用或上游集成，也未向该issue自动发言。

参考：https://github.com/theagentrouter/agent-router/issues/2073

未重新还原AI Incident Database #1152的完整因果证据。因此1206行只作为合成演示，不声称精确重建事故，也不把伪造数据等行为归因于缺少结构化拒绝。没有核实的star数量、专家金标、人类效率和LLM成本不写成事实。
