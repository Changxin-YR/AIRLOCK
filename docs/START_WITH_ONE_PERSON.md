# 一个人开始使用 AIRLOCK

当前流程以个人 GitHub 仓库维护为业务场景。你负责本人判断、登录和资源选择；程序准备、日志整理、统计与代码复验由 Codex 完成。模型状态、账单核对和本人面试暂缓，原验收项仍保留。

## 现在可以做的单人练习

“标注者 A、标注者 B”指两名独立的人；“界面 A、界面 B”指两种呈现方式。一个人可以体验两种界面，也可以提供自己的第一份标注。不要用两个编号把同一个人记成两个人。

在项目 PowerShell 运行：

```powershell
Set-Location C:\Users\27363\Desktop\airlock
.\.venv\Scripts\python.exe scripts/pilot_server.py --port 8766 --open-browser
```

浏览器入口为 `http://127.0.0.1:8766/`。这个独立练习页无需初始化审批服务、数据库或审核凭据。

1. 点击页面顶部的“下载练习任务”，保存 `pilot-tasks.json`。
2. 填一个匿名编号，例如 `pilot-01`，选择刚下载的任务文件。
3. 来源选“本人参与”，本人同意后勾选同意框，开始练习。
4. 独立完成 8 道 GitHub 维护情境题和理解题。页面只记录模拟决定，不调用 GitHub。
5. 导出匿名结果，保存到本机 `var/human-study/sessions/`，把文件路径告诉 Codex。重复练习需说明，不能增加参与人数。
6. 在启动终端按 Ctrl+C 停止页面服务。

这些题使用作者编写的合成情境和答案，适合检查操作是否顺畅、哪里容易误解。一次单人结果只报告个人观察值，置信区间和正式验收结论留空；双人 κ、真实危险识别和人群效率改善仍需正式数据。下载文件含练习答案，不能用于防作弊的盲法研究。

## 没有历史业务日志也能开始

已选择的实际目标是 `Changxin-YR/AIRLOCK` 的维护：登记真实缺陷、跟踪证据和处理真实文档缺项。已授权的仓库维护由 Codex 执行并保存过程，你不需要另外找公司索要日志。

目前已有 4 条连接器创建轨迹和 1 条 AIRLOCK 受控中转执行轨迹，任务类型仍集中在 Issue 创建。新导入工具整理前 4 条已有轨迹，不会把它们计算成 4 条新增操作。读取当前 Issue 得到的是“当前快照”，不能倒推当时的操作过程或审批事实。

原始记录、意图和个人标注保存在忽略的 `var/` 内；公开 Git 只保存工具、合成测试和脱敏数量/hash。先填写自己的单人标注表，后续找到第二位独立标注者再分别收集。模型建议不能填入真人答案。真实日志会随着有实际价值的维护任务积累，不能为增加样本数批量制造空任务。

本机已经准备好 `var/single-person-20261003/annotation-pack/`：阅读 `case-source.original.json` 的任务上下文，用 Excel/WPS 打开 `single-person.template.csv`。只填写这一份。`annotator_id` 用一个匿名编号；本人判断后明确填写 `source=human`、`human=true`，`independent` 按实际情况填写；标签选项见[完整填写说明](USER_ACTIONS_20261003.md#2-双人独立标注你可以直接把表格交给两个人)。事实不明时保留空白/unknown，并在 `uncertainty` 写明疑问。保存 CSV UTF-8 后告诉 Codex 路径即可，不需要手动编写 JSON。

Codex 使用的可复现入口如下；输出必须使用全新目录，原始输入和 hash 会保留：

```powershell
.\.venv\Scripts\python.exe -m benchmark.pilot import --cases var/single-person-20261003/annotation-pack/case-source.original.json --annotations var/single-person-20261003/annotation-pack/single-person.template.csv --source-reference '本人完成的单人先导；请记录真实时间与参与情况' --output var/single-person-20261003/result-v1
```

空表导入会报告等待本人输入，不能因为命令退出 0 就算有人参与。

## 身份在哪里配置

使用 [Auth0 控制台](https://manage.auth0.com/)；本项目已实现登录客户端，不需要你写 OAuth 代码。账户注册和本人登录/MFA 由你完成。

1. **Applications → APIs → Create API**：名称 `AIRLOCK`，Identifier 可填 `https://airlock.local/api`，签名算法 **RS256**。Identifier 是标识符，不要求该地址能访问。
2. 打开 API 的 **Access Token Settings → JSON Web Token (JWT) Profile**，选择 **RFC 9068**，保存。Token 有效期不超过本项目配置的 3600 秒。
3. **Applications → Applications → Create Application**：名称 `AIRLOCK Desktop`，类型 **Native**。登记精确回调 `http://127.0.0.1:8765/oidc/callback`，使用 Authorization Code + S256 PKCE。
4. 创建或选择自己的测试用户；需要验证 MFA 时，在租户的 MFA 设置中配置本人可用的因子和策略。客户端不能替代发行端 MFA 策略。
5. 把 **Domain/issuer、API Identifier、公开 Client ID** 和测试用户的公开 `sub` 告诉 Codex。可以提供公开 JWKS 地址；不要发送密码、私钥、Client Secret 或 access token。
6. Codex 准备本机公共配置、固定公钥/IP 和主体路由后，你在浏览器完成一次本人登录；随后复验令牌、路由、过期和撤销。

操作依据：[Native application](https://auth0.com/docs/get-started/auth0-overview/create-applications/native-apps)、[RFC 9068 配置](https://auth0.com/docs/get-started/apis/configure-access-token-profile)。尚未创建租户时，真实 IdP 验证继续受阻，不影响单人练习和代码测试。

## 云归档在哪里配置

使用 [AWS S3 控制台](https://console.aws.amazon.com/s3/)。云归档用于把审计检查点交给独立保管环境，Git 中的证据副本已有保留，但不是 WORM 归档。

1. 本人登录 AWS，先确定区域、预算和保留天数。当前模型实验的 3 元预算不包含云资源费用。
2. **General purpose buckets → Create bucket**：新建专用桶，保持 **Block Public Access**，启用 **Bucket Versioning**。
3. 在 **Advanced settings → Object Lock** 启用锁定。启用后不能关闭 Object Lock 或暂停版本控制；对象使用 COMPLIANCE 保留期时到期前不能正常删除。先决定实际保留期再写入。
4. 给独立保管环境配置仅访问此桶/前缀的专用身份。只告诉 Codex `region、bucket、prefix、retain_days` 和凭据所在环境；凭据只留在保管环境，不交给 Agent 或审批服务器。
5. Codex 准备归档配置和命令；保管端运行检查点写入、按版本读取与 hash/保留期复验，保存云端收据。

操作依据：[创建桶](https://docs.aws.amazon.com/AmazonS3/latest/userguide/creating-bucket.html)、[Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock-configure.html)。只有一名操作者时可以分离服务身份和保管身份，但不能宣称已有独立第二人保管。

## 通知在哪里查看

本机通知收件箱使用独立进程和独立数据文件，只保存健康告警代码及事件 ID。它提供浏览器查看入口，并按事件 ID 去重；没有批准、执行或重试业务操作的权限。本机页面不是手机推送或长期云端告警服务。

在项目 PowerShell 中设置两枚不同的、至少 16 个可打印 ASCII 字符的专用口令，不与审批或审计密钥共用。可以由密码管理器生成；以下输入隐藏，不会写入命令历史：

```powershell
$inboxWrite = Read-Host '输入收件箱专用写入口令' -AsSecureString
$inboxRead = Read-Host '输入收件箱专用只读口令' -AsSecureString
$env:AIRLOCK_INBOX_WRITE_TOKEN = [System.Net.NetworkCredential]::new('', $inboxWrite).Password
$env:AIRLOCK_INBOX_READ_TOKEN = [System.Net.NetworkCredential]::new('', $inboxRead).Password
Remove-Variable inboxWrite, inboxRead
try {
    .\.venv\Scripts\python.exe -m airlock.alert_inbox --database var/notifications/local.inbox.sqlite3 --port 8767
} finally {
    Remove-Item Env:AIRLOCK_INBOX_WRITE_TOKEN, Env:AIRLOCK_INBOX_READ_TOKEN -ErrorAction SilentlyContinue
}
```

打开 `http://127.0.0.1:8767/`，在页面输入只读口令。首次为空是正常的，页面不会凭空生成告警。终端 Ctrl+C 停止；重新启动同一文件保留已接收通知。不要把现有审批数据库用作收件箱文件。

发送端由部署操作者配置：将专用写入口令设置为 `AIRLOCK_ALERT_WEBHOOK_TOKEN`；本机联调配置为：

```json
{
  "endpoint": "http://127.0.0.1:8767/airlock/events",
  "address_pins": [],
  "allow_loopback_fixture": true,
  "timeout_seconds": 5.0
}
```

把它保存到 `var/ops/inbox-webhook.json`。在持有自己的服务运维凭据的独立终端运行：

```powershell
.\.venv\Scripts\python.exe scripts/operational_check.py --url http://127.0.0.1:8000 --output var/ops/status.json --alert-config var/ops/inbox-webhook.json --alert-state var/ops/notifications.sqlite3
```

该检查只在真实健康状态变化时投递；初次健康保持安静。需要先运行已配置的 AIRLOCK 服务；操作者凭据不交给 Agent。运维检查的健康/告警/投递失败退出码分别为 0/2/3。收件箱页面点击“刷新”查看，退出会清空浏览器内存中的口令和事件。

远程使用还需部署 HTTPS 和实际接收渠道；本轮没有创建付费资源或向外部收件人发消息。只有用户实际确认收到的通知，才记为真人送达验证。

## 由谁完成

| 工作 | 当前负责人/条件 |
|---|---|
| 程序、测试、日志导入、数据冻结、统计、GitHub 维护 | Codex |
| 单人练习和自己的第一份标注 | 你本人；完成后交本机文件路径 |
| 第二份独立标注、正式人群 A/B | 以后有真实参与者再进行 |
| Auth0 注册、本人登录/MFA | 你本人，配置文件由 Codex 准备 |
| 云账户、预算、保留天数、保管身份 | 你选择，接入代码和复验由 Codex 完成 |
| 模型状态、账单和本人面试 | 按本轮要求暂缓 |

完整原始目标仍在 126 项验收矩阵中。可用人员数、已收到的真实记录数和已通过的指标分别记账。
