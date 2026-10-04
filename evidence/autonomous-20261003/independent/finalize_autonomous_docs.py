from pathlib import Path
import json
import xml.etree.ElementTree as ET

root=Path.cwd(); base=root/'evidence/autonomous-20261003'; docs=root/'docs/acceptance'
ci=json.loads((base/'CI_FINAL.json').read_text()); artifact=ci['artifact']; sha=ci['tested_commit_sha']
matrix=json.loads((docs/'COMPLETION_MATRIX.json').read_text(encoding='utf-8'))
assert ci['conclusion']=='success' and ci['downloaded_sha256_verified'] and matrix['target_count']==126
assert matrix['tested_commit_sha']==sha
ci_pytest=json.loads((base/'ci/verified/pytest.log.status.json').read_text())
assert ci_pytest['tested_commit_sha']==sha and ci_pytest['exit_code']==0 and ci_pytest['tracked_source_dirty'] is False
n=len(list(ET.parse(base/'ci/verified/pytest.xml').iter('testcase')))
local_n=len(list(ET.parse(base/'local/final-runtime-pytest.xml').iter('testcase')))
local_status=json.loads((base/'local/final-runtime-pytest.log.status.json').read_text())
assert local_status['tested_commit_sha']==sha and local_status['exit_code']==0 and local_status['tracked_source_dirty'] is False
latency=json.loads((base/'ci/verified/latency.json').read_text())
report=f'''# AIRLOCK 全面修复与逐项验收报告（2026-10-03）

本轮已完成可在现有权限和环境内实施的代码、模型模拟与真实 GitHub 中转闭环。原始全部目标仍未满足。126项逐条记录保留在[矩阵 JSON](COMPLETION_MATRIX.json)和[可读矩阵](COMPLETION_MATRIX.md)，父项不能替代子项证据。具体人工步骤见[操作手册](../USER_ACTIONS_20261003.md)。

## 1. 当前实际实现的功能是否通过？

**PASS，限已声明和实测范围。** 应用提交 `{sha}` 已推送；[Linux CI {ci['run_id']}]({ci['url']})通过 **{n} Python、6 JavaScript、23原生浏览器检查**，含官方MCP SDK、Next构建、冻结benchmark、隔离Docker、上游网络、S3 Object Lock、Envoy/OTel、依赖审计与证据门禁。Windows本机同提交复验{local_n}项，exit0；v2模型浏览器回放在`a68b11b`通过，后续没有改模型或UI代码。现有Starlette弃用warning保留。

最终Linux只读额外开销p95为 **{latency['read']['added_ms']['p95']:.3f}ms**（阈值100ms），静态分类p95 **{latency['write']['static_ms']['p95']:.3f}ms**（300ms），隔离预演p95 **{latency['write']['preview_ms']['p95']:.3f}ms**（5000ms）。全部60对读样本和30写样本保留；并发1的合成基准不代表生产容量。

真实[Issue #6](https://github.com/Changxin-YR/AIRLOCK/issues/6)通过AIRLOCK审批→单次可信operator relay→GitHub完整回读→unknown对账→executed；6条审计验链有效。9项检查包括Agent审批拒绝、pending/rejected不可领取、重复claim拒绝、同键重查不重复创建。审核者是独立凭据的测试脚本，真人0。relay收据为`operator_attested`，不是专用PAT直接验证。真实写入收据保持原`5ca6fcf + dirty`来源；冻结后的相同适配器由全量CI复验，未改写旧SHA。

## 2. 最初规划的全部目标是否满足？

**否。** {matrix['counts']['implementation']['IMPLEMENTED']} IMPLEMENTED / {matrix['counts']['implementation']['PARTIAL']} PARTIAL；{matrix['counts']['verification']['PASS']}限定范围PASS / {matrix['counts']['verification']['BLOCKED_EXTERNAL']} BLOCKED_EXTERNAL。记录含父项，不是完成率或126个独立实验。

未关闭：G4、C8/C8.5、C11/C11.2、T1/T2、B1—B4、H1—H5、K1—K4、K6。独立危险召回≥90%、真实FPR≤10%、双人κ≥0.75及原真人体验/治理指标仍无合格真实数据。四条原则、L0—L4、四臂消融、失败判据和技术栈要求均逐项保留。

## 3. 已经修复什么，证据是什么？

| 本轮完成项 | 代码与证据 |
|---|---|
| GitHub Issue适配 | `github_adapter.py`固定仓库node ID/正文绑定，持久单次send、丢响应保unknown、只读回查；`test_github_adapter.py`及真实#6收据 |
| PKCE登录客户端 | `oidc_login.py`的state/nonce/S256、ID/access token绑定、私密导出、显式audience白名单；真实TLS模拟issuer与错主体/重放反例 |
| 登录慢响应P2 | 全令牌交换使用隔离子进程15秒预算，超时kill/wait；实际TLS慢headers/body反例 |
| 中转文件权限P2 | `private_files.py`在请求前建立Windows私密ACL/POSIX0700+0600；失败reservation阻止再次领取；实际ACL测试 |
| STS归档身份 | `archive.py`专用可选session token，空值拒绝、不会混入全局AWS凭据 |
| 告警投递 | `alert_delivery.py`固定HTTPS/pins、专用凭据、脱敏、持久event ID、丢响应与本地提交失败重试、恢复和目标变化；真实loopback接收器 |
| 模型角色填写 | 两模型各标注4条真实任务；DeepSeek另完成4条合成UI决定。模型schema及研究统计排除真人冒充 |
| 盲化缺陷 | 旧子模型包的授权语义ID泄漏被发现；原试验标blinding_failure保留，改opaque ID并用无历史新子模型重验；v2两模型8次UI决定通过 |
| CI尾延迟失败 | a68b11b原CI的只读开销p95=103.883327ms超过100ms。诊断发现每次申请两次连接/末连接checkpoint；改为一次连接保留两次独立FULL提交，新增失败/时钟/授权回归。阈值与样本没有更改 |
| SQLite运行时 | 官方WAL-reset修复来源、源码归档SHA256和amalgamation SHA3校验；CI/Docker固定3.53.1，实际source ID及加载库摘要绑定；不受确认版本在打开持久WAL前拒绝 |
| 拒绝启动顺序P2 | 最小反例显示先打开旧WAL后拒绝会在关闭时checkpoint；改内存检查先行，拒绝路径无持久连接，原始WAL字节保持不变。模拟旧版本，不宣称复现数据库损坏 |

完整原始退出收据在`evidence/autonomous-20261003/local/`；新增测试与旧P0/P1回归全部纳入CI。独立24并发反例只有1次send，错回读不能收敛。两模型对审批要求、可逆性均0/4一致，分歧原样保留；模型不能据此放宽服务端权限。

失败[CI 37085024673](https://github.com/Changxin-YR/AIRLOCK/actions/runs/37085024673)的完整ZIP与原始exit1/job日志在Git保留。旧Linux SQLite版本仅记录3.45.1，不能由此确定发行版是否回补；此次采用可核验的固定上游构建消除运行时不确定性。依据：[官方WAL-reset说明](https://sqlite.org/wal.html#walresetbug)、[3.53.1发布摘要](https://sqlite.org/releaselog/3_53_1.html)。Windows系统DLL未修改。

## 4. 哪些仍缺功能？

现有目标中可安全补齐的具体工具与实验入口已实现。任意第三方工具零适配代理、任意Shell执行沙箱、任意生产数据库灾备、多租户列级授权没有通用实现；未知工具仍fail-closed。新增GitHub仅创建Issue，不支持修改既有Issue/PR，也没有GitHub目标CAS或完全撤销通知的能力。

真实部署配置仍缺：服务器专用GitHub身份、真实IdP及账号策略、独立长期云桶/保管身份、实际告警接收端和部署侧调度。不能把本机模拟或一次中转当成这些环境已经部署。

## 5. 哪些代码完成，但缺真人或外部验证？

- 两名真实独立标注者、真实参与者与实际使用日：当前真人0、human κ=null、human A/B=null。模型填写及正确率不能替代。
- 代表性多来源授权任务和全新独立保留集：已有5条GitHub维护轨迹，只有一条经过AIRLOCK relay，仍是单一任务族。
- 真实IdP登录/MFA、专用PAT直连、长期云归档/真实STS、生产告警送达与恢复取回；代码和隔离反例已完成。
- 供应商项目账单及用户本人现场讲解。已成功读取官方余额API，但账户余额不是本项目发票。

真实DeepSeek障碍已解除；本轮8次新增调用全有效，累计650次（634有效、16历史错误），共用原账本保守预留/结算估价 **¥1.13770512 / ¥3**，增量¥0.01652272。有效usage估价累计¥0.86913512；不是实际账单。未重置ledger，未为v2盲包重试新增付费调用。

## 6. 代码和证据实际提交到了哪里？

应用提交`{sha}`在远端`codex/full-audit-2026-10-02`；[草稿PR #1](https://github.com/Changxin-YR/AIRLOCK/pull/1)未合并。main仍为`704b5035cf69f9a6c40c44eecd84c0d0741de849`。本报告/矩阵/归档的后续交付提交与memory提交分别记录在`memory/progress:STATE.json`。

完整CI包`{ci['zip_git_path']}`，{artifact['size_in_bytes']:,}字节，SHA256 `{ci['zip_sha256']}`，已核对GitHub digest、{ci['manifest_files_verified']}个manifest载荷、全部JUnit与真实退出收据，独立verifier exit0。Actions artifact {artifact['id']}到期`{artifact['expires_at']}`；Git副本无自动到期，依赖仓库历史/备份，非外部WORM。详见[保留表](EVIDENCE_RETENTION.md)。

个人任务原始上下文、原始模型填写、账户余额、私有ledger及配置只留本机var，不入公开Git；路径/hash在`PRIVATE_EVIDENCE_INDEX.json`，不宣称永久归档。公开Git仅保存脱敏汇总、真实命令收据及合成UI原始导出。旧失败证据保留。

## 7. 是否仍有阻止验收的P0/P1？

**当前已实现并实测范围内，没有已知未修复、可复现的P0/P1。** 这不是全域安全认证。全部原目标仍因上述21条真实验证记录受阻，不能宣告全目标验收通过。写入、补偿、批量决定继续需要独立审批；模型、可逆性、预算与学习建议都不授予权限。
'''
(docs/'FINAL_REPORT.md').write_text(report,encoding='utf-8')
(docs/'AUTONOMOUS_CLOSURE_20261003.md').write_text('# 2026-10-03 自主补齐与验证\n\n最新七项交账见 [完整报告](FINAL_REPORT.md)。原始证据在 `evidence/autonomous-20261003/`，未消除的真人/外部环境条件见 [操作手册](../USER_ACTIONS_20261003.md)。\n\n模型v1盲化失败单独保留；v2为新子模型无历史参与，仍是模型模拟。\n',encoding='utf-8')
findings=docs/'FINDINGS_AND_FIXES.md'
old_findings=findings.read_text(encoding='utf-8')
if 'F017' not in old_findings:
    findings.write_text(old_findings+f'''

## 自主补齐阶段（2026-10-03）

最终源码`{sha}`，CI {ci['run_id']} 的{n}项Python与全部其他门禁通过。以下为子模型独立代码审查、隔离反例及主执行者复验，未宣称真人独立评审。证据前缀`evidence/autonomous-20261003/`。

| ID | 严重度/性质 | 发现与修复 | 原始证据与复验 |
|---|---|---|---|
| F017 | P2，中转凭据落盘 | 导出领取收据需要在发请求前保证权限；新增私密独占目录/文件reservation，Windows ACL及POSIX权限失败时不发claim | `local/private-output-tests*.log`、`tests/test_private_files.py`；旧工具/ACL解码失败日志保留 |
| F018 | P2，登录总时限 | 单个socket超时不能约束慢headers/body总耗时；整个token exchange置于15秒限时子进程，stdin管道不把授权码放argv | `tests/test_oidc_login.py`真实TLS慢响应、callback超时及私密导出；最终CI |
| F019 | 研究盲化缺陷 | 子模型v1任务ID含授权语义；改opaque ID，新无历史actor重做 | `models/v1-blinding-failure.json`、原v1报告、`models/v2/`；模型结果仍不进入human metrics |
| F020 | P1，性能验收 | CI 37085024673 read added p95=103.883327ms超过100ms。申请路径改为单连接、两个独立FULL事务；保留先提交过期/高水位和失败回滚 | 完整失败ZIP/exit1、`independent/profile_read_connections.*`；最终Linuxp95={latency['read']['added_ms']['p95']:.3f}ms。阈值/60对样本不变，不宣称已定位所有尾延迟来源 |
| F021 | 运行时安全加固 | 历史SQLite3.45.1缺少准确vendor回补记录；采用官方固定3.53.1及源码双摘要验证。现存WAL关闭会checkpoint，故内存版本检查提前到任何持久open前 | `sqlite/research.json`、`independent/guard*`；模拟旧版本而非复现损坏。`tests/test_sqlite_runtime.py`四种拒绝路径字节不变，CI/Docker实际加载source ID及.so hash与构建报告绑定 |

真实GitHub #6取得operator_attested收据、6条有效审计和9项边界检查；独立24并发只有一次发送，错误回读不收敛。GitHub无目标CAS，不能完全撤销通知，未知状态不重试mutation。模型语义建议、预算和恢复能力均未取得审批权限。
''',encoding='utf-8')
state={'record_type':'code_validation_and_delivery_anchor','actual_main_sha':'704b5035cf69f9a6c40c44eecd84c0d0741de849',
       'working_branch':'codex/full-audit-2026-10-02','tested_commit':sha,'code_push_confirmed':True,
       'documentation_commit':'Exact final pushed delivery SHA is recorded on memory/progress STATE.json.',
       'pr':{'number':1,'url':'https://github.com/Changxin-YR/AIRLOCK/pull/1','state':'open','draft':True,'merged':False},
       'ci':ci,'target_count':126,'counts':matrix['counts'],
       'not_closed_ids':[r['id'] for r in matrix['targets'] if r['verification_status']!='PASS'],
       'model':json.loads((base/'models/cost-and-provenance.json').read_text()),'human_participants':0,
       'original_goals_all_satisfied':False,'known_unresolved_p0_p1_in_tested_scope':0,
       'scope':'Bounded SQLite, registered CAS HTTP/MCP and GitHub append-only operator relay; PKCE local issuer and cloud/webhook fixtures do not prove actual production identity/custody.'}
(docs/'DELIVERY_STATE.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
retention=f'''# 2026-10-03 新证据与保留期限

应用SHA `{sha}`。来源收据保留原始SHA、dirty状态及退出码。

| 去向 | 原始证据 | 保留期限 |
|---|---|---|
| Git：`evidence/autonomous-20261003/` | 本机{local_n}项收据、真实GitHub脱敏回执、模型v1盲化失败标记、v2合成UI原始导出/截图、CI日志及全ZIP | 无自动到期；依赖仓库/备份，非WORM |
| Git：`{ci['zip_git_path']}` | 完整成功CI ZIP，含source.zip，{ci['manifest_files_verified']}载荷已逐hash验证；SHA256 `{ci['zip_sha256']}` | 同Git历史保留 |
| Actions：run {ci['run_id']} / artifact {artifact['id']} | 同一ZIP的托管原副本 | 90天，到期 `{artifact['expires_at']}` |
| Git：`ci/acceptance-a68b11b-failed.zip` | 未过延迟门禁的完整失败包，SHA256 `a509b48f43f31481e3f3022568d45f809a432db6347c81edec628a2835a2c778` | Git无自动到期；对应Actions artifact11260098507到期2027-01-01T01:09:49Z |
| 本机 `var/real-work/github-20261003/` | 原始个人任务/模型答案、账户余额、专用配置、私有账本 | 忽略，不入Git；无永久保留承诺。只公开路径/hash |
| 临时IdP/Webhook/S3/Gate进程与数据库 | 隔离验证目标 | 测试结束清理各自临时资源；不算长期独立云存证 |

本轮8次付费调用和GitHub实连在`5ca6fcf + dirty`阶段完成，后续代码冻结及全量CI绑定`{sha}`；v2浏览器绑定`a68b11b39c2c2ed41e18d9001b90b66dcb652ba4`，此后只修改连接复用、SQLite运行时及其验收代码。未将历史收据改写到新SHA。Git永久副本一词仅指无自动到期，不代表不可删除或外部WORM。

<details><summary>此前归档、失败记录及Actions期限（原文保留）</summary>

'''
old=(docs/'EVIDENCE_RETENTION.md').read_text(encoding='utf-8')
if not old.startswith('# 2026-10-03 新证据'):
    (docs/'EVIDENCE_RETENTION.md').write_text(retention+old+'\n</details>\n',encoding='utf-8')
print(json.dumps({'target_count':126,'junit_tests':n,'counts':matrix['counts']}))
