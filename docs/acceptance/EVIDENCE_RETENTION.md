# 原始证据去向与保留期限

最终应用测试SHA：`17ccd2c5942aa316ee94509109cc01fbca925a26`。报告归档提交另见memory/progress。每个原始收据保留真实SHA、UTC、dirty状态、命令和退出码，旧实验不改写为最新代码结果。

| 位置 | 内容 | 期限与限制 |
|---|---|---|
| Git：evidence/continuation-20261002/ | 本机原始日志/收据、JUnit、PNG、逐例模型/离线结果、合成账本导出、失败历史、CI元数据 | Git无自动到期，依赖仓库/备份保留，不是WORM |
| Git：ci/acceptance-17ccd2c.zip | 最终Linux完整包，含source.zip、原始日志/图片、Docker/Envoy/Collector及逐例数据 | 4523055 bytes；SHA256 `a0d3854ab3a17581ae28e053cd0f34111ff2a5fe117c16d9fa6b22856df530fc`；已核对57载荷哈希，独立verifier exit 0 |
| Actions run36998200376 / artifact11222458811 | 上述ZIP原托管副本 | 90天，到期2026-12-31T10:55:52Z；Git副本不随其到期 |
| Git：ci/acceptance-400024b.zip | 前一个成功应用提交完整Linux包 | 4521492 bytes；SHA256 `be3bb07644f8a056a36e59039c7f52d68b50b6c1da73c1aedfb287e5ef57fc79`；57载荷和verifier已校验 |
| Actions run36997232536 / artifact11221817634 | 400024b原包 | 到期2026-12-31T10:45:27Z；Git副本无自动到期 |
| Git：evidence/full-audit-20261002/ | 首轮基线/失败/修复、本机结果、旧CI文本/元数据、故意exit23负对照 | 历史保留，不回写旧模型n=0或旧功能状态 |
| 旧Actions artifact11216944737 / 11218125469 / 11218408231 | 首轮Linux / 故意失败 / UI修复原包 | 分别到期2026-12-31T08:48:02Z / T08:53:28Z / T09:13:44Z；旧完整ZIP未入Git，旧文本不等于完整包 |
| 本机忽略目录ci/raw/、ci/raw-17ccd2c/ | 已归档ZIP的解压副本 | 仅本机；可从Git ZIP还原 |
| 本机忽略目录var/ | 私有ledger SQLite、临时数据库/配置、abcacfa CI ZIP缓存 | 不提交数据库或凭据；合成账本导出已入Git；本机文件无永久承诺 |
| 本机audit-inputs/与.firecrawl/ | 执行辅助文件、首轮含临时合成token的原始失败文件、公开资料缓存 | 不入Git；脱敏副本/来源/历史哈希另存；不提交第三方全文 |
| Git：docs/acceptance/ | 原始126索引、基线与当前矩阵、报告和校验器 | 原完整正文仍在docs/CODEX_FULL_AUDIT_BRIEF.md，随Git保留 |

`ARCHIVE_MANIFEST.json` 对本轮纳入Git的载荷逐文件保存字节数/SHA256，排除自己与忽略的解压副本。CI原manifest不改写；下载校验收据核对它覆盖的57个文件。

preflight、final、retest、final-code、final-17ccd2c分别代表各自源状态。latest Python和完整CI绑定17ccd2c；四臂保持v1提示与6adcc07收据，v2仅重放10个开发失败样例，未冒充全套v2结果。

模型导出仅含合成任务与响应，不含API key。初次14次无效schema只有错误类型/时间/状态；新增诊断后2次超长输出保留原文与schema_errors，不能据此证明最初14次全部同一原因。

本轮没有创建Release或外部不可变存储。后续报告提交触发的新Actions有自己的保留期限；应用代码不变时，17ccd2c完整包仍是本报告已核验应用证据锚点。
