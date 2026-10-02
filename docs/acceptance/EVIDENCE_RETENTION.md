# 证据去向与保留期限

基线 `704b5035cf69f9a6c40c44eecd84c0d0741de849`；核心复验 `266ad9e9daedcbfd5183f0402d1d5227f4a2a0b4`；最后 UI 修复 `b9de71085e9b3027b8127c4da6d7193d8f19ba88`。所有时间采用证据中 UTC。

| 保存位置 | 实際内容 | 期限与限制 |
|---|---|---|
| 工作分支 Git：`evidence/full-audit-20261002/` | 本机原状/中间/冻结检查日志、真实退出码收据、JUnit、逐例评测、延迟原始样本、PNG、研究自动化导出；GitHub CI 原始文本日志及 API 元数据 | 随 Git 历史长期保存，没有 Actions 式自动到期；仍依赖仓库及备份保留，不是 WORM/外部不可变存证 |
| 工作分支 Git：`docs/acceptance/` | 原始索引、原状与最终矩阵、审查报告、矩阵校验代码和证据说明 | 同上；原始完整任务正文在 `docs/CODEX_FULL_AUDIT_BRIEF.md` |
| Actions run 36986102382：artifact 11216944737 `acceptance-evidence` | Linux 原始运行包：源码 zip、截图、命令收据、真 Docker 报告、依赖/评测/时延等 | 90 天，API 明确到期 `2026-12-31T08:48:02Z`；935541 bytes；SHA256 `d5f0e6cde83689a0b472572c31d0072366f8c888430c6dbc59fb804f6e24cbd9` |
| Actions run 36986618577：artifact 11218125469 | 故意失败的日志及 exit23 收据 | 90 天，到期 `2026-12-31T08:53:28Z`；原始 CI 文本和元数据另已放入 Git |
| Actions run 36988565652：artifact 11218408231 | 最后 UI 代码提交的完整 Linux 原始运行包 | 90 天，到期 `2026-12-31T09:13:44Z`；936515 bytes；服务端 digest `sha256:30e078a97b7a17c98485f540fe29b28e8c11852960808903d7eb39739392ee51` |
| 后续正常 Actions | 以对应 run 的 metadata 为准；默认 retention-days=90 | 后续 URL 与 SHA 单列 `DELIVERY_STATE.json` 或 memory/progress，不冒用旧 run 的日期 |
| 仅本机忽略目录 `audit-inputs/` | 基线 traceback 中两个含临时合成 token 的未脱敏原文件、执行辅助脚本 | 不入 Git，无持久保留保证；Git 只保存脱敏副本及双向 hash 对照，原退出码不改 |
| 仅本机 `.firecrawl/` | 公开资料完整临时抓取缓存 | 不提交整篇第三方内容；保留引用、核验日期和选择性事实，缓存没有永久归档承诺 |

本轮没有下载并独立校验上述 Actions ZIP，也没有创建 Release 归档或外部永久存储。不能把 Git 中的 CI 文本当作完整 Linux artifact 的替代品；尤其 Linux 原始 Docker JSON 与 CI PNG 的完整包仍仅在 Actions。工具读取到的 job/step 成功与原始 log 支持 CI 结论，artifact metadata 的 digest 仅是服务端报告。

`ARCHIVE_MANIFEST.json` 对最终纳入 Git 的证据载荷逐文件记录字节数和 SHA256。`final/manifest.json` 是原始运行时清单：生成时自己的 `manifest.log` 仍在写入，故它对该单个自引用日志的 hash 不作为最终归档 hash。最终 hash 以根归档清单为准；所有原始报告保留，不回写其 SHA 或退出码。

`preview-final/` 与 `fixes/` 是中间结果，不代表最终冻结源；`final/` 绑定 266ad9e；`final-ui/` 绑定 b9de710。仅做文本脱敏的文件列在 `REDACTION_PROVENANCE.json`，其他原始业务证据未重算冒充新测试。
