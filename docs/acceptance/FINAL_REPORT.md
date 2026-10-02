# AIRLOCK 继续完善与复验报告

当前受控实现通过复验；原始完整目标仍未全部满足。全部126条记录已分别填写实现状态、验证状态、范围、代码、命令、真实退出码、原始证据和 tested_commit_sha，见[矩阵](COMPLETION_MATRIX.md) / [JSON](COMPLETION_MATRIX.json)。父项不能代替子项，“通过”仅限明确实测范围。

## 1. 当前实际实现的功能是否通过？

**通过当前声明范围的复验。** 最终应用提交为 `17ccd2c5942aa316ee94509109cc01fbca925a26`。本机177项 Python 测试通过，保留1条 Starlette TestClient/httpx 弃用 warning。[同SHA的完整Linux CI](https://github.com/Changxin-YR/AIRLOCK/actions/runs/36998200376)成功：177 Python、6 JavaScript、22条原生浏览器检查、Next.js构建、依赖扫描、真实Docker Compose隔离、官方SDK、Envoy和OpenTelemetry Collector集成，以及原始证据门禁通过。

Windows本机Compose的基础镜像认证请求仍网络超时，exit 1保留；本机Envoy/Collector容器实验另有成功收据。Linux成功不改写Windows失败。

真实DeepSeek-V4.1-Flash完成了合成任务语义评估、四臂消融、缓存/预算检查、注入边界和经真实HTTP闸门的拒绝后安全改道。独立reviewer是测试脚本，不是真人。未批准时目标保持1206行、余额总和1206000。

## 2. 最初规划的全部目标是否满足？

**否。** 126条含父项的记录：97条IMPLEMENTED、29条PARTIAL；104条限定范围PASS、21条BLOCKED_EXTERNAL、1条NOT_RUN。唯一NOT_RUN是C1父项的保守聚合状态：已测子项不代表通用接入目标完整验收。统计不是126个独立测试或完成率。

未完整关闭记录：G4、A2、C1、C1.3、C1.5、C8、C8.5、C11、C11.2、T1、T2、T5、B1—B4、B6、H1—H5、R1、R6、E1、E4、K1—K4、K6。

个人项目运行、可核实简历素材、创新边界和17组面试问答已交付；用户现场讲解能力不能代验。四条架构原则、L0—L4、原技术/体验指标与失败判据都保留。危险召回≥90%、真实非危险FPR≤10%、双人κ≥0.75、真人理解/决策/正确率、归并质量和日均审批指标仍缺真实数据，不能宣布达标。Next.js技术栈偏差通过实际迁移和复验关闭。

## 3. 哪些已经修复，证据是什么？

历史P1修复包括Windows JS MIME空白页、验收器遗漏失败、Windows stdio环境、受影响Starlette/UNC边界和审批TTL/版本绑定，失败证据未改写。详见[发现与修复](FINDINGS_AND_FIXES.md)。

| 本轮增量 | 代码与验证 |
|---|---|
| MCP Streamable HTTP与受控MCP上游 | mcp_http.py、upstream.py；官方SDK实际初始化/发现/调用、拒绝/错误、CAS和收据 |
| 跨进程持久策略激活 | policy.py、service.py；独立Python进程重载、失败保旧、重启、旧pending stale |
| 恢复分类和远端补偿 | recovery.py、upstream.py；源动作归属、独立审批、CAS、幂等、漂移不覆盖 |
| DeepSeek与持久CNY预算 | semantic.py；真实调用/usage/错误/缓存失效，638条账本导出；模型无批准权 |
| Next.js / React审批台 | frontend/app/page.jsx；真实API、hash CSP、14条常规和8条边界浏览器检查、移动长文本与键盘路径 |
| 审计轮换、检查点和完整率 | audit_keys.py、store.py、audit_schema.py；插入/重排/替换/删除/截尾、9状态字段和远端原执行声明关联 |
| 有界OTLP导出 | telemetry.py；503保留/重试、确定span ID、官方Collector接收、SQL/参数/凭据不入spans |
| CEL映射实测 | container_integrations.py；官方Envoy1.39.1容器的12例受限布尔/比较映射，明确错误语义差异 |
| 研究和CI工具 | benchmark/research.py、ablation.py；四臂逐例及分层、κ/真人A-B工具、真实退出码和artifact校验 |

初次600次四臂模型调用有14次无效schema，全部保留失败并阻断；开发集诊断重放又复现2次reason超长。新增无效输出诊断证据及简短理由指令，严格长度上限不变；10个开发失败样例在v2指令下全部有效。原负结果未回写，未宣称v2全量重跑。远端stale/failed收据的完整率检查改为验证其原持久执行声明，避免合法路径误报；缺失声明反例仍失败。

## 4. 哪些仍缺功能？

通用第三方MCP工具仍需预演、版本CAS、结果收据与恢复契约适配；域名/DNS安全管理、OAuth audience/生产SSO、会话或SSE上游尚未实现。当前支持固定SQLite和注册HTTP/stateless MCP JSON契约，未宣称任意工具零适配透明代理。

尚无通用外部工具影响估算/灾备适配器、生产多租户/字段级PII导出治理或全工具沙箱。外部WORM存储、生产告警、第三方网络部署未落地。签名检查点与独立保存工具已实现，本机普通文件不能代替WORM。

这些缺项保留PARTIAL或作用域限制。所有支持的写入、补偿、批量决定继续独立审批；模型建议、可逆性、剩余预算和学习建议没有自动批准权。

## 5. 哪些代码完成，但缺真实验证？

| 项目 | 已有结果/工具 | 仍缺真实输入 |
|---|---|---|
| 多来源benchmark与语义指标 | 200条冻结作者合成、逐例/分层/四臂真实模型结果 | 授权日常日志、可复现事故任务、独立业务危险金标及新保留集 |
| 双人标注和κ | 导入校验、裁决前统计、空集/退化处理 | 两名独立真人标注者；当前人数0、κ=null |
| 真人A/B、理解/正确率/疲劳 | 任务导入、平衡分配、前台计时、匿名导出与配对分析 | 用户确认暂无参与者；真人n=0，自动化导出被排除 |
| 真实使用治理效果 | 归并/预算/批量/安全shadow工具和指标 | 同任务质量金标、活跃用户日、实际审批次数/错误率 |
| 生产与生态 | 可部署代码、真实容器、资料核对、未发送讨论稿 | 第三方授权、生产环境、外部采用/评审与用户本人演示 |

真实模型凭据/预算障碍已解除；剩余模型效果障碍主要是独立业务数据及金标。OpenAI备用provider本轮仍只做离线契约。

## 6. 代码和证据实际提交到哪里？

应用代码已推送独立分支 `codex/full-audit-2026-10-02`；[PR #1](https://github.com/Changxin-YR/AIRLOCK/pull/1)保持草稿、未合并。实际main仍为 `704b5035cf69f9a6c40c44eecd84c0d0741de849`。报告/证据提交与应用测试SHA分开，最终报告提交由memory/progress的STATE.json精确记录。

本轮载荷在 `evidence/continuation-20261002/`：原始日志和真实退出码、JUnit、PNG、逐例消融、合成账本导出、异常输出、容器日志、CI元数据。首轮审查证据继续保留。

完整Linux包 `ci/acceptance-17ccd2c.zip` 已下载并核对服务端SHA256、57个载荷文件大小/哈希，再运行独立证据校验器，exit 0。ZIP、校验收据、job原始日志随Git归档；Actions原包到期 **2026-12-31T10:55:52Z**。Git副本无自动到期，依赖仓库及备份，不是WORM。另保留400024b成功CI完整ZIP。见[保留期限](EVIDENCE_RETENTION.md)和[交付定位](DELIVERY_STATE.json)。

真实模型638次调用，622次有效、16次无效。同一持久账本将用户预算保守解释为本轮合计 **¥3**；按官方高峰价计入失败预占后的占用 **¥1.11779816**，有效调用已知usage估价 **¥0.84922816**。这些不是供应商账单，未做实际扣费对账；没有更换账本重置预算。

本机60对合成HTTP只读开销：增量均值8.838ms、p95 11.368ms；30写样本静态规则p95 0.102ms、预演p95 11.125ms。并发1、热态、1206行，未外推生产性能。

## 7. 是否仍有阻止验收通过的P0/P1？

**当前声明且已实测范围内，没有已知、未修复且可复现的P0/P1。** 这不代表未实现生产适配器或任意外部工具的安全认证。

全原始目标仍不能验收通过，原因是功能范围缺项及真实数据/真人验证缺口。模型负结果、Windows Docker网络问题和未知指标均保留。后续先核对main、工作分支、memory/progress，再按逐项目命令及所缺最小输入复验。
