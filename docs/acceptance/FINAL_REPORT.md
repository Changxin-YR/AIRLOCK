# AIRLOCK 全面审查与增量修复报告

结论：当前已声明、已测的受控实现通过限定范围复验；原始完整目标仍未全部满足。126 条原记录全部逐项交账，没有删掉原目标或以父项代替子项。具体字段、命令、真实退出码、test ID、适用范围、余项和 SHA 见 [完整矩阵](COMPLETION_MATRIX.md) / [JSON](COMPLETION_MATRIX.json)。PASS 仅适用于该行 scope；PARTIAL＋PASS 不表示原目标完成。

## 1. 当前实际实现是否通过

冻结核心提交 `266ad9e9daedcbfd5183f0402d1d5227f4a2a0b4` 在 Windows 本机通过 151 项 Python、6 项 JavaScript、14 项原生浏览器检查，依赖扫描退出 0。官方 MCP Python SDK 1.26.0、独立进程 HTTP 上游、真实 SQL 效果、SSE、审批/拒绝、批量、补偿和指标均有实际运行证据。

[Linux CI run 36986102382](https://github.com/Changxin-YR/AIRLOCK/actions/runs/36986102382) 的全部作业/步骤成功，包括真实 Docker Compose、浏览器、完整测试、依赖扫描、逐例评测及最终证据校验。原始 job log 和 metadata 在 Git 证据目录。本机 Docker 镜像认证网络超时，`docker-smoke` 和随后 `evidence-gate` 均实际退出 1，保持失败记录，未冒充本机容器验证成功。

最后的指标表首列修复提交是 `b9de71085e9b3027b8127c4da6d7193d8f19ba88`。它相对 266ad9e 的最终代码差异仅 `airlock/static/governance.js` 的表 class 与 `style.css` 的对应宽度规则，工作流已恢复相同内容。`final-ui/` 在该 SHA 再跑 151 Python、6 JS、14 原生浏览器及语法检查，全部退出 0；已重新查看指标截图。[最终代码 CI run 36988565652](https://github.com/Changxin-YR/AIRLOCK/actions/runs/36988565652) 也已完整通过，包括真 Docker 和最终证据门禁。远端交付提交定位见 `DELIVERY_STATE.json` 和 memory/progress。

## 2. 最初全部目标是否满足

**否，部分实现。** 当前矩阵包含 74 条 IMPLEMENTED、52 条 PARTIAL；86 条 PASS（范围限定）、36 条 BLOCKED_EXTERNAL、4 条 NOT_RUN。这些统计包含父项，不能相加解释为独立测试数或完成百分比。

未关闭 ID：G4；A2、A3；C1、C1.2、C1.3、C1.5；C2、C2.4、C2.5；C4、C4.1；C5、C5.1、C5.3、C5.5；C7、C7.2、C7.4；C8、C8.5；C9、C9.3；C10、C10.2；C11、C11.2；C12、C12.1—C12.4；L0-1、L0-6、L0-7；T1、T2、T5；B1—B6；H1—H5；R1、R3、R6；E1、E4；D1；K1—K4、K6。此处包含已经在局部范围 PASS 的 PARTIAL 行。

个人项目运行及简历素材已有证据；创新叙述定位为影响证据、授权绑定和治理组合，没有首创/全面优于竞品结论。17 组面试问答已更新，但用户本人讲解与独立演示能力没有代验。四条架构原则和 L0—L4 原验收均逐项保留。

真实危险语义召回 ≥90%、真实非危险 FPR ≤10%、真人理解/决策效率、正确率、快速批准代理比例、真实归并质量和用户日审批次数均未宣称达标。失败判据 K1—K4、K6 的真实触发状态未知；保留阈值，没有通过更改定义来消除它们。D1 的 Next.js 偏差保持未关闭。

## 3. 已修复与新增内容

历史/审查问题：Windows JS MIME 导致空白页；证据校验器接受失败 JUnit/不完整产物；stdio 子进程遗漏 Windows 系统变量；受影响 Starlette 依赖与 UNC 前置校验。新增功能复验中进一步绑定审批 TTL/版本、阻断时钟回退，修复移动导航溢出及指标首列可读性。每项复现、根因、代码和原始证据见 [FINDINGS_AND_FIXES](FINDINGS_AND_FIXES.md)。

本轮安全实现增量：

- C1/C6：HTTP 和 stdio MCP 共用核心；操作者 allowlist 的独立 HTTP 上游，独立凭据、版本 CAS、持久授权执行声明、幂等收据及 unknown 恢复对账；多 reviewer 资源/风险路由与即时撤销。
- C2/C3：真实 cel-python＋安全 YAML 的受限表达式、三态和硬阻断优先；配置摘要、失效与失败回滚；克隆预演精确计数及审批快照绑定。
- C4：本地完整合成快照补偿、克隆恢复演练、单独路由/审批/审计，目标漂移后不覆盖。
- C5：可选真实 OpenAI Responses provider、严格 schema、超时/并发/持久调用与估算预算、结果缓存。模型只能加严，低风险建议没有放行权。
- C7/C8：影响与 diff-first 审批、精确确认、真实状态数据；请求分组、成员摘要绑定的批量决定、持久固定窗风险预算；学习建议只改变显示窗口，经 operator 明确激活/撤回，不自动批准。
- C9/C10：结构化拒绝与独立安全替代演示；有界真实模型 Agent 驱动工具；原始评估/审批/收据快照、关联 ID、HMAC 审计与原始回放。
- C11/C12：多来源数据/双人标注 schema、冻结/泄漏检查、κ、四臂消融和真人 A/B 导入/计时/导出/分析工具；真实阶段时延、token/价格来源、成本未知、不同缓存和治理指标。

所有支持写操作仍须独立审批；可逆、预算、模型建议和学习结果均不构成授权。上游执行后的网络/审计异常只对账原收据，不换新 action 盲重试。

## 4. 仍缺的功能与验证覆盖

以下是真实余项，保留在对应矩阵中：通用 MCP 上游透明代理与 Tasks/Streamable HTTP；通用可逆性/恢复分类和第三方恢复适配器；跨进程统一策略热更新/Envoy 兼容；生产 OAuth/SSO 及真实上游隔离；跨服务 OpenTelemetry exporter/告警和主动缓存失效计数；审计自动 key-id 轮换与外部截尾锚点；Next.js 前端迁移。当前 API/适配器只对明确支持的作用域给保证。

仍需扩展验证的项包括：全部失败/未知/过期状态的原生浏览器端到端组合、辅助技术/全部长文本、完整审计插入/重排组合、真实上游生产网络攻击面与高并发/冷缓存性能。工具实现可复现不等同这些验证已经完成。

## 5. 代码已具备，但外部效果受阻

| 项目 | 已交付工具 | 缺少的最小输入 | 当前真实结果 |
|---|---|---|---|
| 真实 LLM 风险/安全改道/成本 | `airlock/semantic.py`、`scripts/live_agent.py`、四臂 runner | 本项目授权的 provider/model/key、价格来源/生效日和预算 | live 调用 0；真实 usage、账单、语义效果为 null |
| 多来源 benchmark | Case/Annotation schema、冻结哈希、族隔离、逐例输出 | 授权脱敏真实日志/公开可复现任务，保留真实业务意图与来源版本 | 现有 200 条仍是单一作者合成策略回归 |
| 双人标注与 Cohen's κ | 独立标注校验、裁决前 κ、空/退化情况和手算验证 | 两名真实标注者独立记录、分歧与裁决记录 | 真实标注人数 0；真实 κ=null |
| 四组消融 | keyword / pure LLM / hybrid no-preview / hybrid preview | 同一冻结真实任务及上述模型授权 | keyword 已跑；三个模型臂 BLOCKED_EXTERNAL，n=0 |
| 真人 A/B | 浏览器随机平衡、首见计时/后台暂停、匿名导出、配对分析 | 知情参与者、真实业务任务金标、预登记样本与流程 | 真人 n=0；浏览器 automation 输出被分析器明确排除 |
| 生态/面试 | 最新资料核对、未发送议题草稿、17 组问答 | 真实采用/评审反馈、用户实际讲解 | stars=0/forks=0 的本次快照不等于未来状态；没有采用效果证据 |

没有为获取效果而调用未授权模型、动用生产数据或向第三方发帖。

## 6. 测量口径与原始证据

`evidence/full-audit-20261002/final/` 的每个命令具有 `.log.status.json`，列出原始命令、SHA、dirty 状态、UTC 时间、耗时和真实退出码。原始包还有 JUnit、逐例 JSON、PNG 与版本清单；`final-ui/` 绑定后续 UI 修复 SHA。

| 检查 | 实际结果与边界 |
|---|---|
| 固定合成回归 | dev 120/120；test 80/80 三态一致；支持 pass 额外拦截 dev/test 各 0/30；精确预演 dev 40/40、test 20/20。这些不是独立危险金标召回率 |
| 独立关键词基线 | dev 70/120、test 60/80；保留逐例错误，不以同一个 Gate 当独立 baseline |
| 本机配对只读开销 | 同一 1206 行目标、60 对随机交替、并发 1；增量均值 8.095ms，p95 10.356ms；保留带符号差值 |
| 静态规则 / 克隆预演 | 30 次写样本，p95 分别 0.061ms / 6.657ms；包含所有原始极值，不删慢样本；无真实模型/人工等待 |
| 原始无代理与代理对照 | 一次性合成目标无代理 1206→0；pending/拒绝保持1206，SELECT 安全替代返回1206，另一动作明确批准才0 |
| 真实 CI 失败传播 | run36986618577：临时 `raise SystemExit(23)` 作业失败，整次 failure，正常 verify success；临时作业随后移除，未改弱验证规则 |

完整 SHA、所有未满足 ID、各环境失败和依赖版本在矩阵中。没有前端编译构建步骤的原生 JS 项目只报告真实语法/测试结果。Starlette TestClient 的 httpx 弃用 warning 保留。

Git 中的本机原始证据和 CI 文本没有自动到期；完整 Linux Actions artifact 是 90 天临时包，尚未另行下载为永久 ZIP。具体 ID、digest 和到期时间见 [EVIDENCE_RETENTION](EVIDENCE_RETENTION.md)。

## 7. 交付与 P0/P1 结论

代码、文档与证据提交到独立分支 `codex/full-audit-2026-10-02`；[PR #1](https://github.com/Changxin-YR/AIRLOCK/pull/1) 为待审草稿。实际 main 仍为 `704b5035cf69f9a6c40c44eecd84c0d0741de849`，未合并 main、未 force-push。报告/证据归档提交只追加文档，不冒充新的应用测试 SHA。最终远端工作分支、进度分支和 CI 定位保存于 `DELIVERY_STATE.json` / `memory/progress`，并在交付时核对远端。

在当前已声明且已执行测试的边界内，**没有仍未修复并可复现的 P0/P1**。原始全部目标的验收仍不通过：部分功能缺项、真实模型/真人/外部数据验证缺失，不能用当前合成闭环通过替代全目标验收。

复现入口：`README.md`、`docs/OPERATIONS.md`；`python scripts/demo_comparison.py --output evidence/comparison.json` 为一次性合成演示。模型配置不会默认启用；真实研究导入后用 `python -m benchmark.research --help` 选择检查/分析命令。后续执行先核对 main、工作分支和 memory/progress，保留本次失败历史与原始目标。
