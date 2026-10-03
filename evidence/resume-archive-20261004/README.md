# 简历阶段工程归档（2026-10-04，Asia/Shanghai）

冻结工作分支基线 `699adbd7c421f0c80fd0339ff69f892929cb28bd`；main 为 `704b5035cf69f9a6c40c44eecd84c0d0741de849`，当时 memory/progress 为 `a6b56d11ce93c1847d61e3199d2f4b8d5ef5ad41`。PR #1 为草稿、未合并。

[下载归档包](AIRLOCK-resume-baseline-699adbd.zip)。外部 [ARCHIVE.json](ARCHIVE.json) 保存包的字节数和 SHA256；包内 CONTENTS.json 逐项绑定载荷。包含该提交的 Git 源码归档、上一轮完整源码 CI ZIP、原始任务/126 目标、报告、矩阵和保留说明的快照。源码归档排除历史 evidence 目录；矩阵引用的其他历史证据仍在仓库 Git，并非全部复制到本包。

历史完整验证锚点：源码 `533726aa72eeeb71d5c28d81ac84ad7b1a23dd3c`，CI 37117971834；交付 `699adbd`，CI 37118762214。两次各 687 Python / 6 JS / 31 原生浏览器及隔离集成通过，具体边界和真实退出码在原始包内。这些是上一轮实测，不冒充本次新跑全套。

本次仅整理归档与简历材料，应用代码不变。确定性演示用现有脚本重新执行：

| 证据 | 结果 | 解释 |
|---|---|---|
| comparison.log / comparison.log.status.json | ENVIRONMENT BLOCKED，exit 1 | Windows 受限执行环境拒绝新建临时 SQLite 文件；原错误完整保留 |
| comparison-rerun.log / comparison-rerun.log.status.json / comparison.json | PASS，exit 0 | 经工具自动审批后在普通用户环境运行相同脚本；一次性合成数据，不访问现有库或真实凭据 |
| validation.log / validation.log.status.json | 以实际收据为准 | 包内文件/hash/源码提交、项目文档链接、演示原始数值与快照绑定校验 |

演示观察为：无闸门 1206→0；pending 和拒绝后均为 1206；安全读返回 1206；新的明确批准请求执行后为 0；审计 valid=true。审核者是自动化夹具，真人完成仍为 0，本轮模型调用为 0。

此归档与原证据在 Git 无自动到期，依赖历史/备份，不是独立云 WORM。源码 CI 原 Actions 副本到期 2027-01-01T10:55:17Z，交付 CI 原 Actions 副本到期 2027-01-01T11:09:37Z；完整源码 CI ZIP 已包括在本包，重复交付 ZIP 仍仅在原 Actions 和本机临时缓存。var、数据库、个人原始日志和真实凭据未打包。

简历阶段聚焦可解释的核心链路、演示和项目表述。原始 126 项保持 105 限定 PASS / 21 BLOCKED_EXTERNAL；功能展示优先级变化不将未完成目标改为通过。当前材料见[简历与演示版本](../../docs/RESUME_PORTFOLIO.md)。
