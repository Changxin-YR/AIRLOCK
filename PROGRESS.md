# AIRLOCK 执行记忆：个人 MVP 已交付，等待 Codex 独立验收

更新：2026-10-02。本分支记录实际进度，不替代代码、测试或授权。禁止再次清空仓库；保留 Git 历史，不 force-push。开始新会话先 fetch main + memory/progress，核对本文件与 STATE.json 的提交和证据。

## 用户目标与已冻结范围

个人 AI 全栈简历/面试工程项目，由 ChatGPT 实现，Codex 独立验收。定位是服务端 Agent 写操作审批与影响预演，不是首个 HITL，也不是任意工具透明代理。

当前限定 SQLite synthetic customers 表，初始1206行；Python/FastAPI/Pydantic、SQLite、模块化原生 JavaScript/CSS、最小 stdio MCP。前端不是 Vue/Next.js，原先 npm 环境受限后采用无需构建且已实际运行的实现。

## 最终远端代码与 CI

- main：704b5035cf69f9a6c40c44eecd84c0d0741de849
- Git tree：1715976a1e43f4cb6a56d0e6af12a07c9fd620e9
- 最终 GitHub Actions run：36965666756，completed / success
- run：https://github.com/Changxin-YR/AIRLOCK/actions/runs/36965666756
- artifact：11210150290，名称 acceptance-evidence，432627 bytes
- artifact SHA256：ae2ef02b26253686386338257b0b77352492366249aefb3b149eb00954c3417a
- GitHub artifact 保留期至2026-12-31；交付包应单独保存，不依赖临时下载URL。

已下载最终artifact，核对它的SHA256和manifest中25个文件哈希；七份逐命令退出码收据均为0。解包source.zip重算Git树，与上述远端tree完全一致。Markdown相对文件链接均有效；源码包不含运行密钥、数据库或字体文件。用最终源码的verify_evidence.py再次核验最终产物，退出码0。

## 最终实际结果

- Python：88 passed，1条上游弃用warning，5.54s；官方mcp Python SDK 1.26.0互通在其中。
- JavaScript：6项通过，语法检查通过。
- 原生Playwright：10项检查通过，mode=native_browser_e2e，无脚本错误；包括105条新只读记录后pending仍可见。
- Docker：real_docker_compose，进程exit_code=0；非root UID10001、能力位0、只读根、Agent无审核/审计密钥及服务器卷/配置/socket，不能伪造审批或读取控制表。
- 数据：独立测试审批前1206行，pending重启不自执行；批准演示删除后再重启仍0行，没有自动重新播种，审计有效。
- 网络：服务器ingress+protected双网络，Agent仅内部protected；宿主端口只发布到loopback。
- 合成评测：总200条/40模板族，dev120/test80按族切分；test三态80/80、支持只读误报0/30、支持写入影响20/20。这不是真实世界危险召回率。
- runner：Python3.13.15、SQLite3.45.1；完整依赖版本、原始日志、JUnit、逐样例输出和截图均在artifact。
- warning：Starlette引用AnyIO已弃用的BlockingPortal别名；未隐藏，不是本轮功能失败。

最终原生截图逐张查看：桌面viewport1440×1100，PNG1440×1513；移动viewport390×844，PNG390×1844。影响数量、状态、SQL与样本diff、完整决策表单可读，移动端无横向溢出，时延单位不再单独换行。没有声称独立设计稿像素保真、WCAG或全浏览器安全认证。

## 实际修复历史必须保留

- 1f5d33b：清空旧当前文件，历史父提交d9499abc仍保留。
- 67df890：把先前已写入但未提交的源码对象恢复并发布MVP。
- 0433671 / run36963123248：官方SDK和原生浏览器通过，但Docker实际失败；旧tee管道丢失退出码导致GitHub假绿。这一轮不能算整体通过。
- 6544e63 / run36963919651：真实退出码收据、JUnit/产物门禁和日志器回归修复假绿，CI正确失败；保留的日志显示容器healthy但宿主PORTS为空。
- 525ea8f / run36964267162：修正服务器入口网络与Agent内部网络分离，真实Docker及严格门禁通过。
- 031489d / run36964992992：修复新只读历史挤掉pending，以及NaN/Infinity错误响应自身不可序列化；新增回归后88项Python、10项native及Docker通过。
- 704b503 / run36965666756：完成交付文档后，最终源码再次独立全套通过，并下载逐项核验证据。

## 关键工程约束

所有支持写入，包括零变化写入都需要独立reviewer。客户端不能用approved/risk/principal取得权限。受限克隆预演失败就阻断；精确只对当前支持模式与快照成立，未验证备份不编造时间，不承诺提交后恢复。

审批绑定请求、策略、影响与版本，在BEGIN IMMEDIATE事务内检查TTL、身份、摘要与数据漂移；业务效果、终态和HMAC审计同库提交。不是分布式exactly-once。重复键同内容返回原收据，内容不同冲突；结果未知时先查旧action，不能换键盲重试。

Agent不得拥有服务器文件/数据库、reviewer/audit密钥、Docker socket或宿主管理权限，否则不可宣传不可绕过。HMAC没有外部锚点，无法证明尾部未删或抵御服务器与密钥一起失陷。

MCP只sql_execute/action_status；pending不是成功，SSE只通知。官方SDK测试证明所测子集，不是完整规范认证或真实LLM行为证明。UI token仅内存，可见时间是untrusted遥测。队列必须先服务端筛选pending再分页。

合成集冻结SHA256：243854b51e7039324de4c31fa7a67af1a98ddc48b9c9edfbbac581a2c2f73af7。作者构造的相关变体，不是真实事故/独立人工金标，不编造κ或真人效率。内部计时不含最终持久化/提交、HTTP与人工等待。

## 交付文档

README.md；AGENTS.md；CODEX_REVIEW.md；LICENSE；docs/PLAN.md、SPEC.md、THREAT_MODEL.md、EVALUATION.md、RESEARCH.md、INTERVIEW.md（13组问答）、UX_QA.md、API_EXAMPLES.md；evidence/ACCEPTANCE.md保留031运行基线和失败历史，最终704由本分支STATE.json锚定。

## 未实现或未验证，不得改写成已完成

真实LLM业务行为与语义风险评估；真人A/B（n=0）、独立人工标注与κ；生产数据库/远端副作用连接器；SSO、多租户、多人路由；学习型自动降级；外部审计锚定；提交后恢复；任意MCP透明代理。Docker与浏览器smoke也不是全面渗透或规范认证。

## 接续唯一优先动作

让Codex从CODEX_REVIEW.md开展独立复核，首先核对main SHA、原始命令退出码、必需JUnit和真实产物；构造新的反例，不能删测试/降断言来变绿。若发现真实P0/P1，最小复现、定点修复、增加回归、全套重跑，再更新本分支。没有新需求或证据，不再从零重建，也不把这份记忆当验收事实。
