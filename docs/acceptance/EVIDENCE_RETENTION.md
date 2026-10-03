# 2026-10-03 新证据与保留期限

应用SHA `4aca4073114b5b992460903abf33c3721f4f8063`。来源收据保留原始SHA、dirty状态及退出码。

| 去向 | 原始证据 | 保留期限 |
|---|---|---|
| Git：`evidence/autonomous-20261003/` | 本机348项收据、真实GitHub脱敏回执、模型v1盲化失败标记、v2合成UI原始导出/截图、CI日志及全ZIP | 无自动到期；依赖仓库/备份，非WORM |
| Git：`evidence/autonomous-20261003/ci/acceptance-4aca407.zip` | 完整成功CI ZIP，含source.zip，84载荷已逐hash验证；SHA256 `da532d08ae18b911c9bc768d38f074c8e67abf81020258d9fa181f0e884afdb4` | 同Git历史保留 |
| Actions：run 37087612206 / artifact 11260688999 | 同一ZIP的托管原副本 | 90天，到期 `2027-01-01T01:50:22Z` |
| Git：`ci/acceptance-a68b11b-failed.zip` | 未过延迟门禁的完整失败包，SHA256 `a509b48f43f31481e3f3022568d45f809a432db6347c81edec628a2835a2c778` | Git无自动到期；对应Actions artifact11260098507到期2027-01-01T01:09:49Z |
| 本机 `var/real-work/github-20261003/` | 原始个人任务/模型答案、账户余额、专用配置、私有账本 | 忽略，不入Git；无永久保留承诺。只公开路径/hash |
| 临时IdP/Webhook/S3/Gate进程与数据库 | 隔离验证目标 | 测试结束清理各自临时资源；不算长期独立云存证 |

本轮8次付费调用和GitHub实连在`5ca6fcf + dirty`阶段完成，后续代码冻结及全量CI绑定`4aca4073114b5b992460903abf33c3721f4f8063`；v2浏览器绑定`a68b11b39c2c2ed41e18d9001b90b66dcb652ba4`，此后只修改连接复用、SQLite运行时及其验收代码。未将历史收据改写到新SHA。Git永久副本一词仅指无自动到期，不代表不可删除或外部WORM。

<details><summary>此前归档、失败记录及Actions期限（原文保留）</summary>

# 本轮证据去向与保留期限

应用测试SHA `25d4f523bce65f7bb0dd769fa3ba4052b8bf11fb`；代码、最终报告提交、工作分支、PR、main与memory/progress分别记录。完整原始收据不改写旧tested SHA或dirty状态。

| 位置 | 内容 | 保留期限/限制 |
|---|---|---|
| Git：evidence/closure-20261002/ | 本地/CI日志、真实退出码、JUnit、PNG、真实模型轨迹、成本、来源摘要、126项基线与校验 | 无自动到期，依赖仓库历史和备份，非WORM |
| Git：ci/acceptance-25d4f52.zip | 成功Linux完整包，含source.zip及78个manifest载荷；SHA256 cdb3092b25ec8867d62c3943a0f9adedb7e0b7b63273be198e3934ba480d087c；1,397,386字节 | 已逐载荷核验并独立verifier exit0；Git长期保留 |
| Git：ci/verified/ | 原始CI可审阅载荷；source.zip仅保留在完整ZIP内 | 原manifest保持原值，未将Linux数据改成本机值 |
| Actions成功包11235800383 / run37026082667 | 上述完整包的Actions原副本 | 90天，到期2026-12-31T15:18:49Z；不影响Git副本 |
| Actions失败包 11233268064 / run37022113155 | 完整ZIP仅Actions；Git留完整job日志/元数据 | 2026-12-31T14:45:36Z |
| Actions失败包 11234600390 / run37023304336 | 完整ZIP仅Actions；Git留完整job日志/元数据 | 2026-12-31T14:55:35Z |
| 临时S3服务 | 实际COMPLIANCE保留契约、版本收据、拒删/缩短/降级与截尾检测 | 测试结束容器/tmpfs已清理；不是长期云归档，只有报告/收据在Git |
| 本机ci/raw/、.firecrawl/、var/ | ZIP解压、公共页面全文缓存、私有账本和本机配置 | 忽略，不入Git；无永久承诺；不保存密钥到证据 |

ARCHIVE_MANIFEST.json列出本轮Git载荷字节数/hash，排除自身与忽略的解压副本。证据校验命令、退出码和源SHA在matrix-validation.log.status.json与ci/evidence-verifier-25d4f52.log.status.json。公共资料只归档必要短摘录、来源、日期和抓取hash，未转载全文。

preflight含故意/实际失败和dirty工作树，不作为最终源提交通过证据。final本机主要绑定c3dd6ad；最终Linux绑定25d4f52。真实4次模型调用也保持c3dd6ad收据，后续另补SSE身份租约回归并完整复验，未将旧模型收据改成新SHA。上一轮638次、原v1消融、v2开发重放各自保留原SHA。

本轮没有部署外部永久云WORM、创建Release或合并main。源构建S3镜像只供隔离测试，源码和镜像身份记录在ci/verified/archive-image.json。

另有Git中间完整包 ci/acceptance-cc9d687.zip（SHA256 e7b48439c920447e6ce121676a57191bb6272fb1cbf2c523c94f431f841329bc，1,401,201字节），曾通过216例CI，但不包含随后SSE修复，不作为最终应用证明。其Actions包11235036337到期2026-12-31T15:03:27Z。旧展开副本ci/intermediate-cc9d687及新ci/raw-final均忽略，仅完整ZIP/选定载荷入Git。

<details><summary>上一轮归档与历史Actions期限</summary>

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

</details>

</details>
