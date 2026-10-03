# AIRLOCK 全面修复与逐项验收报告（2026-10-03）

本轮已完成可在现有权限和环境内实施的代码、模型模拟与真实 GitHub 中转闭环。原始全部目标仍未满足。126项逐条记录保留在[矩阵 JSON](COMPLETION_MATRIX.json)和[可读矩阵](COMPLETION_MATRIX.md)，父项不能替代子项证据。具体人工步骤见[操作手册](../USER_ACTIONS_20261003.md)。

## 1. 当前实际实现的功能是否通过？

**PASS，限已声明和实测范围。** 应用提交 `4aca4073114b5b992460903abf33c3721f4f8063` 已推送；[Linux CI 37087612206](https://github.com/Changxin-YR/AIRLOCK/actions/runs/37087612206)通过 **348 Python、6 JavaScript、23原生浏览器检查**，含官方MCP SDK、Next构建、冻结benchmark、隔离Docker、上游网络、S3 Object Lock、Envoy/OTel、依赖审计与证据门禁。Windows本机同提交复验348项，exit0；v2模型浏览器回放在`a68b11b`通过，后续没有改模型或UI代码。现有Starlette弃用warning保留。

最终Linux只读额外开销p95为 **4.662ms**（阈值100ms），静态分类p95 **0.079ms**（300ms），隔离预演p95 **11.638ms**（5000ms）。全部60对读样本和30写样本保留；并发1的合成基准不代表生产容量。

真实[Issue #6](https://github.com/Changxin-YR/AIRLOCK/issues/6)通过AIRLOCK审批→单次可信operator relay→GitHub完整回读→unknown对账→executed；6条审计验链有效。9项检查包括Agent审批拒绝、pending/rejected不可领取、重复claim拒绝、同键重查不重复创建。审核者是独立凭据的测试脚本，真人0。relay收据为`operator_attested`，不是专用PAT直接验证。真实写入收据保持原`5ca6fcf + dirty`来源；随后冻结的适配器实现由全量CI复验，未改写旧SHA。

## 2. 最初规划的全部目标是否满足？

**否。** 111 IMPLEMENTED / 15 PARTIAL；105限定范围PASS / 21 BLOCKED_EXTERNAL。记录含父项，不是完成率或126个独立实验。

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

应用提交`4aca4073114b5b992460903abf33c3721f4f8063`在远端`codex/full-audit-2026-10-02`；[草稿PR #1](https://github.com/Changxin-YR/AIRLOCK/pull/1)未合并。main仍为`704b5035cf69f9a6c40c44eecd84c0d0741de849`。本报告/矩阵/归档的后续交付提交与memory提交分别记录在`memory/progress:STATE.json`。

完整CI包`evidence/autonomous-20261003/ci/acceptance-4aca407.zip`，1,504,050字节，SHA256 `da532d08ae18b911c9bc768d38f074c8e67abf81020258d9fa181f0e884afdb4`，已核对GitHub digest、84个manifest载荷、全部JUnit与真实退出收据，独立verifier exit0。Actions artifact 11260688999到期`2027-01-01T01:50:22Z`；Git副本无自动到期，依赖仓库历史/备份，非外部WORM。详见[保留表](EVIDENCE_RETENTION.md)。

个人任务原始上下文、原始模型填写、账户余额、私有ledger及配置只留本机var，不入公开Git；路径/hash在`PRIVATE_EVIDENCE_INDEX.json`，不宣称永久归档。公开Git仅保存脱敏汇总、真实命令收据及合成UI原始导出。旧失败证据保留。

## 7. 是否仍有阻止验收的P0/P1？

**当前已实现并实测范围内，没有已知未修复、可复现的P0/P1。** 这不是全域安全认证。全部原目标仍因上述21条真实验证记录受阻，不能宣告全目标验收通过。写入、补偿、批量决定继续需要独立审批；模型、可逆性、预算与学习建议都不授予权限。
