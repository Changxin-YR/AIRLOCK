# 审查发现与修复记录

审查基线：`704b5035cf69f9a6c40c44eecd84c0d0741de849`。本轮修复与复验由同一执行者完成；独立反例指相对原测试新增的反例，不代表作者与评审者独立。

| ID | 严重度 | 最小复现与修复前证据 | 根因与修复 | 复验 |
|---|---|---|---|---|
| F001 | P1 | Windows 原生 Chrome 打开 `/`，body 为空；`baseline/blank-console.json`、`blank-console.png` | 主机 MIME 注册表将 `.js` 映射为 `text/plain`；`ConsoleAssets` 显式设置 JS/CSS/HTML 响应类型，保持 nosniff | `test_console_javascript_mime_survives_host_registry`；`fixes/browser-native.log` 的 10 项真实浏览器流程通过 |
| F002 | P1（验收门禁） | `baseline/evidence-counterexample.log`：含额外失败 JUnit、缺少截图、不完整逐例结果的合成包被校验器以 0 接受 | 只验证少数用例名字及汇总字段；改为检查全部失败/error/skip、必需截图、原始语料哈希及逐例重新计算阈值；显式异常在 `python -O` 下仍生效 | `tests/test_evidence_gate.py` 的故意失败、优化模式和伪造汇总反例 |
| F003 | P1（Windows 验收路径） | `baseline/pytest.log`：87 pass/1 fail，stdio 子进程 TLS 初始化失败 | 最小环境遗漏 Windows `SYSTEMROOT`；补系统变量白名单，不继承 reviewer/audit 凭据；MCP 显式 UTF-8 输入输出 | 原失败测试通过，并增加中文/emoji 跨进程往返 |

| F004 | P1（受影响依赖与 Windows 静态文件边界） | 增量阶段 `fixes/dependency-audit-before-upgrade.json` 发现 Starlette 0.50.0 已知问题，包括 UNC 解析前外连风险 CVE-2026-48818；报告存在同一漏洞的别名重复，不能按条目数声称已复现等量攻击 | 固定 FastAPI 0.142.2 / Starlette 1.7.0 / Pydantic 2.13.5；`ConsoleAssets.lookup_path` 在 filesystem resolution 前拒绝 UNC/反斜杠 | `test_static_unc_path_rejected_before_filesystem_resolution` 验证没有进入危险解析；最终 `dependency-audit.log.status.json` 为 0。未向真实 SMB 主机发送凭据 |
| F005 | P2（新增 UI 移动布局） | 新增五个导航项后 390px 视口横向溢出 | 小屏导航换行、按钮保持可点击宽度 | `final/browser-report.json` mobile no-overflow；原生移动截图已人工查看 |
| F006 | P1（新功能审批绑定的防回归） | 独立改写 pending TTL 的反例要求拒绝；旧摘要字段不充分覆盖过期时间和自身版本 | `Gate._digest` 纳入 action ID、expires_at 和版本，执行前重算 | `test_new_boundaries.py` 的 TTL 替换反例；151 项全套通过 |
| F007 | P2（指标可读性） | `final/console-metrics.png` 中静态规则等名称受到通用 45px 首列样式影响而断裂 | `governance.js` 为指标表设独立 class，CSS 自适应首列并保留阶段名称 | `final-ui/` 原生浏览器复验，修复提交 `b9de71085e9b3027b8127c4da6d7193d8f19ba88` |

证据目录前缀：`evidence/full-audit-20261002/`。本机 Docker 原状及最终退出码均为 1：`auth.docker.io` 基础镜像认证连接超时，属于 `BLOCKED_ENV`，不是本机容器隔离通过。Linux CI run 36986102382 在相同核心代码 SHA 上真实运行 Docker 与最终证据门禁并成功。最终 pytest 保留 Starlette TestClient 的 httpx 弃用 warning，未统一屏蔽。

修复阶段 Python 95 项通过、原生浏览器 10 项通过，是中间工作树结果。冻结核心提交 `266ad9e9daedcbfd5183f0402d1d5227f4a2a0b4` 后，Python 151 项、JS 6 项、原生浏览器 14 项通过。最终 UI 样式提交另有 `final-ui/` 收据，不能将中间结果改称最终运行。

本轮增量补齐了 C1—C12 对应的受控 HTTP 上游、CEL/YAML、独立补偿审批、模型建议 provider、路由、预算/批量、shadow 建议、研究工具和指标。新增独立反例覆盖路由撤销、预算并发、新组成员、时钟倒退、模型非法 schema、远端已生效但响应/审计失败后重启对账等，详见逐项矩阵的 test_ids。新功能的加固项与历史基线缺陷分开描述。

CI run 36986618577 的 `intentional-negative-control` 子进程退出 23，GitHub 作业及整次 run 为 failure，正常 verify 作业 success。该临时作业在 `90bbbfb` 删除，历史日志保留。这证明实际失败传播路径，没有跳过原有检查来恢复正常状态。

当前已测边界内未发现仍未修复、可复现的 P0/P1；这不是对未实现适配器、生产部署或真实模型行为的安全认证。未完成的原目标仍列为 PARTIAL/受阻，不因本结论关闭。

## 继续完善阶段：真实模型与新增集成

本节证据前缀为 evidence/continuation-20261002/。最终应用17ccd2c本机177项Python通过；同SHA的Linux CI run36998200376通过全部177 Python、6 JS、22原生浏览器、真实Compose/Envoy/Collector及证据门禁。新增反例仍由同一执行者完成，不虚构独立评审人员。

| ID | 严重度/性质 | 发现及修复 | 原始证据与复验 |
|---|---|---|---|
| F008 | P1，新Next界面集成阶段 | Next内联初始化受原严格CSP阻止；静态打包生成逐内容SHA256授权，未加入unsafe-inline；长文本面板增加min-width约束 | next-login-diagnostic.png、browser-initial/保留初始观察；final和retest的native/edges原生检查、最终CI通过 |
| F009 | P2，真实容器测试路径 | Envoy默认entrypoint尝试chown而cap-drop ALL下失败；改显式非root执行/usr/local/bin/envoy，保留cap-drop与只读根；访问日志flush设50ms以得到完整采样 | integration-initial/envoy-container.log、ci/failed-6ad-job.log；retest/container-integrations.json和最终CI12例全通过 |
| F010 | P2，真实模型可用性及诊断 | 原消融14次schema异常fail-closed；dev诊断复现2次reason过长。新增保存原输出/schema_errors；v2要求≤300字符，严格max800不变 | final/ablation-live-*.json、final/model-diagnostics.json、retest/model-contract-recheck.json；10个dev重放全部有效，原负结果不覆盖 |
| F011 | P2，审计完整率误报 | 合法远端CAS stale/failed收据不重复携带reviewer字段；完整率改核对先前独立持久执行声明，缺少声明仍判缺失 | tests/test_audit_completeness.py；final-17ccd2c/pytest.xml及最终CI通过 |

新增功能对应的独立反例包括：跨进程策略重载与重启；MCP真实HTTP协议拒绝/非法参数/无副作用；远端补偿归属/CAS/独立批准；审计轮换和检查点插入/排序/替换/删除/截尾；9状态完整率及明确N-A；真实Collector接收、503重试且授权不变；Next真实stale/expired/failed/unknown对账、长文本/文本注入、键盘/退出/CSP。逐项源码和测试ID在126矩阵。

没有新增自动批准路径。全原始目标仍受生产适配器、独立真实数据和真人研究缺口限制；上述受控复验不构成全域安全认证。

## 闭环阶段：接入、归档和研究真实性

证据前缀 `evidence/closure-20261002/`。历史失败不覆盖，本地测试和 Linux CI 逐收据绑定源提交。

| ID | 性质 | 发现与修复 | 反例/证据 |
|---|---|---|---|
| F012 | P1，评估结论失真风险 | 将送审/阻断视为危险识别，会把合法写入送审错误计作模型命中。独立 predicted_dangerous 与授权三态拆开，未知覆盖率单列 | test_research / test_research_closure：保护率1而语义召回0；缺双人标签 acceptance_metrics=null |
| F013 | P2，跨环境CI可复现性 | 本机缓存的旧 MinIO 官方 DockerHub 镜像已无法公开拉取；Linux run37022113155 的归档步骤真实exit1。改为从官方固定源码提交构建，保存源码/二进制/image身份 | ci/failed-c3dd6ad-job.log、failed-c3dd6ad.json；新CI build/archive原始日志 |
| F014 | 新增接入安全加固 | DNS核验与连接使用同一已验证IP并保持TLS身份；token仅映射现有路由；SSE会话/响应绑定 | test_network真实TLS服务器与重绑定；test_oidc真实RSA签名/过期/错误audience/撤销；test_mcp_streamable会话替换/错误id/主动请求反例 |
| F015 | 审计与研究工具补齐 | 最小化摘要导出先按路由过滤；研究correctness由任务文件重算；理解题独立采集；真实日志按相同任务质量分母比较 | test_export/test_routing/test_research_closure；原生浏览器理解题自动化导出 |

真实模型新增4调用验证固定注册MCP上游。待审目标不变、拒绝后停止、独立批准一次生效；审查者为脚本。新增网络检查从Agent侧实测禁止直接访问上游；本机基础镜像拉取仍受阻，Linux结果单列。S3 API临时对象的COMPLIANCE拒删/缩短/降级不等于云账户长期保管，容器已清理。

源码构建在 run37023304336 已通过；归档启动探测遇到 botocore ConnectionClosedError 而提前失败。cc9d687 增加仅针对 ListBuckets 的有界启动重试和连接重置回归，变更不重试归档写入或业务执行，并保存脱敏容器日志。第二次失败日志与元数据也保留。

F016（P1，SSE身份租约绑定）：热重载把同一令牌映射到另一身份时，原连接只检查认证非空，可能继续发送原reviewer范围的动作ID通知；没有因此授予决定/执行权限。25d4f52改为每次通知前要求当前认证身份与连接主体完全相同，否则结束连接。test_sse_lease_ends_when_authenticated_identity_changes和真实SSE传输相关14项复验通过，最终CI另含该必需反例。

独立旧模块重放见 evidence/closure-20261002/sse_identity_replay.py 与相邻原始log/exit收据：直接从Git载入cc9d687的API模块，在相同固定依赖和临时数据库中模拟热映射。旧模块在主体变化后仍通知动作ID（467字节），修复版立即结束（0字节）；两者目标均保持1206行。仅心跳等待被加速，未替换身份或通知实现。


## 自主补齐阶段（2026-10-03）

最终源码`4aca4073114b5b992460903abf33c3721f4f8063`，CI 37087612206 的348项Python与全部其他门禁通过。以下为子模型独立代码审查、隔离反例及主执行者复验，未宣称真人独立评审。证据前缀`evidence/autonomous-20261003/`。

| ID | 严重度/性质 | 发现与修复 | 原始证据与复验 |
|---|---|---|---|
| F017 | P2，中转凭据落盘 | 导出领取收据需要在发请求前保证权限；新增私密独占目录/文件reservation，Windows ACL及POSIX权限失败时不发claim | `local/private-output-tests*.log`、`tests/test_private_files.py`；旧工具/ACL解码失败日志保留 |
| F018 | P2，登录总时限 | 单个socket超时不能约束慢headers/body总耗时；整个token exchange置于15秒限时子进程，stdin管道不把授权码放argv | `tests/test_oidc_login.py`真实TLS慢响应、callback超时及私密导出；最终CI |
| F019 | 研究盲化缺陷 | 子模型v1任务ID含授权语义；改opaque ID，新无历史actor重做 | `models/v1-blinding-failure.json`、原v1报告、`models/v2/`；模型结果仍不进入human metrics |
| F020 | P1，性能验收 | CI 37085024673 read added p95=103.883327ms超过100ms。申请路径改为单连接、两个独立FULL事务；保留先提交过期/高水位和失败回滚 | 完整失败ZIP/exit1、`independent/profile_read_connections.*`；最终Linuxp95=4.662ms。阈值/60对样本不变，不宣称已定位所有尾延迟来源 |
| F021 | 运行时安全加固 | 历史SQLite3.45.1缺少准确vendor回补记录；采用官方固定3.53.1及源码双摘要验证。现存WAL关闭会checkpoint，故内存版本检查提前到任何持久open前 | `sqlite/research.json`、`independent/guard*`；模拟旧版本而非复现损坏。`tests/test_sqlite_runtime.py`四种拒绝路径字节不变，CI/Docker实际加载source ID及.so hash与构建报告绑定 |

真实GitHub #6取得operator_attested收据、6条有效审计和9项边界检查；独立24并发只有一次发送，错误回读不收敛。GitHub无目标CAS，不能完全撤销通知，未知状态不重试mutation。模型语义建议、预算和恢复能力均未取得审批权限。

## 单人启动阶段（2026-10-03）

源码 `0d9be52e58c06601341c9ebbd8f50a2686ea1ebb`；CI 37093593956的458项Python、31项原生浏览器及其余门禁通过，独立校验92个载荷。证据前缀 `evidence/single-person-20261003/`。

| ID | 性质 | 修复与复验 |
|---|---|---|
| F022 | P2，研究统计 | 历史31cf0e7原函数重放：单人区间[1250,1250]改为null，均值保留；independent/single-participant-baseline.log保留前后值及exit0 |
| F023 | P2，新增导入工具边界 | 提交前审查发现case_id可成为CSV公式；输出前严格校验并拒绝，不静默改写ID。6个参数化反例及17项独立先导探针通过 |
| F024 | P2，新增日志工具计数 | 提交前独立审查发现重复来源会虚增已创建对象数；保留creation_claim_records，按correlation_key计算独立对象。反例2条记录/1个对象通过 |
| F025 | P2，新增收件箱请求边界 | 非ASCII幂等头可使str compare_digest抛异常；改UTF-8字节比较，错误头返回400，深嵌套JSON/慢体受限。pytest与独立5秒慢体反例通过 |

3项独立HTTP反例、2项退出竞态与115项冻结定点测试保留实际收据；这些测试没有增加真人、模型或外部渠道数量。历史失败证据继续保留。

## 双向复验阶段（2026-10-03）

本轮从工作分支 `4e512df4c65e9b94b7f210ed5483e612efb5eec1` 开始。先构造原实现反例，再修复；第二位子模型交叉复验并再次发现边界。子模型审核不计为真人评审。最终冻结提交及完整 CI 以 FINAL_REPORT.md 为准。

| ID | 性质 | 修复和双向证据 |
|---|---|---|
| F026 | P2，远端收据竞争 | 同一 GitHub Issue 的 create response/readback 按任一顺序完成时，保留第一次持久收据及来源；所有效果字段、relay 引用仍精确绑定。原两向竞态 exit1，修复后 exit0；实际子进程发送前/后骤停，效果0/1、不重发并可只读对账。 |
| F027 | P1，通知状态文件隔离 | outbox 原可向误指的其他数据库写表；加入 SQLite 运行时和数据库身份检查。交叉复验发现同列名缺约束库会静默漏告警，再补 PK/UNIQUE/NOT NULL/default/索引/表选项检查，合法旧库仍能迁移，错误库字节不变。 |
| F028 | P1，通知时间与恢复 | 旧健康记录可能覆盖新告警并发出假恢复；持久时间高水位拒绝乱序变化。交叉复验发现损坏高水位值可异常逃逸，现再次校验类型/范围并受控阻塞，不发送、不改库。 |
| F029 | P1，健康检查退出语义 | 不再信任与 status 矛盾的 recommended_exit_code；从合法状态推导0/2。身份/网络/报告未知产生当前 unknown 收据、exit4，不发恢复；投递问题exit3。独立真实HTTP链2→4→3→0，仅产生alert和recovery两个事件。 |
| F030 | P2，研究来源声明 | human/independent 必须为真实布尔 true；正式 JSON/JSONL 拒绝重复字段、非有限常量、空白身份和理由，正常 BOM/CSV 路径保留。声明本身不证明真人身份或独立性。 |
| F031 | P2，理解题金标 | 绑定任务文件重算时先剔除浏览器 correctness 声明；没有理解题 gold 的任务不进入理解率分母，空分母保持null。 |
| F032 | P2，活跃用户日 | 治理记录只接受规范真实日历日期和明确的任务/参与者ID；按tuple计算用户日，非法日期不增加分母。 |
| F033 | P1，验收来源与汇总门禁 | 矩阵双向核对126原目标、父子命令/证据、实际汇总、JUnit结果、SHA、原日志和归档hash。删除收据、篡改子项或虚报全部完成失败。交叉复验发现异目录伪造收据可冒充冻结验证，现只有经当前CI清单hash绑定的真实收据可建立冻结依据。可执行验收脚本也纳入run_logged的dirty检测。 |
| F034 | P1，性能验收门禁 | 从原始配对样本独立重算均值/分位数，保留负配对差，拒绝丢行、重复、非有限和不一致摘要。交叉复验发现阈值边界可利用摘要容差，现严格使用重算p95判100/300/5000ms上限；原始样本恰等于上限仍失败。 |

公开原始证据前缀为 `evidence/bidirectional-20261003/`。每个中间检查绑定实际旧 HEAD、dirty 标记和源码hash，最终新提交CI另列。历史失败和反例不覆盖；含环境片段的早期Windows测试错误原文仅本机保留，公开索引列hash与原因。结构门禁通过不证明真人指标，原始105限定PASS/21外部受阻口径未被降低。
