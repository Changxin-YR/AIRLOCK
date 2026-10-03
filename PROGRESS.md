# AIRLOCK 自主补齐与真实GitHub中转交付（2026-10-03）

真实main仍为 `704b5035cf69f9a6c40c44eecd84c0d0741de849`，未合并。独立工作分支已推送 `31cf0e76156f0b5a408756d45068f1a318cf856c`；应用完整测试提交 `4aca4073114b5b992460903abf33c3721f4f8063`，两者应用源码diff为空。PR #1仍open/draft/unmerged。此前记忆检查点为 `15e901d8107e1a744ed2f71f99c11df91d3ddb5b`。

新增受控GitHub Issues适配器（固定repository node ID、持久单次send、unknown只读对账）、Public Code+S256 PKCE客户端、显式audience白名单、私密中转文件、STS凭据、持久Webhook去重/恢复，以及严格非人类的模型角色填写与UI回放。真实Issue #6完成AIRLOCK审批→可信operator relay→GitHub完整回读→executed，6条审计验链通过，9项边界检查通过；独立审核是脚本，模型不审批，PAT直接运行时路径仍缺专用身份。Issues #2—#5此前4次connector-only任务与本次受控实连分别记账。

发现并修复两个P2（中转文件权限、令牌交换慢headers/body总时限）；研究试验发现授权语义ID泄漏，旧v1结果标blinding_failure保留，v2改opaque ID并由无会话历史子模型重做。两模型在4例审批/可逆性上0/4一致，保留分歧；v2合成UI 8次决定通过、无业务副作用。真人0、κ=null，模型不计人类金标或因果A/B。

首个a68b11b CI37085024673功能项通过但read p95=103.883327ms超100ms，原完整失败ZIP/hash/job保留在Git。按原始profile优化为一次请求单连接、两个独立FULL事务，失败提交仍保存expiry/clock high-water，不削弱权限和审计。SQLite运行时官方来源、构建/保护与最终版本以源码、CI runtime报告和最终报告为准，旧CI版本不回写。新完整CI [37087612206](https://github.com/Changxin-YR/AIRLOCK/actions/runs/37087612206)success，实际子退出码/JUnit/原始载荷已核验；完整ZIP `evidence/autonomous-20261003/ci/acceptance-4aca407.zip`，SHA256 `da532d08ae18b911c9bc768d38f074c8e67abf81020258d9fa181f0e884afdb4`，84载荷已逐hash核对。Actions包11260688999到期2027-01-01T01:50:22Z；Git副本无自动到期，非WORM。

126条逐项矩阵：111 IMPLEMENTED/15 PARTIAL，105限定PASS/21 BLOCKED_EXTERNAL；原目标未全部满足，未删除阈值或以父项代替子项。真实人员、代表性数据、新holdout、真实IdP/MFA、服务器GitHub身份、长期独立云保管/告警与项目账单、本人面试仍需外部输入。详细可操作步骤在docs/USER_ACTIONS_20261003.md，不再要求用户写客户端或实验代码。

本轮8次DeepSeek新增调用全有效；原账本650次/634有效/16历史错误，保守预留或结算估价¥1.13770512/¥3，增量¥0.01652272；余额API前后HTTP200但账户余额不等于项目账单，金额留本机。未重置ledger、未为v2再付费。原始个人上下文/模型填写/余额/数据库/配置不入Git，脱敏汇总、收据、合成UI导出在evidence/autonomous-20261003，PRIVATE_EVIDENCE_INDEX只列路径/hash；本机无永久保留承诺。

下一次从本STATE和origin真实refs重新核对，再读源码和原始证据。不得回退用户工作或force-push，不合main，不把模型模拟补成真人结果。常规代码/合成测试与用户自有GitHub维护已授权；真实个人身份/MFA和参与事实不得虚构。

<details><summary>上一交接检查点（原文）</summary>

# AIRLOCK 用户操作交接与真实 GitHub 待办（2026-10-03）

用户已授权操作其GitHub仓库，并要求其他人工环节的详细步骤。本轮仅操作Changxin-YR/AIRLOCK，实际创建并回读核对Issues #2—#5：GitHub受控适配、真实语料、真人实验、外部身份/归档/告警/账单。没有操作无关仓库，main保持704b5035cf69f9a6c40c44eecd84c0d0741de849，PR #1仍open/draft/unmerged。

工作分支codex/full-audit-2026-10-02已推送5ca6fcf4acb5e4483a5bf2d6c995a62c0068184c。只新增/更新用户手册、README、报告接续说明和公开任务摘要；应用源码与25d4f523bce65f7bb0dd769fa3ba4052b8bf11fb无差异。217 Python/6 JS/23浏览器完整应用证据继续使用原已核验Git包，不重写原收据。本次交付CI37081776246已成功，job111083641483，原日志再次核对217 Python、6 JS和全部证据门禁通过。完整CI元数据与原job日志在HANDOFF_CI_20261003.json / HANDOFF_JOB_20261003.log。重复完整包仅Actions（artifact11259062939，SHA256 13ef02a92292b149f36d56401eddbaabcddb0f99a0d8cb9449375c62faac7d40，1,420,906字节），到期2027-01-01T00:22:11Z；原应用完整25d4f52包仍在工作分支Git中。

详细步骤：docs/USER_ACTIONS_20261003.md，包括GitHub细粒度Token（仅AIRLOCK服务实连时需要）、两人CSV独立标注、约12人探索性沙箱A/B、真实活跃用户日、Auth0 RFC9068公共配置和现有单一audience限制、独立S3 Object Lock保管及保留期选择、告警送达、DeepSeek账单和本人面试。公开步骤依据GitHub/Auth0/AWS官方文档；没有新建付费云资源或代办本人MFA。

本机var/real-work/github-20261003/connector-trace.json保存当前用户授权、工具输入/规范化输出及GitHub独立回读；annotation-pack/有两份4行空白CSV、共同事实、说明和manifest；TO_RETURN.md给出非密钥信息回传清单。已确认都被Git忽略。公开Git只保存evidence/github-handoff-20261003/summary.json及手册；原始个人日志和标注不提交。

这4次真实项目维护创建全部同一任务族，通过Codex GitHub连接器执行，未经过AIRLOCK审批；没有独立危险金标、没有正式benchmark导入、没有新增真人或活跃用户日。不能以此将21个外部受阻目标改为通过。当前没有项目服务专用GitHubToken和已验收GitHub写适配器；桌面连接器凭据不能自动复用到服务。后续适配不能假定普通GitHub接口拥有原子CAS和幂等写语义。

手册中3个CLI帮助命令退出0，5段PowerShell语法检查通过，实际创建后逐项核对标题/正文；两个CSV全部标签/人类声明字段仍空白。这只是交接工具与实际Issue核验，不冒充新的功能或人类实验验收。模型无新增调用：仍642次、626有效/16历史无效，累计预算估价¥1.1211824/¥3。126矩阵仍111 IMPLEMENTED/15 PARTIAL、105限定PASS/21 BLOCKED_EXTERNAL。

Git里的旧应用完整包保留期、历史失败与已修复P1见下方上一检查点及原始证据。下一步按用户手册处理真实外部输入；常规仓库操作已授权，不反复询问；账号注册/本人验证、真实人员、数据权限、费用和云保留期不能替用户编造。没有明确合并指令时不合main。

<details><summary>上一完整工程验收检查点（2026-10-02）</summary>

# AIRLOCK 闭环交付：受控工程通过，真实研究验证仍受阻

2026-10-02。开始接续时仍应先 fetch 并核对真实分支、HEAD、工作区、main 与 memory/progress。此文件是记忆，验收事实以原始收据和源码为准。历史进度保存在本分支 Git 历史；上一检查点 eb888b0447e266c2cea76292c360625343dee641。

## 实际交付

- main：704b5035cf69f9a6c40c44eecd84c0d0741de849，未合并。
- 独立工作分支：codex/full-audit-2026-10-02；远端 HEAD fac683600e79c2635cf8f9073b597d4c36846e4b。
- 应用源码测试提交：25d4f523bce65f7bb0dd769fa3ba4052b8bf11fb。代码/报告/完整证据提交68492cd04174de5c3ccd5cb3211cb34ee1fb2d7d；最终fac6836只校正报告一处测试数。应用源码与25d4f52无差异。
- 草稿PR https://github.com/Changxin-YR/AIRLOCK/pull/1 已更新，open/draft/unmerged。
- 126条原目标完整矩阵：111 IMPLEMENTED / 15 PARTIAL；105限定范围PASS / 21 BLOCKED_EXTERNAL，没有NOT_RUN。含父项，不是独立测试数量或完成率。
- 全部原始目标尚未通过。已知且可安全实施的受控功能和实验工具已完成，外部研究与生产接入不能用合成结果代替。

## 验证与修复

最终应用CI https://github.com/Changxin-YR/AIRLOCK/actions/runs/37026082667 成功，job110900936649：217 Python、6 JavaScript、23原生浏览器检查、Next构建、依赖审计、官方MCP SDK、冻结benchmark、真实Compose/受保护上游网络/S3 Object Lock/Envoy/Collector和研究/证据门禁全部通过。对应完整ZIP已独立验证78个manifest载荷和217条JUnit，verify_evidence实际exit0；矩阵126条与23份真实收据校验exit0。188个Git证据载荷与manifest逐个核对通过。

报告/证据提交68492cd的CI37027516945也成功。最终交付fac6836的CI37028190235已完整成功，job110908065123；原始日志再次记录217 Python、6 JS及全部证据门禁成功。真实元数据与原始job日志在本分支CLOSURE_CI_20261002.json / CLOSURE_DELIVERY_JOB_20261002.log。

新增闭环：OIDC RS256 access-token受信issuer/audience/JWKS与撤销、DNS/TLS实际连接绑定、MCP会话/SSE、独立S3归档连接器、operator健康/告警/Prometheus、按reviewer路由过滤的白名单导出、受保护上游网络、研究导入/双人模板/仲裁/κ/理解题/金标重算/治理工具。MCP真实SDK、来源事故与成本均保留原始证据。

新增P1反例：SSE长连接身份映射变化后沿用旧通知范围。25d4f52改为当前身份必须等于连接身份；独立加载旧Git模块重放得到467字节动作通知，修复后0字节，业务目标均1206行，无批准/写入越权。新增回归进入217项CI。另修正危险语义预测与授权保护率混算，缺标签不产生验收结论。完整修复清单见FINDINGS_AND_FIXES.md。

Windows Compose仍因auth.docker.io认证网络超时exit1，原日志保留；Linux成功不改写本机失败。两次中间CI失败（旧官方镜像不可拉取、只读启动探测ConnectionClosedError）已修复为固定官方源码构建与只读就绪重试，原日志保存。Starlette TestClient弃用warning保留。

## 真实模型与预算

用户已授权DeepSeek V4.1 Flash、本机DEEPSEEK_API_KEY，费用约每个3元；实际所有实验共用var/deepseek-continuation-ledger，保守累计预算硬上限¥3，不重新起账。本次新增4调用全部有效，真实模型→AIRLOCK→MCP counter证明待审无效果、拒绝后停止、独立测试审核批准后0→3且版本仅增1。该真实轨迹收据绑定c3dd6ad，后续修复后的CI绑定25d4f52，未改写旧模型收据。

累计642调用，626有效/16历史无效；保守预留/结算占用¥1.1211824/¥3，有效usage估价¥0.8526124；本轮4次增量¥0.00338424。均为估价，未核对供应商账单。无需继续付费调用。原600次四臂v1负结果保留；v2只复验既有开发失败样例，未冒称完整v2重跑。审核者是独立脚本，不是人类参与者。

## 剩余外部条件

未关闭原记录：G4、C8、C8.5、C11、C11.2、T1、T2、B1、B2、B3、B4、H1、H2、H3、H4、H5、K1、K2、K3、K4、K6。用户已明确目前没有真人，保留n=0、独立标注0、κ=null、真实召回/FPR/疲劳效果未知。需要授权真实业务日志、两名独立标注者、全新保留集和知情A/B参与者；工具与模板完整，不自动创造金标或参与者。

真实IdP发证/交互登录及MFA需要外部客户端配置；长期独立云桶保管与生产告警接收器、实际业务适配器、真实账单和用户现场讲解尚未验证。通用第三方工具需按真实目标实现preview/CAS/收据/补偿；不宣称任意工具零适配、任意Shell沙箱、通用生产数据库灾备或多租户列权限。

## 原始证据与保留期

Git的evidence/closure-20261002/包含原始日志、真实退出码、JUnit、PNG、真实模型轨迹和来源摘要。最终应用完整ZIP：ci/acceptance-25d4f52.zip，1,397,386字节，SHA256 cdb3092b25ec8867d62c3943a0f9adedb7e0b7b63273be198e3934ba480d087c。Actions副本11235800383到期2026-12-31T15:18:49Z；Git副本无自动到期，依赖仓库历史/备份，非WORM。

最终交付CI完整ZIP仅Actions：artifact11236286987，1,412,685字节，SHA256 8cc239d81fdac081a93ea455aff667d46e5de06b281f8d5eff79dacd6d004a9f，到期2026-12-31T15:36:38Z；其元数据和job日志在本memory分支。应用25d4f52完整包已在代码分支Git永久归档（无自动到期），不因重复交付CI包到期丢失应用证据。中间68492cd的Actions包11236520683到期2026-12-31T15:30:58Z。失败CI完整ZIP仍仅Actions，Git保存日志/元数据，精确期限见EVIDENCE_RETENTION.md。

临时S3测试容器已移除，不代表部署了永久云归档。数据库、密钥、私有ledger、签名下载URL、解压副本与公共网页全文未入Git。原始任务正文及126索引保留完整，未被旧MVP范围覆盖。

## 接续边界

当前实测声明范围无已知、未修复、可复现P0/P1；不代表全域或生产认证。Agent必须无服务器文件/数据库/reviewer或audit密钥/宿主管理权限；上游实际执行CAS与持久幂等收据。所有写入和补偿保持独立批准，可逆性、预算、模型和学习建议均不产生批准权。

接续入口为docs/CLOSURE_RUNBOOK.md及126条COMPLETION_MATRIX.json。外部输入可用后按各条retest_command复验；保留原始失败和历史tested_commit_sha。不清空、不覆盖用户工作、不force-push；未经用户授权不合并main。

</details>

</details>
