# GitHub 执行双向独立检查

基线 HEAD：`4e512df4c65e9b94b7f210ed5483e612efb5eec1`。基线工作区干净；`origin/main` 为 `704b5035cf69f9a6c40c44eecd84c0d0741de849`。已完整阅读本项目 `AGENTS.md`、`CODEX_REVIEW.md`、适配器及既有测试，核对 `origin/memory/progress:PROGRESS.md`。本报告属于独立子代理检查，不是真人研究结果。

## 发现和修复

**P2，可恢复的错误冲突：direct 创建响应与独立读取对账并发，后到者可能报告 `github_receipt_conflict`，尽管两次观察指向同一 Issue，第一次持久收据已经成功。**

`direct_receipt_race.py` 对两个完成顺序都构造确定性屏障。修复前 `baseline-race.log` exit 1：readback 先完成则 execute 报错；response 先完成则 reconcile 报错。每种情形的合成效果数均为 1，持久状态为 executed；没有重复写入、权限绕过或错误业务终态。现有 10 项适配器测试在该基线仍通过（`baseline-existing-tests.log` exit 0），证明该竞态未被旧回归覆盖。

修复仅对 direct 模式的 `github_response` / `github_readback` 两种可信观察来源允许元数据不同；其余效果字段仍要求完全一致。返回并保留第一次持久化的原始收据，既不追加发送，也不覆盖证据来源。relay 的凭据、binding、观察引用仍按原样精确比较。

新增四项回归：response/readback 两种先后 × 同一 Issue/冲突 Issue。成功方向返回原始收据且数据库文档字节不变；反向冲突仍抛错，重启后同键执行不发送。

## 实际复验

| 检查 | 结果 | 原始证据 |
|---|---|---|
| 原始竞态，两个次序 | FAIL，exit 1，缺陷基线 | `baseline-race.log(.status.json)` |
| 旧适配器 10 项 | PASS，exit 0 | `baseline-existing-tests.log(.status.json)` / XML |
| 原始竞态，修复后同一脚本 | PASS，exit 0 | `repaired-race.log(.status.json)` |
| GitHub/upstream/SQLite 定点 45 项 | PASS，exit 0 | `targeted-tests-v2.log(.status.json)` / XML |
| 真实子进程 `os._exit` 于发送前/后 | PASS，子退出码 73/74 为预期注入；外层 exit 0 | `independent-boundaries-v2.log(.status.json)` |
| 未授权、跨角色、同键篡改 | PASS，7 个凭据拒绝、1 个绑定冲突，未授权效果 0 | 同上 |
| 本分支全量 CI / 真实 GitHub API | NOT RUN，本子任务没有执行 | 由主代理整体复验；不能用本报告代替 |

实际崩溃检查使用单独的 throwaway 子进程及合成 target.db：发送前崩溃后 target 效果 0、动作 unknown；发送后崩溃效果 1、动作先 unknown，独立读取对账后 executed。两者重放都未重发，发送后的目标记录仍恰好 1。所有资源只在本目录下随机创建；没有请求外部 API，没有读取实际服务器/审核/审计凭据，没有操作已有数据库。

`independent-boundaries.log` 首次外层 exit 1 原样保留，原因是检查脚本在 Windows 上未显式关闭自己的合成 target SQLite 读取句柄导致临时目录清理 WinError 32；这是检查脚本清理问题。v2 增加 `contextlib.closing` 后通过，未修改应用逻辑或断言来规避失败。

已有定点测试还覆盖审批前不可 claim、拒绝后不可 claim、真实 loopback Gate→relay→receipt→audit 正常路径，持久单次 send、并发/重启、超时 unknown、请求/配置漂移、容量和过期、relay 精确读取、固定 GraphQL origin/node/result 绑定、SQLite 运行时拒绝。在已测范围内未发现未修复 P0/P1。

## 范围和交付

只修改 `airlock/github_adapter.py`（9 行）与 `tests/test_github_adapter.py`（53 行）。未提交、未推送、未合并。原始证据仅在本目录（Git 忽略），尚无永久保留承诺。其他代理的并发修改如实出现在后续 dirty 收据，未被覆盖。

修复后应用源 SHA256：`f07997fd71c421123ef06fc760c082d9563b5f4bf455307052376af06751c64b`；测试源 SHA256：`48211e9a33ff7853e5ad1af255be6bd812a2b366c07641a9e89a237f3c67bdfe`。基线应用源 SHA256：`911bccc5068288901ef8601c522e66023fed8c9b1f3b8d7c41dec1d7abbca663`。本次 tested_commit_sha 是基线 HEAD 加明示 dirty patch，不能写成该旧提交已包含修复；主代理应冻结新提交后复验。

真实 GitHub 专用服务身份、真实网络变化、跨进程与远端 GitHub 的原子性和真实用户参与均未在本子任务验证。适配器仍是 durable at-most-one-send，不是 distributed exactly-once；没有增加自动重试、自动批准、补偿或任意目标操作。
