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


## 单人启动交付（2026-10-03）

- 应用源码0d9be52e58c06601341c9ebbd8f50a2686ea1ebb，CI37093593956/job111118885655。92个载荷hash、source.zip SHA及458条JUnit/真实子退出码独立核验，verify_evidence exit0。
- 完整成功包纳入Git：evidence/single-person-20261003/ci/acceptance-0d9be52.zip，1,837,526字节，SHA256 83ded2be04f9e4e8e334144693a073f534acbd8292d647de44f993913108aecb。Git无自动到期，依赖历史和备份，不是WORM。
- Actions副本11263493490，到期2027-01-01T03:33:25Z；与Git副本分别记账。
- 新本机冻结定点收据、原生浏览器截图、独立边界反例、历史单人区间重放、矩阵校验收据和脱敏导入汇总均在evidence/single-person-20261003。ARCHIVE_MANIFEST.json逐文件记录公开载荷hash。
- var/single-person-20261003下的真实原始输入、标注表、当前快照及Issues #3—#5更新轨迹不进Git，无永久保留承诺。Git仅存对应路径/hash和数量，不含实际人员填写。
- 未新增外部云资源、付费模型调用或真人记录；原模型/失败CI等历史证据及各自保留期限继续有效。

## 双向复验交付（2026-10-03）

- 源码096b9bbbf9c113471eda1a713f9d0c860c95a348；完整CI37100296703/job111138333764。94个清单载荷、source.zip commit、588条JUnit及真实退出码独立核验，verify_evidence exit0。
- 完整成功包进入工作分支Git：evidence/bidirectional-20261003/ci/acceptance-096b9bb.zip，1,875,653字节，SHA256 68335fca51e8c0cc61b959f32aeb94018557983b1af1fc332a123d3099e5406a；无自动到期，依赖仓库历史/备份，不是WORM。
- Actions原副本11266455225到期2027-01-01T05:35:11Z。Git和Actions分别记账；后续文档交付CI使用自己的元数据和期限。
- 公开目录保留未修改基线、修复前反例失败、作者修复测试及第二方向复验。IMPORT_INDEX逐原文件映射，ARCHIVE_MANIFEST逐最终载荷hash；precommit dirty与冻结收据不混用。
- var/bidirectional-20261003/operations/targeted-tests.log和targeted-tests.xml的早期Windows错误可能含环境片段，仅本机保留；公开索引记录hash/字节/原因，原文无永久保留承诺。隔离临时数据库不归档。此前个人真实日志仍仅本机，未转为公开Git。
- 本轮真人完成0、付费模型调用0；未创建云资源、长期服务、Release或WORM归档。原失败CI历史不覆盖。

## 再次修复与双重复验交付（2026-10-03）

- 源码533726aa72eeeb71d5c28d81ac84ad7b1a23dd3c；完整CI37117971834/job111188360694。94个清单载荷、source.zip commit、687条JUnit及真实退出码独立核验，verify_evidence exit0。
- 完整成功包进入工作分支Git：evidence/closure2-20261003/ci/acceptance-533726a.zip，1,917,012字节，SHA256 1a77398592181042eab95aa1040298a877ac1bb5b3786d8feefb3797b7f6d4f9；无自动到期，依赖仓库历史/备份，不是WORM。
- Actions原副本11272472106到期2027-01-01T10:55:17Z。此期限仅适用该Actions副本；最终文档交付触发的重复CI有独立编号和期限，由memory/progress保存元数据、原始job日志和验证收据，重复ZIP仅Actions及本机var临时副本，无额外永久保留承诺。
- independent/保留171份作者/另一作者的原始失败、成功、源码和收据，以及最终只读审查报告；IMPORT_INDEX映射原路径，DOCUMENT_BINDINGS绑定文档，ARCHIVE_MANIFEST记录最终公开载荷hash。中间dirty测试不冒充冻结CI。
- 本轮S3 Object Lock只验证临时隔离服务的真实API语义，测试容器随后清理，不构成长期云归档。完整ZIP与结果在Git，生产WORM尚未部署。
- 本机var临时文件/数据库不归档，历史个人原始日志与凭据仍不入Git；本轮新增真人记录0、付费模型调用0。此前失败CI与原保留说明继续有效。

## 项目维护归档（2026-10-04）

- 源码7073fb76a2e46365fabe6f51a3765de267863890，完整CI37164846361/job111325559836。下载后核验94载荷、source.zip commit、703条JUnit和真实退出码，verify_evidence exit0。
- 完整成功包进入工作分支Git：evidence/project-maintenance-20261004/ci/acceptance-7073fb7.zip，1,940,695字节，SHA256 fb98b56d111cae2c1e318b012e6d0703022d4b62e938801e1a79872963a4b190。Git无自动到期，依赖历史/备份，非WORM；Actions原副本11288478711到期2027-01-02T00:24:25Z。
- 作者原始复现、16项回归、测试夹具错误及修复、独立7项子进程检查、52项定点与矩阵验证均保存真实SHA/dirty和退出码。最终交付重复CI的元数据/job日志/验证收据保存于memory/progress；重复完整ZIP仅Actions和本机临时副本，期限单独记账。
- 工程基线包evidence/project-checkpoint-20261004/AIRLOCK-project-baseline-699adbd.zip，2,835,750字节，SHA256 60bd67a5db7aa28c86f6b8743ce052b6a8986821bf0cf371257645ef5f87717e。该包仍绑定699adbd历史源码；历史已发布产物、原命令路径和hash由PROVENANCE.json/PREVIOUS_MANIFEST.json及原Git提交保存，未改写原始收据。
- 原目标、失败CI、真人0/模型本轮调用0和外部验证条件保持。个人日志、真实凭据、数据库和var临时文件不入Git。
