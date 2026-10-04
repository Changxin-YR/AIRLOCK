# 工程基线归档（2026-10-04，Asia/Shanghai）

冻结源码与文档基线 `699adbd7c421f0c80fd0339ff69f892929cb28bd`。当时 main 为 `704b5035cf69f9a6c40c44eecd84c0d0741de849`，memory/progress 为 `a6b56d11ce93c1847d61e3199d2f4b8d5ef5ad41`；工作分支和 main 分别记录。

[工程归档包](AIRLOCK-project-baseline-699adbd.zip)包括该提交的源码 ZIP、完整源码 CI ZIP、原始任务及126目标、报告、矩阵和保留说明的快照。[ARCHIVE.json](ARCHIVE.json)绑定外层包的大小/hash；包内 CONTENTS.json 绑定每个载荷。历史 evidence 目录不递归打包，矩阵引用的其他历史结果继续保留在仓库 Git。

## 证据来源

源码验收锚点为 `533726aa72eeeb71d5c28d81ac84ad7b1a23dd3c` / CI37117971834；交付锚点为 `699adbd` / CI37118762214。两次各687 Python、6 JS、31原生浏览器及隔离集成通过。这是对应版本的历史结果；当前版本的验证使用独立收据。

本目录保留一次合成对照操作的原始执行记录：

| 文件 | 实际结果 |
|---|---|
| comparison.log / comparison.log.status.json | ENVIRONMENT BLOCKED，exit1：Windows受限执行环境拒绝新建临时SQLite文件 |
| comparison-rerun.log / comparison-rerun.log.status.json / comparison.json | PASS，exit0：相同脚本在普通用户环境执行，使用独立一次性合成库 |
| validation.log / validation.log.status.json | 当次归档与文档校验的原始收据，绑定其实际源码和路径 |
| checkpoint-validation.log / checkpoint-validation.log.status.json | 当前归档字节、历史来源与项目文档链接复核；以收据记录为准 |

对照操作中，无闸门1206→0；pending和拒绝后均1206；安全SELECT返回1206；新的明确批准请求执行后0，审计valid=true。审核者是自动化夹具，不能算真人完成记录。

`PROVENANCE.json`记录已发布前序产物的Git位置和字节身份；`PREVIOUS_MANIFEST.json`保留当时清单。原日志内路径、命令、SHA与退出码不回写。`verify_archive.py`通过Git对象验证这些来源，再检查当前包与文档，历史校验不冒充当前完整应用验收。

## 保留与边界

Git副本无自动到期，依赖历史/备份，不是独立云WORM。源码CI原Actions副本到期2027-01-01T10:55:17Z，交付CI原副本到期2027-01-01T11:09:37Z。前者完整包已包括在本归档；后者重复ZIP仅原Actions和本机缓存。var、数据库、个人原始日志和真实凭据未打包。

原始126目标继续由[逐项矩阵](../../docs/acceptance/COMPLETION_MATRIX.json)跟踪。项目用途与开发顺序见[开发计划](../../docs/PLAN.md)，安装接入见[项目首页](../../README.md)。
